"""
Infra Monitor -- the agentic AIOps loop: detect -> correlate/dedupe ->
reason -> propose a fix -> wait for human approval -> execute -> close
the loop back to ServiceNow.

Design note on "reasoning": the human-readable summary comes from an LLM
(via Now Assist / Bedrock), but WHICH ACTION to propose comes from a
deterministic playbook keyed on the diagnosed problem type, not an LLM
guess. This is deliberate -- letting a model freely choose which command
to run against real infrastructure is a real reliability risk (a
hallucinated or overly aggressive action), so narrative reasoning and
action selection are kept separate. That playbook is also exactly what a
human approver reviews before anything executes.

Every poll cycle:
  1. Lists pods in the namespaces WE own (never participant-*).
  2. Diagnoses problems (CrashLoopBackOff, high restart count).
  3. Correlates by (namespace, app label, problem type) -- a recurrence
     of an already-known, still-active problem does NOT create a new
     incident or a new approval request; it just increments an
     occurrence counter and adds a work note. This is the
     deduplication/noise-reduction layer: one incident per distinct
     problem, not one per raw pod-crash event.
  4. For a genuinely NEW problem: gets an LLM narrative summary, creates
     a real ServiceNow incident, and queues a PROPOSED remediation
     action -- nothing executes automatically.
  5. A human approves or rejects via /api/proposals/{id}/approve|reject.
     Only on approval does this ever touch the cluster (delete the
     unhealthy pod so its Deployment recreates it) -- and the outcome is
     written back to the ServiceNow incident either way.
"""
import sys
import time
import uuid
from pathlib import Path

import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

sys.path.insert(0, "/app/shared")
import servicenow_client  # noqa: E402

app = FastAPI(title="Infra Monitor")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

K8S_API = "https://kubernetes.default.svc"
TOKEN = Path("/var/run/secrets/kubernetes.io/serviceaccount/token").read_text().strip()
CA_BUNDLE = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
K8S_HEADERS = {"Authorization": f"Bearer {TOKEN}"}

NOW_ASSIST_URL = "http://now-assist-agent:8080/api/summarize"

# Only infrastructure WE deployed this session -- never participant-*,
# never kube-system/karpenter (see k8s/infra-monitor-rbac.yaml).
MONITORED_NAMESPACES = ["ai-agents", "trainer", "observability", "monitoring", "kubernetes-dashboard"]
RESTART_THRESHOLD = 5
POLL_INTERVAL_SECONDS = 20
CORRELATION_WINDOW_SECONDS = 900  # 15 min -- recurrences inside this window dedupe onto the same incident

# Deterministic action playbook, keyed by diagnosed problem type. This is
# the "what to do about it" -- separate from the LLM's "here's what
# happened in plain English" narrative.
PLAYBOOK = {
    "CrashLoopBackOff": {
        "action_type": "restart_pod",
        "description": "Delete the affected pod(s) so the owning Deployment recreates them fresh. If the same problem recurs after this, the container image/command itself needs investigation -- this action only clears the symptom.",
        "risk": "low",
    },
    "HighRestarts": {
        "action_type": "restart_pod",
        "description": "Delete the affected pod(s) to reset their restart count via recreation.",
        "risk": "low",
    },
}

# --- In-memory state -------------------------------------------------------
# CORRELATIONS: "namespace/app_label/problem_type" -> tracking dict
CORRELATIONS: dict[str, dict] = {}
# PROPOSALS: proposal_id -> proposal dict (pending + resolved, newest first via list)
PROPOSALS: dict[str, dict] = {}
PROPOSAL_ORDER: list[str] = []  # newest first
STATS = {"polls": 0, "problems_detected": 0, "incidents_created": 0, "recurrences_deduped": 0, "actions_executed": 0, "errors": 0, "last_poll_at": None}


def _list_pods(namespace: str):
    resp = requests.get(f"{K8S_API}/api/v1/namespaces/{namespace}/pods", headers=K8S_HEADERS, verify=CA_BUNDLE, timeout=15)
    resp.raise_for_status()
    return resp.json().get("items", [])


def _delete_pod(namespace: str, name: str):
    resp = requests.delete(f"{K8S_API}/api/v1/namespaces/{namespace}/pods/{name}", headers=K8S_HEADERS, verify=CA_BUNDLE, timeout=15)
    resp.raise_for_status()


def _diagnose(pod: dict):
    """Returns (problem_type, detail) if this pod is unhealthy, else None."""
    for cs in pod.get("status", {}).get("containerStatuses", []):
        waiting = cs.get("state", {}).get("waiting", {})
        restarts = cs.get("restartCount", 0)
        if waiting.get("reason") == "CrashLoopBackOff":
            return "CrashLoopBackOff", f"container '{cs['name']}' is in CrashLoopBackOff ({restarts} restarts)"
        if restarts >= RESTART_THRESHOLD:
            return "HighRestarts", f"container '{cs['name']}' has restarted {restarts} times (threshold {RESTART_THRESHOLD})"
    return None, None


def _llm_summary(short_description: str, description: str) -> dict:
    """Gets a narrative summary from Now Assist. We deliberately ignore its
    'recommended_solution' for infra problems -- that's matched against an
    IT-helpdesk ticket dataset with nothing relevant to Kubernetes."""
    try:
        resp = requests.post(NOW_ASSIST_URL, json={
            "ticket_id": f"infra-{uuid.uuid4().hex[:8]}",
            "short_description": short_description,
            "description": description,
        }, timeout=180)  # CPU-only inference on the self-hosted 27B model can take well over a minute
        resp.raise_for_status()
        body = resp.json()
        return {"summary": body.get("summary"), "llm_provider": body.get("llm_provider")}
    except requests.RequestException as e:
        return {"summary": None, "llm_provider": None, "error": str(e)}


def _new_proposal(correlation_key: str, namespace: str, app_label: str, problem_type: str, detail: str, incident_number, sys_id):
    play = PLAYBOOK.get(problem_type, {"action_type": "manual_review", "description": "No automated playbook for this problem type -- needs manual investigation.", "risk": "unknown"})
    pid = uuid.uuid4().hex[:10]
    proposal = {
        "id": pid,
        "correlation_key": correlation_key,
        "namespace": namespace,
        "app_label": app_label,
        "problem_type": problem_type,
        "detail": detail,
        "incident_number": incident_number,
        "sys_id": sys_id,
        "action_type": play["action_type"],
        "action_description": play["description"],
        "risk": play["risk"],
        "status": "pending",
        "occurrence_count": 1,
        "created_at": time.time(),
        "resolved_at": None,
        "resolved_by": None,
        "execution_result": None,
    }
    PROPOSALS[pid] = proposal
    PROPOSAL_ORDER.insert(0, pid)
    del PROPOSAL_ORDER[200:]
    return proposal


def _handle_problem(namespace: str, pod_name: str, app_label: str, problem_type: str, detail: str):
    key = f"{namespace}/{app_label}/{problem_type}"
    now = time.time()
    STATS["problems_detected"] += 1
    existing = CORRELATIONS.get(key)

    if existing and (now - existing["last_seen"]) < CORRELATION_WINDOW_SECONDS:
        # Recurrence of an already-known, still-active problem -- dedupe.
        existing["last_seen"] = now
        existing["occurrence_count"] += 1
        existing["latest_pod"] = pod_name
        STATS["recurrences_deduped"] += 1
        if existing.get("sys_id"):
            servicenow_client.add_work_note(
                existing["sys_id"],
                f"[Infra Monitor] Recurred (occurrence #{existing['occurrence_count']}). Latest affected pod: {pod_name}.",
            )
        # If there's already a PENDING proposal, just bump it -- don't
        # spam a second approval request for the same undecided problem.
        # But if the last one was already resolved (approved/rejected)
        # and the problem is happening AGAIN, that's new, actionable
        # information -- create a fresh proposal against the SAME
        # incident (dedup means one ticket per problem, not "a human can
        # only ever act on it once").
        pid = existing.get("pending_proposal_id")
        if pid and PROPOSALS.get(pid, {}).get("status") == "pending":
            PROPOSALS[pid]["occurrence_count"] += 1
            PROPOSALS[pid]["detail"] = detail
        else:
            proposal = _new_proposal(key, namespace, app_label, problem_type, detail, existing.get("incident_number"), existing.get("sys_id"))
            proposal["occurrence_count"] = existing["occurrence_count"]
            existing["pending_proposal_id"] = proposal["id"]
        return

    # New (or cooled-down) problem: get an LLM narrative, open a real
    # ServiceNow incident, and queue a proposal -- but do NOT touch the
    # cluster yet.
    short_description = f"[Infra Monitor] {problem_type} detected: {app_label} in {namespace}"
    description = f"Pod {pod_name} in namespace {namespace}: {detail}."
    llm = _llm_summary(short_description, description)

    incident_number, sys_id = None, None
    if servicenow_client.is_configured():
        created = servicenow_client.create_incident(short_description, description)
        if created:
            incident_number, sys_id = created.get("number"), created.get("sys_id")
            STATS["incidents_created"] += 1
            play = PLAYBOOK.get(problem_type, {})
            note = (
                f"[Infra Monitor] Auto-detected and diagnosed.\n"
                f"Summary: {llm.get('summary') or description}\n"
                f"Proposed remediation (awaiting human approval): {play.get('description', 'manual review needed')}\n"
                f"Risk: {play.get('risk', 'unknown')}"
            )
            servicenow_client.add_work_note(sys_id, note)

    proposal = _new_proposal(key, namespace, app_label, problem_type, detail, incident_number, sys_id)
    CORRELATIONS[key] = {
        "incident_number": incident_number, "sys_id": sys_id,
        "first_seen": now, "last_seen": now, "occurrence_count": 1,
        "latest_pod": pod_name, "pending_proposal_id": proposal["id"],
    }


def _poll_once():
    for ns in MONITORED_NAMESPACES:
        try:
            pods = _list_pods(ns)
        except requests.RequestException as e:
            STATS["errors"] += 1
            print(f"[infra-monitor] failed to list pods in {ns}: {e}", flush=True)
            continue

        for pod in pods:
            problem_type, detail = _diagnose(pod)
            if not problem_type:
                continue
            app_label = pod.get("metadata", {}).get("labels", {}).get("app", pod["metadata"]["name"])
            try:
                _handle_problem(ns, pod["metadata"]["name"], app_label, problem_type, detail)
            except Exception as e:
                STATS["errors"] += 1
                print(f"[infra-monitor] error handling problem for {ns}/{pod['metadata']['name']}: {e}", flush=True)


def _poll_loop():
    while True:
        try:
            _poll_once()
            STATS["polls"] += 1
            STATS["last_poll_at"] = time.time()
        except Exception as e:
            STATS["errors"] += 1
            print(f"[infra-monitor] poll loop error: {e}", flush=True)
        time.sleep(POLL_INTERVAL_SECONDS)


@app.on_event("startup")
def start_monitor():
    import threading
    threading.Thread(target=_poll_loop, daemon=True).start()


# --- Human-in-the-loop approval API -----------------------------------------

class ApprovalRequest(BaseModel):
    actor: str = "unknown"
    reason: str = ""


@app.get("/api/proposals")
def list_proposals(status: str | None = None):
    items = [PROPOSALS[pid] for pid in PROPOSAL_ORDER if pid in PROPOSALS]
    if status:
        items = [p for p in items if p["status"] == status]
    return {"proposals": items, "pending_count": sum(1 for p in PROPOSALS.values() if p["status"] == "pending")}


@app.post("/api/proposals/{proposal_id}/approve")
def approve_proposal(proposal_id: str, req: ApprovalRequest):
    proposal = PROPOSALS.get(proposal_id)
    if not proposal:
        raise HTTPException(404, "proposal not found")
    if proposal["status"] != "pending":
        raise HTTPException(400, f"proposal is already '{proposal['status']}', not pending")

    result = {"targets_found": 0, "targets_deleted": 0, "errors": []}
    if proposal["action_type"] == "restart_pod":
        try:
            pods = _list_pods(proposal["namespace"])
            for pod in pods:
                if pod.get("metadata", {}).get("labels", {}).get("app") != proposal["app_label"]:
                    continue
                p_type, _ = _diagnose(pod)
                if p_type != proposal["problem_type"]:
                    continue
                result["targets_found"] += 1
                try:
                    _delete_pod(proposal["namespace"], pod["metadata"]["name"])
                    result["targets_deleted"] += 1
                    STATS["actions_executed"] += 1
                except requests.RequestException as e:
                    result["errors"].append(str(e))
        except requests.RequestException as e:
            result["errors"].append(str(e))

    proposal["status"] = "approved_and_executed"
    proposal["resolved_at"] = time.time()
    proposal["resolved_by"] = req.actor
    proposal["execution_result"] = result

    if proposal.get("sys_id"):
        outcome = (f"found {result['targets_found']} still-unhealthy pod(s), deleted {result['targets_deleted']}"
                   if result["targets_found"] else "no still-unhealthy pods found -- likely already self-resolved")
        servicenow_client.add_work_note(
            proposal["sys_id"],
            f"[Infra Monitor] Remediation APPROVED by {req.actor}. Action: {proposal['action_description']}\nResult: {outcome}."
            + (f"\nErrors: {result['errors']}" if result["errors"] else ""),
        )

    return proposal


@app.post("/api/proposals/{proposal_id}/reject")
def reject_proposal(proposal_id: str, req: ApprovalRequest):
    proposal = PROPOSALS.get(proposal_id)
    if not proposal:
        raise HTTPException(404, "proposal not found")
    if proposal["status"] != "pending":
        raise HTTPException(400, f"proposal is already '{proposal['status']}', not pending")

    proposal["status"] = "rejected"
    proposal["resolved_at"] = time.time()
    proposal["resolved_by"] = req.actor

    if proposal.get("sys_id"):
        servicenow_client.add_work_note(
            proposal["sys_id"],
            f"[Infra Monitor] Remediation REJECTED by {req.actor}."
            + (f" Reason: {req.reason}" if req.reason else "")
            + " No automated action was taken; needs manual handling.",
        )

    return proposal


@app.get("/api/dashboard")
def dashboard():
    return {
        "stats": STATS,
        "active_problems": len(CORRELATIONS),
        "servicenow_configured": servicenow_client.is_configured(),
        "servicenow_last_error": servicenow_client.LAST_ERROR,
        "monitored_namespaces": MONITORED_NAMESPACES,
    }


@app.get("/healthz")
def healthz():
    return {"status": "ok", **STATS}
