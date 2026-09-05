"""
Password Reset Agent -- simulates the end-to-end automated password-reset
workflow from Session 7: chat trigger -> Flow Designer -> Integration
Hub/RPA credential reset -> approval (for privileged accounts) ->
notification. Returns a step-by-step execution log so the UI can show the
workflow actually running, not just a final result.

This simulates the orchestration/state machine -- it does not perform a
real Active Directory reset (no directory is connected). Swap
`_execute_reset_step` for a real Integration Hub/AD call once one exists.
"""
import sys
import time
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

sys.path.insert(0, "/app/shared")
import servicenow_client  # noqa: E402

app = FastAPI(title="Password Reset Agent")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

PRIVILEGED_USERNAMES = {"admin", "root", "svc-backup", "domainadmin"}


class ResetRequest(BaseModel):
    username: str
    requested_via: str = "chat"


def _build_workflow(username: str):
    needs_approval = username.lower() in PRIVILEGED_USERNAMES
    steps = [
        {"step": "Request received", "detail": f"Password reset requested for '{username}' via {{requested_via}}", "actor": "Virtual Agent"},
        {"step": "Flow Designer triggered", "detail": "Flow 'Automated Password Reset' started", "actor": "Flow Designer"},
        {"step": "Identity verification", "detail": "Verified requester identity against HR record", "actor": "Flow Designer"},
    ]
    if needs_approval:
        steps.append({"step": "Approval required", "detail": f"'{username}' is a privileged account -- routed to manager for approval", "actor": "Approval Workflow"})
        steps.append({"step": "Approved", "detail": "Manager approved the reset request", "actor": "Approval Workflow"})
    steps += [
        {"step": "Credential reset executed", "detail": "Integration Hub/RPA action reset the AD password and generated a temporary credential", "actor": "Integration Hub / RPA"},
        {"step": "Notification sent", "detail": f"Temporary credential delivered to '{username}' via secure channel", "actor": "Notification"},
        {"step": "Incident closed", "detail": "Ticket auto-closed with resolution notes attached", "actor": "Flow Designer"},
    ]
    return steps


@app.post("/api/reset-request")
def reset_request(req: ResetRequest):
    if not req.username.strip():
        raise HTTPException(400, "username is required")

    workflow_id = str(uuid.uuid4())[:8]
    steps = _build_workflow(req.username)
    now = time.time()
    log = []
    for i, step in enumerate(steps):
        log.append({
            **step,
            "detail": step["detail"].replace("{requested_via}", req.requested_via),
            "timestamp_offset_seconds": i * 2,
            "status": "completed",
        })

    return {
        "workflow_id": workflow_id,
        "username": req.username,
        "total_steps": len(log),
        "log": log,
        "servicenow_configured": servicenow_client.is_configured(),
    }


@app.get("/healthz")
def healthz():
    return {"status": "ok"}
