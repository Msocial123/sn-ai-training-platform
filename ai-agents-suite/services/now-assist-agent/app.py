"""
Now Assist Agent -- case summarization + solution recommendation.

Mirrors Session 3 of the training: given an incident, produce a short
plain-language summary and recommend a resolution based on similar past
tickets. Uses a real LLM if ANTHROPIC_API_KEY is configured, otherwise a
deterministic template fallback -- and pulls live ServiceNow data if
configured, otherwise the local sample dataset.
"""
import json
import re
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

sys.path.insert(0, "/app/shared")
import llm_client  # noqa: E402
import servicenow_client  # noqa: E402

app = FastAPI(title="Now Assist Agent")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

TICKETS = json.loads(Path("/app/data/sample_tickets.json").read_text())


def _find_ticket(ticket_id: str):
    live = servicenow_client.get_incident(ticket_id)
    if live:
        return {
            "id": live.get("number"),
            "short_description": live.get("short_description", ""),
            "description": live.get("description", ""),
            "resolution": live.get("close_notes", ""),
        }, True
    for t in TICKETS:
        if t["id"] == ticket_id:
            return t, False
    return None, False


def _keyword_overlap(a: str, b: str) -> int:
    words_a = set(re.findall(r"[a-z]{4,}", a.lower()))
    words_b = set(re.findall(r"[a-z]{4,}", b.lower()))
    return len(words_a & words_b)


def _template_summary(ticket: dict) -> str:
    desc = ticket["description"].strip()
    first_sentence = re.split(r"(?<=[.!?])\s", desc)[0]
    return f"{first_sentence} (auto-summarized -- configure ANTHROPIC_API_KEY for full generative summaries)"


def _recommend(ticket: dict) -> dict:
    resolved = [t for t in TICKETS if t.get("resolution") and t["id"] != ticket.get("id")]
    scored = sorted(resolved, key=lambda t: _keyword_overlap(ticket["description"], t["description"]), reverse=True)
    if not scored or _keyword_overlap(ticket["description"], scored[0]["description"]) == 0:
        return {"recommended_solution": "No sufficiently similar past incident found.", "based_on": None, "confidence": 0.0}
    best = scored[0]
    overlap = _keyword_overlap(ticket["description"], best["description"])
    return {
        "recommended_solution": best["resolution"],
        "based_on": best["id"],
        "confidence": round(min(0.5 + overlap * 0.08, 0.95), 2),
    }


class SummarizeRequest(BaseModel):
    ticket_id: str
    # Optional: callers that already have the incident text in hand (e.g.
    # the Incident Watcher, processing a just-created incident that isn't
    # in this service's own sample dataset or live ServiceNow yet) can
    # pass it inline instead of relying on lookup-by-id.
    short_description: str | None = None
    description: str | None = None
    # Background/bulk callers (Incident Watcher's poll loop, working
    # through potentially dozens of incidents unattended) should set this
    # -- it uses the faster/smaller Ollama model instead of the default
    # 27B one. On a CPU-only node with a single inference slot, a bulk
    # backlog on the slow model can monopolize the ONLY slot for a very
    # long time, starving the interactive callers (chat, the on-demand
    # Summarize button someone is actively watching) behind it -- which
    # is exactly what was reported as "Ollama not working." The on-demand
    # button still defaults to False (quality over speed, one ticket, one
    # person waiting a bounded amount of time).
    use_fast_model: bool = False


@app.get("/api/tickets")
def list_tickets():
    return TICKETS


@app.post("/api/summarize")
def summarize(req: SummarizeRequest):
    ticket, is_live = _find_ticket(req.ticket_id)
    if not ticket and req.short_description:
        # Not found by lookup, but the caller supplied the text directly
        # (e.g. a brand-new incident the Incident Watcher just picked up) --
        # use that instead of 404ing.
        ticket = {"id": req.ticket_id, "short_description": req.short_description, "description": req.description or req.short_description, "resolution": ""}
        is_live = False
    if not ticket:
        raise HTTPException(404, f"Ticket {req.ticket_id} not found")

    llm_error = None
    if llm_client.is_configured():
        try:
            complete_fn = llm_client.complete_fast if req.use_fast_model else llm_client.complete
            summary = complete_fn(
                system_prompt="You are a ServiceNow Now Assist agent. Summarize the incident in one or two plain-language sentences for a support agent skimming their queue.",
                user_prompt=f"Short description: {ticket['short_description']}\n\nFull description: {ticket['description']}",
                max_tokens=150,
            )
        except llm_client.LLMError as e:
            # A provider failure (throttled, timed out, misconfigured) must
            # never 500 this request -- degrade to the template instead.
            llm_error = str(e)
            summary = _template_summary(ticket)
    else:
        summary = _template_summary(ticket)

    recommendation = _recommend(ticket)

    return {
        "ticket_id": ticket.get("id", req.ticket_id),
        "source": "live ServiceNow" if is_live else "sample dataset",
        "summary": summary,
        "llm_configured": llm_client.is_configured(),
        "llm_provider": llm_client.provider(),
        "llm_error": llm_error,
        **recommendation,
    }


@app.get("/healthz")
def healthz():
    return {
        "status": "ok",
        "servicenow_configured": servicenow_client.is_configured(),
        "llm_configured": llm_client.is_configured(),
        "llm_provider": llm_client.provider(),
    }
