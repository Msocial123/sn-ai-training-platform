"""
Incident Watcher -- the actual "automatically track live incidents" loop.

Every POLL_INTERVAL_SECONDS, this:
  1. Looks for open/new incidents not yet processed -- BOTH live
     ServiceNow incidents (if connected) AND local ones (sample data,
     POST /api/simulate-incident, or infra-monitor's break reports) --
     these are combined, not either/or.
  2. For a "local" incident, if ServiceNow is connected, creates a real
     new incident for it first (it has no existing ticket yet).
  3. Calls TWO agents on every incident -- this is deliberately a
     multi-agent workflow, not one model doing everything:
       - Now Assist Agent (/api/summarize): narrative summary + a
         similar-past-incident recommendation.
       - Predictive Intelligence Agent (/api/predict): category +
         P1-P4 priority classification.
  4. If there's a real ServiceNow sys_id (existing or just-created),
     writes the summary + recommendation + priority back as a work note.
  5. Records the full result (summary, recommendation, category,
     priority) in an in-memory feed -- this feed is what the Now Assist
     tab's incident list renders, so every incident that occurs shows up
     there automatically, already summarized and classified.

This is the piece that was missing before: every other agent is
on-demand (a person clicks a button). This one runs on its own.
"""
import json
import sys
import time
from pathlib import Path

import requests
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

sys.path.insert(0, "/app/shared")
import servicenow_client  # noqa: E402

app = FastAPI(title="Incident Watcher")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

NOW_ASSIST_URL = "http://now-assist-agent:8080/api/summarize"
PREDICTIVE_URL = "http://predictive-intelligence-agent:8080/api/predict"
POLL_INTERVAL_SECONDS = 15

# Local incident pool used when ServiceNow isn't configured -- seeded from
# the sample dataset's genuinely "Open" tickets, plus anything added via
# the simulate endpoint (which mimics a new incident being created).
_TICKETS = json.loads(Path("/app/data/sample_tickets.json").read_text())
_LOCAL_OPEN = [dict(t) for t in _TICKETS if t.get("status") == "Open"]

PROCESSED_IDS: set[str] = set()
FEED: list[dict] = []  # most recent first
STATS = {"polls": 0, "processed": 0, "last_poll_at": None, "errors": 0}

# PROCESSED_IDS/FEED persisted to the state PVC (see
# k8s/services/incident-watcher.yaml) so a pod restart -- which happens
# on every `deploy.sh` run, not just a crash -- doesn't forget everything
# already summarized. Without this, every redeploy re-discovered the
# ENTIRE live-ServiceNow backlog (dozens of incidents) as "new" and
# re-ran it through the LLM from scratch, monopolizing Ollama's single
# CPU inference slot for a very long time and starving interactive
# requests behind it -- the concrete, reproduced cause of a real "Ollama
# isn't working" report. This is a plain JSON file, not a database:
# fine for this volume of state, and easy to inspect/delete by hand.
STATE_FILE = Path("/app/state/state.json")


def _load_state():
    if not STATE_FILE.exists():
        return
    try:
        data = json.loads(STATE_FILE.read_text())
        PROCESSED_IDS.update(data.get("processed_ids", []))
        FEED.extend(data.get("feed", []))
        STATS.update(data.get("stats", {}))
        print(f"[incident-watcher] restored {len(PROCESSED_IDS)} processed id(s), {len(FEED)} feed entries from state file", flush=True)
    except (json.JSONDecodeError, OSError) as e:
        # A corrupt/unreadable state file must never block startup -- worst
        # case is the same backlog-replay this file exists to avoid, not a
        # crash loop.
        print(f"[incident-watcher] could not read state file, starting fresh: {e}", flush=True)


def _save_state():
    try:
        STATE_FILE.write_text(json.dumps({
            "processed_ids": list(PROCESSED_IDS),
            "feed": FEED,
            "stats": STATS,
        }))
    except OSError as e:
        print(f"[incident-watcher] could not write state file: {e}", flush=True)


_load_state()


def _candidate_incidents():
    """Always returns BOTH live ServiceNow incidents (if connected) AND
    local ones (sample/simulated/infra-reported) -- these are not
    mutually exclusive. A local incident has no existing ServiceNow
    ticket to look up (it originated here, e.g. from infra-monitor), so
    it's tagged kind="local" and _process_incident creates a brand-new
    real incident for it when ServiceNow is connected, rather than being
    silently dropped just because live incidents also exist."""
    candidates = []

    live = servicenow_client.list_open_incidents()
    if live is not None:
        candidates += [{
            "id": i.get("number"), "sys_id": i.get("sys_id"),
            "short_description": i.get("short_description", ""), "description": i.get("description", ""),
            "kind": "live",
        } for i in live]

    candidates += [{
        "id": t["id"], "sys_id": None,
        "short_description": t["short_description"], "description": t.get("description", t["short_description"]),
        "kind": "local",
    } for t in _LOCAL_OPEN]

    return candidates


def _process_incident(incident: dict):
    started = time.time()
    incident_id = incident["id"]
    sys_id = incident.get("sys_id")
    source = "live ServiceNow" if incident["kind"] == "live" else "sample dataset / simulated"

    # A "local" incident (infra-monitor report, simulated demo incident)
    # has no real ServiceNow ticket yet -- create one now if connected,
    # so it becomes a genuine incident, not just a local-only record.
    if incident["kind"] == "local" and servicenow_client.is_configured():
        created = servicenow_client.create_incident(incident["short_description"], incident["description"])
        if created and created.get("number"):
            incident_id = created["number"]
            sys_id = created["sys_id"]
            source = "created in ServiceNow (from infra-monitor / simulated report)"

    try:
        # Pass the text inline, not just the id -- Now Assist's own sample
        # dataset/live-lookup won't know about an incident this watcher
        # just discovered, so relying on lookup-by-id alone 404s. See
        # now-assist-agent's SummarizeRequest for the matching fallback.
        resp = requests.post(NOW_ASSIST_URL, json={
            "ticket_id": incident_id,
            "short_description": incident["short_description"],
            "description": incident["description"],
            # This loop runs unattended and, after any restart, can face a
            # backlog of dozens of incidents at once (PROCESSED_IDS is
            # in-memory -- see BATCH_SIZE_PER_POLL comment below). On a
            # CPU-only node with a single Ollama inference slot, the slow
            # 27B model here would monopolize that slot for a very long
            # time and starve interactive requests (chat, someone waiting
            # on the on-demand Summarize button) behind it -- this WAS the
            # concrete cause of a real "Ollama isn't working" report.
            "use_fast_model": True,
        }, timeout=180)  # CPU-only inference can still take well over a minute even on the fast model
        resp.raise_for_status()
        result = resp.json()
    except requests.RequestException as e:
        STATS["errors"] += 1
        FEED.insert(0, {
            "incident_id": incident_id,
            "short_description": incident["short_description"],
            "status": "error",
            "error": str(e),
            "processed_at": time.time(),
        })
        PROCESSED_IDS.add(incident["id"])  # dedupe on the ORIGINAL id, not the created one
        _save_state()
        return

    # Second agent, same incident -- category + P1-P4 priority. Best-effort:
    # a classification failure shouldn't block the summary from landing.
    classification = {"category": "Unclassified", "priority_level": "P4"}
    try:
        pred_resp = requests.post(PREDICTIVE_URL, json={"short_description": incident["short_description"]}, timeout=15)
        pred_resp.raise_for_status()
        classification = pred_resp.json().get("prediction", classification)
    except requests.RequestException:
        pass

    written_back = False
    if sys_id:
        note = (
            f"[Incident Watcher] Auto-summary: {result.get('summary')}\n"
            f"Recommended resolution: {result.get('recommended_solution')}\n"
            f"Category: {classification.get('category')} | Priority: {classification.get('priority_level')}"
        )
        written_back = servicenow_client.add_work_note(sys_id, note)

    FEED.insert(0, {
        "incident_id": incident_id,
        "short_description": incident["short_description"],
        "status": "processed",
        "summary": result.get("summary"),
        "recommended_solution": result.get("recommended_solution"),
        "confidence": result.get("confidence"),
        "llm_provider": result.get("llm_provider"),
        "category": classification.get("category"),
        "priority_level": classification.get("priority_level"),
        "assignment_group": classification.get("assignment_group"),
        "written_back_to_servicenow": written_back,
        "source": source,
        "processing_seconds": round(time.time() - started, 2),
        "processed_at": time.time(),
    })
    del FEED[200:]  # cap feed size -- 200 is enough history to show "every incident" meaningfully
    STATS["processed"] += 1
    PROCESSED_IDS.add(incident["id"])  # dedupe on the ORIGINAL id, not the created one
    _save_state()


BATCH_SIZE_PER_POLL = 3
# PROCESSED_IDS is in-memory, so a pod restart forgets everything it has
# already summarized -- the very next poll then sees the FULL live-
# ServiceNow backlog (potentially dozens of incidents) as "new" all at
# once. Processing all of them in one unbroken loop iteration -- with
# nothing else able to get a turn on Ollama's single CPU inference slot
# for however many minutes that backlog takes -- is what actually
# produced a real "Ollama isn't working" report: every other request
# (chat, on-demand summarize) was simply queued behind it. Capping how
# many incidents get processed per poll, and letting the loop's own
# sleep run between batches, spreads a backlog out over multiple 15s
# ticks instead of one long burst, so interactive requests get a
# realistic chance to slot in between batches. It does mean a big
# backlog takes longer to fully drain -- that trade favors the person
# actively waiting on a response over unattended catch-up work.


def _poll_loop():
    while True:
        try:
            processed_this_poll = 0
            for incident in _candidate_incidents():
                if processed_this_poll >= BATCH_SIZE_PER_POLL:
                    break
                if incident["id"] not in PROCESSED_IDS:
                    _process_incident(incident)
                    processed_this_poll += 1
            STATS["polls"] += 1
            STATS["last_poll_at"] = time.time()
        except Exception as e:  # the poll loop itself must never die
            STATS["errors"] += 1
            print(f"[incident-watcher] poll loop error: {e}", flush=True)
        time.sleep(POLL_INTERVAL_SECONDS)


@app.on_event("startup")
def start_watcher():
    # A plain background thread, not an asyncio task -- every call inside
    # the loop (requests to now-assist-agent, to ServiceNow) is blocking,
    # and wrapping blocking calls in an asyncio.create_task() ties up the
    # WHOLE single-threaded event loop for as long as that work takes --
    # including /healthz, which is why the first real poll against a live
    # ServiceNow instance (with real demo-data incident volume) made this
    # pod look stuck/unready for minutes. A real thread runs genuinely in
    # parallel with uvicorn's event loop instead.
    import threading
    threading.Thread(target=_poll_loop, daemon=True).start()


class SimulateRequest(BaseModel):
    short_description: str
    description: str = ""


@app.post("/api/simulate-incident")
def simulate_incident(req: SimulateRequest):
    """Demo trigger: mimics a brand-new incident being created. The
    watcher's own poll loop picks it up within POLL_INTERVAL_SECONDS --
    this endpoint does NOT process it synchronously, on purpose, so what
    you see afterward in /api/feed is the real automatic pipeline, not a
    canned response."""
    new_id = f"INC-SIM-{int(time.time())}"
    _LOCAL_OPEN.append({
        "id": new_id,
        "short_description": req.short_description,
        "description": req.description or req.short_description,
        "status": "Open",
    })
    return {"queued_incident_id": new_id, "will_be_picked_up_within_seconds": POLL_INTERVAL_SECONDS}


@app.get("/api/feed")
def feed():
    return {
        "stats": STATS,
        "servicenow_configured": servicenow_client.is_configured(),
        "servicenow_last_error": servicenow_client.LAST_ERROR,
        "feed": FEED,
    }


@app.get("/healthz")
def healthz():
    return {"status": "ok", "servicenow_configured": servicenow_client.is_configured(), **STATS}
