"""
Process Mining Agent -- discovers how the incident-resolution process
actually runs (vs. how it's designed) from event-log timestamps, and
surfaces the slowest step. Mirrors Session 8's mini-demo.

Uses a synthetic event log (event_log.json, generated to look like
typical ITSM step timings) since no real process-mining event export is
connected yet.
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

sys.path.insert(0, "/app/shared")
import servicenow_client  # noqa: E402

app = FastAPI(title="Process Mining Agent")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

EVENT_LOG = json.loads(Path("/app/data/event_log.json").read_text())


@app.get("/api/bottleneck-report")
def bottleneck_report():
    durations_by_step = defaultdict(list)
    for case in EVENT_LOG:
        events = sorted(case["events"], key=lambda e: e["timestamp_minutes"])
        for i in range(len(events) - 1):
            step_name = f"{events[i]['step']} -> {events[i+1]['step']}"
            duration = events[i + 1]["timestamp_minutes"] - events[i]["timestamp_minutes"]
            durations_by_step[step_name].append(duration)

    report = []
    for step, durations in durations_by_step.items():
        avg = sum(durations) / len(durations)
        report.append({"transition": step, "avg_minutes": round(avg, 1), "sample_size": len(durations), "max_minutes": max(durations)})

    report.sort(key=lambda r: r["avg_minutes"], reverse=True)
    bottleneck = report[0] if report else None

    return {
        "cases_analyzed": len(EVENT_LOG),
        "bottleneck": bottleneck,
        "all_transitions": report,
    }


@app.get("/api/event-log")
def event_log():
    return EVENT_LOG


@app.get("/healthz")
def healthz():
    return {"status": "ok", "servicenow_configured": servicenow_client.is_configured()}
