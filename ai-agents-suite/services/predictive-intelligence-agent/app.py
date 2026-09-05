"""
Predictive Intelligence Agent -- auto-categorization, priority prediction,
and assignment group suggestion. Mirrors Session 6 of the training.

This is a deliberately transparent keyword/rule-based classifier, not a
trained ML model -- there's no historical labeled ticket volume available
to train one on yet. The syllabus itself flags this: "these agents need
solid datasets to capture real-time data." The rule table below is the
placeholder; swap it for a real trained classifier (e.g. scikit-learn
over exported ServiceNow incident history) once that data exists.
"""
import json
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

sys.path.insert(0, "/app/shared")
import servicenow_client  # noqa: E402

app = FastAPI(title="Predictive Intelligence Agent")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

TICKETS = json.loads(Path("/app/data/sample_tickets.json").read_text())

# keyword -> (category, subcategory, priority, assignment_group)
RULES = [
    (["crashloopbackoff", "pod", "kubernetes", "infra monitor", "namespace"], "Infrastructure", "Kubernetes Workload", "High", "Platform Engineering"),
    (["vpn", "cisco anyconnect", "remote access"], "Network", "VPN", "Medium", "Network Support"),
    (["password", "locked out", "expired", "reset"], "Account Access", "Password Reset", "Medium", "Service Desk"),
    (["mailbox", "outlook", "email"], "Email", "Access", "Low", "Email Support"),
    (["printer", "print"], "Hardware", "Printer", "Low", "Desktop Support"),
    (["onboarding", "new hire", "new employee"], "Account Access", "Onboarding", "Medium", "Service Desk"),
]
URGENT_KEYWORDS = ["cannot log in", "locked out", "down", "outage", "urgent", "all users", "crashloopbackoff"]

# ITSM-standard P1 (Critical) .. P4 (Low) mapping. P1 requires BOTH a High
# underlying priority AND an urgency signal (business-down language) --
# not just any High-priority ticket -- so P1 stays reserved for genuinely
# critical situations rather than being handed out routinely.
PRIORITY_LEVEL = {
    ("High", True): "P1",
    ("High", False): "P2",
    ("Medium", True): "P2",
    ("Medium", False): "P3",
    ("Low", True): "P3",
    ("Low", False): "P4",
}


def _classify(text: str) -> dict:
    lower = text.lower()
    for keywords, category, subcategory, priority, group in RULES:
        matched = [k for k in keywords if k in lower]
        if matched:
            urgent = any(k in lower for k in URGENT_KEYWORDS)
            if urgent:
                priority = "High"
            confidence = round(min(0.6 + 0.1 * len(matched), 0.92), 2)
            return {
                "category": category,
                "subcategory": subcategory,
                "priority": priority,
                "priority_level": PRIORITY_LEVEL[(priority, urgent)],
                "assignment_group": group,
                "matched_keywords": matched,
                "confidence": confidence,
            }
    return {
        "category": "General",
        "subcategory": "Unclassified",
        "priority": "Low",
        "priority_level": "P4",
        "assignment_group": "Service Desk",
        "matched_keywords": [],
        "confidence": 0.25,
    }


class PredictRequest(BaseModel):
    short_description: str


@app.get("/api/sample-tickets")
def sample_tickets():
    return [{"id": t["id"], "short_description": t["short_description"]} for t in TICKETS]


@app.post("/api/predict")
def predict(req: PredictRequest):
    return {"input": req.short_description, "prediction": _classify(req.short_description)}


@app.get("/api/predict-batch")
def predict_batch():
    """Runs prediction over the whole sample set -- powers the 'live demo'
    batch view in the UI."""
    return [{"id": t["id"], "short_description": t["short_description"], "prediction": _classify(t["short_description"])} for t in TICKETS]


@app.get("/healthz")
def healthz():
    return {"status": "ok", "servicenow_configured": servicenow_client.is_configured()}
