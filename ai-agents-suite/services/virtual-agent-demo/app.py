"""
Virtual Agent demo -- lightweight conversational agent covering the two
scenarios called out in Session 8: chat-based ticket status check, and
kicking off a password reset. Intent matching is keyword-based (a real
ServiceNow Virtual Agent uses NLU trained on your topic library) -- this
is a UI-complete stand-in for the live mini-demo.
"""
import json
import re
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

sys.path.insert(0, "/app/shared")
import llm_client  # noqa: E402
import servicenow_client  # noqa: E402

app = FastAPI(title="Virtual Agent Demo")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

TICKETS = json.loads(Path("/app/data/sample_tickets.json").read_text())
SESSIONS: dict[str, dict] = {}


class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"


# Standard out-of-box ServiceNow incident.state values -- the Table API
# returns these as bare numeric strings unless sysparm_display_value is
# requested, so a live lookup needs this to show a human label at all.
_STATE_LABELS = {"1": "New", "2": "In Progress", "3": "On Hold", "6": "Resolved", "7": "Closed", "8": "Canceled"}


def _find_ticket(ticket_id: str):
    # Live-first, local-fallback -- without this, asking about a real
    # live-ServiceNow ticket number in chat always came back "couldn't
    # find" even though the instance is connected and the ticket exists.
    live = servicenow_client.get_incident(ticket_id)
    if live:
        state = str(live.get("state", ""))
        return {
            "id": live.get("number"),
            "short_description": live.get("short_description", ""),
            "status": _STATE_LABELS.get(state, state or "Unknown"),
        }
    return next((t for t in TICKETS if t["id"].lower() == ticket_id.lower()), None)


@app.post("/api/chat")
def chat(req: ChatRequest):
    text = req.message.strip()
    lower = text.lower()
    session = SESSIONS.setdefault(req.session_id, {"awaiting": None})

    # Follow-up: we previously asked for a ticket number
    if session["awaiting"] == "ticket_id":
        m = re.search(r"INC\d+", text.upper())
        session["awaiting"] = None
        if not m:
            return {"reply": "That doesn't look like a valid ticket number (e.g. INC0010001). Could you try again?"}
        ticket = _find_ticket(m.group(0))
        if not ticket:
            return {"reply": f"I couldn't find ticket {m.group(0)}. Please check the number and try again."}
        return {"reply": f"Ticket {ticket['id']} — \"{ticket['short_description']}\" — status: {ticket['status']}."}

    if any(kw in lower for kw in ["status", "ticket", "incident"]):
        m = re.search(r"INC\d+", text.upper())
        if m:
            ticket = _find_ticket(m.group(0))
            if ticket:
                return {"reply": f"Ticket {ticket['id']} — \"{ticket['short_description']}\" — status: {ticket['status']}."}
            return {"reply": f"I couldn't find ticket {m.group(0)}."}
        session["awaiting"] = "ticket_id"
        return {"reply": "Sure — what's the ticket number? (e.g. INC0010001)"}

    if any(kw in lower for kw in ["password", "reset", "locked out"]):
        return {
            "reply": "I can start a password reset for you. This routes through the Automated Password-Reset Agent — head to that tab and enter your username to see it run.",
            "suggested_tab": "password-reset",
        }

    if any(kw in lower for kw in ["agent", "human", "person", "escalate"]):
        return {"reply": "Escalating you to a live agent now. Estimated wait time: 3 minutes."}

    if any(kw in lower for kw in ["hi", "hello", "hey"]):
        return {"reply": "Hi! I can check a ticket's status or start a password reset. What do you need?"}

    # No specific action matched -- these three above stay deterministic
    # (a real ServiceNow Virtual Agent also routes recognized intents to
    # a fixed flow), but for genuinely open-ended messages, hand off to
    # the LLM if one's configured instead of a canned line.
    if llm_client.is_configured():
        try:
            # complete_fast(): chat is the one place a 1-3 minute reply from
            # the 27B model is a genuinely broken experience -- use the
            # smaller/quicker qwen3:8b here instead of complete()'s default.
            reply = llm_client.complete_fast(
                system_prompt=(
                    "You are a ServiceNow IT support Virtual Agent. Answer briefly and helpfully. "
                    "If the user needs a ticket status lookup or a password reset, tell them to ask "
                    "for that directly (e.g. 'check ticket INC0010001' or 'reset my password')."
                ),
                user_prompt=text,
                max_tokens=150,
            )
            return {"reply": reply, "llm_provider": llm_client.provider()}
        except llm_client.LLMError:
            pass  # fall through to the deterministic fallback below

    return {"reply": "I can help check a ticket status or start a password reset — try asking about one of those, or say 'agent' to escalate to a human."}


@app.get("/healthz")
def healthz():
    return {
        "status": "ok",
        "servicenow_configured": servicenow_client.is_configured(),
        "llm_configured": llm_client.is_configured(),
        "llm_provider": llm_client.provider(),
    }
