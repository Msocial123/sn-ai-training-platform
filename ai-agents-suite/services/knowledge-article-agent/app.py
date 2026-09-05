"""
Knowledge Article Agent -- auto-drafts a KB article from a resolved
incident, and checks a proposed article against existing ones for
duplicates. Mirrors Session 5 of the training.
"""
import json
import sys
from difflib import SequenceMatcher
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

sys.path.insert(0, "/app/shared")
import llm_client  # noqa: E402
import servicenow_client  # noqa: E402

app = FastAPI(title="Knowledge Article Agent")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

TICKETS = json.loads(Path("/app/data/sample_tickets.json").read_text())
# The resolved tickets double as a stand-in KB library for duplicate checking.
KB_LIBRARY = [t for t in TICKETS if t.get("resolution")]


def _find_ticket(ticket_id: str):
    # Same live-first, local-fallback pattern as now-assist-agent -- without
    # this, typing a real live-ServiceNow incident number into this tab
    # 404s even though the instance is connected and the ticket exists.
    live = servicenow_client.get_incident(ticket_id)
    if live:
        return {
            "id": live.get("number"),
            "short_description": live.get("short_description", ""),
            "description": live.get("description", ""),
            "resolution": live.get("close_notes", ""),
            "category": live.get("category", "General"),
        }
    for t in TICKETS:
        if t["id"] == ticket_id:
            return t
    return None


def _template_article(ticket: dict) -> dict:
    return {
        "title": f"How to resolve: {ticket['short_description']}",
        "symptoms": ticket["description"],
        "root_cause_and_resolution": ticket["resolution"],
        "category": ticket.get("category", "General"),
    }


class DraftRequest(BaseModel):
    ticket_id: str


class DuplicateCheckRequest(BaseModel):
    text: str


@app.get("/api/kb-library")
def kb_library():
    return [{"id": t["id"], "title": t["short_description"]} for t in KB_LIBRARY]


@app.post("/api/draft-article")
def draft_article(req: DraftRequest):
    ticket = _find_ticket(req.ticket_id)
    if not ticket:
        raise HTTPException(404, f"Ticket {req.ticket_id} not found")
    if not ticket.get("resolution"):
        raise HTTPException(400, "Ticket has no resolution text to draft an article from yet")

    llm_error = None
    if llm_client.is_configured():
        try:
            # max_tokens=220, not the 500 this started at: the self-hosted
            # 27B model measured as low as ~1.6 tokens/sec on this CPU-only
            # node under real load, and ollama_client's own internal
            # timeout for complete() is 170s -- 500 tokens (~312s worst
            # case) reliably blew through that, timed out, fell through a
            # dead Bedrock chain, and came back as a silent template
            # fallback. 220 tokens (~140s worst case) leaves real margin.
            # The system prompt already asks for "concise", so this isn't
            # a quality cut, just a budget that matches actual hardware.
            #
            # complete_fast(), not complete(): this is a person clicking a
            # button and watching a spinner, same as Virtual Agent chat --
            # and Incident Watcher's background summarization (also on
            # this one shared CPU inference slot) can run for a long
            # stretch on live-ServiceNow backlogs. The slow 27B model
            # measurably lost that contention and timed out here even
            # with the reduced token budget above; the fast model is what
            # actually came back with real content under the same load.
            body = llm_client.complete_fast(
                system_prompt=(
                    "You are a ServiceNow Knowledge Management AI agent. Draft a KB article from a "
                    "resolved incident with sections: Symptoms, Root Cause, Resolution Steps. Keep it concise."
                ),
                user_prompt=f"Incident: {ticket['short_description']}\nDescription: {ticket['description']}\nResolution notes: {ticket['resolution']}",
                max_tokens=220,
            )
            article = {"title": f"How to resolve: {ticket['short_description']}", "body": body}
        except llm_client.LLMError as e:
            llm_error = str(e)
            article = _template_article(ticket)
            article["llm_note"] = f"LLM call failed ({e}) -- fell back to template."
    else:
        article = _template_article(ticket)
        article["llm_note"] = "Template-generated -- configure a Bedrock or Anthropic key for AI-drafted prose."

    return {
        "source_ticket": ticket["id"],
        "llm_configured": llm_client.is_configured(),
        "llm_provider": llm_client.provider(),
        "llm_error": llm_error,
        "article": article,
    }


@app.post("/api/duplicate-check")
def duplicate_check(req: DuplicateCheckRequest):
    scored = []
    for article in KB_LIBRARY:
        ratio = SequenceMatcher(None, req.text.lower(), article["short_description"].lower()).ratio()
        scored.append({"id": article["id"], "title": article["short_description"], "similarity": round(ratio, 2)})
    scored.sort(key=lambda x: x["similarity"], reverse=True)
    top = scored[:3]
    return {
        "likely_duplicate": top[0]["similarity"] > 0.6 if top else False,
        "matches": top,
    }


@app.get("/healthz")
def healthz():
    return {
        "status": "ok",
        "servicenow_configured": servicenow_client.is_configured(),
        "llm_configured": llm_client.is_configured(),
        "llm_provider": llm_client.provider(),
    }
