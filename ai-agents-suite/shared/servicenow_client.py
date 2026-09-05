"""
Shared ServiceNow Table API client, used by every agent service.

SAFE BY DESIGN: this never touches a username/password. It only supports
OAuth 2.0 client-credentials auth (the standard way to let a backend
service talk to ServiceNow without impersonating a real user login).

Until SERVICENOW_INSTANCE_URL / SERVICENOW_CLIENT_ID / SERVICENOW_CLIENT_SECRET
are set (as a Kubernetes Secret -- never hardcoded in any file), every
method below returns None and callers fall back to the local sample
dataset in data/sample_tickets.json. That's why every agent works fully
today, and will start using live data the moment those three env vars are
set -- no code changes needed.

To set this up for real:
  1. In ServiceNow: System OAuth > Application Registry > New > "Create an
     OAuth API endpoint for external clients". Note the Client ID/Secret.
  2. kubectl create secret generic servicenow-oauth -n ai-agents \\
       --from-literal=instance-url=https://yourinstance.service-now.com \\
       --from-literal=client-id=... --from-literal=client-secret=...
  3. Reference that secret's keys as env vars in each deployment (already
     wired up in k8s/*-deployment.yaml, currently pointing at a secret
     that doesn't exist yet -- create it and the pods pick it up on next
     restart).
"""
import os
import time
import requests

INSTANCE_URL = os.environ.get("SERVICENOW_INSTANCE_URL", "").rstrip("/")
CLIENT_ID = os.environ.get("SERVICENOW_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("SERVICENOW_CLIENT_SECRET", "")

_token_cache = {"token": None, "expires_at": 0}
LAST_ERROR = None  # set on any live-call failure, for visibility (e.g. exposed via /healthz)


def is_configured() -> bool:
    """True if credentials are PRESENT. Does not mean the connection is
    actually working -- e.g. a wrong secret or missing ServiceNow-side
    config still leaves this True. Every read method below treats a
    live-call failure exactly like "not configured" (falls back to
    sample data) rather than raising, precisely because "configured" and
    "working" are different things -- conflating them once took down an
    entire poll loop that should have degraded gracefully instead."""
    return bool(INSTANCE_URL and CLIENT_ID and CLIENT_SECRET)


def _get_token():
    if not is_configured():
        return None
    if _token_cache["token"] and _token_cache["expires_at"] > time.time():
        return _token_cache["token"]
    resp = requests.post(
        f"{INSTANCE_URL}/oauth_token.do",
        data={
            "grant_type": "client_credentials",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
        },
        timeout=10,
    )
    resp.raise_for_status()
    body = resp.json()
    _token_cache["token"] = body["access_token"]
    _token_cache["expires_at"] = time.time() + int(body.get("expires_in", 1800)) - 60
    return _token_cache["token"]


def get_incident(sys_id_or_number: str):
    """Returns a live incident dict from ServiceNow, or None if not
    configured, not found, OR the live call fails for any reason --
    caller always falls back to sample data rather than crashing."""
    global LAST_ERROR
    if not is_configured():
        return None
    try:
        token = _get_token()
        resp = requests.get(
            f"{INSTANCE_URL}/api/now/table/incident",
            headers={"Authorization": f"Bearer {token}"},
            params={"sysparm_query": f"number={sys_id_or_number}", "sysparm_limit": 1},
            timeout=10,
        )
        resp.raise_for_status()
        results = resp.json().get("result", [])
        LAST_ERROR = None
        return results[0] if results else None
    except requests.RequestException as e:
        LAST_ERROR = str(e)
        return None


def list_incidents(limit: int = 20):
    global LAST_ERROR
    if not is_configured():
        return None
    try:
        token = _get_token()
        resp = requests.get(
            f"{INSTANCE_URL}/api/now/table/incident",
            headers={"Authorization": f"Bearer {token}"},
            params={"sysparm_limit": limit, "sysparm_order_by": "-sys_created_on"},
            timeout=10,
        )
        resp.raise_for_status()
        LAST_ERROR = None
        return resp.json().get("result", [])
    except requests.RequestException as e:
        LAST_ERROR = str(e)
        return None


def list_open_incidents(limit: int = 20):
    """Returns open/new incidents not yet worked -- what a watcher polls
    for. Returns None if not configured OR the live call fails for any
    reason (caller falls back to sample data)."""
    global LAST_ERROR
    if not is_configured():
        return None
    try:
        token = _get_token()
        resp = requests.get(
            f"{INSTANCE_URL}/api/now/table/incident",
            headers={"Authorization": f"Bearer {token}"},
            params={
                "sysparm_query": "state=1^ORstate=2",  # 1=New, 2=In Progress (not yet Resolved/Closed)
                "sysparm_limit": limit,
                "sysparm_order_by": "sys_created_on",
            },
            timeout=10,
        )
        resp.raise_for_status()
        LAST_ERROR = None
        return resp.json().get("result", [])
    except requests.RequestException as e:
        LAST_ERROR = str(e)
        return None


def create_incident(short_description: str, description: str = ""):
    """Creates a brand-new real incident in ServiceNow (used for
    infra-detected breaks, which have no existing ServiceNow ticket to
    look up). Returns the created incident's {number, sys_id} dict, or
    None if not configured or the call fails."""
    global LAST_ERROR
    if not is_configured():
        return None
    try:
        token = _get_token()
        resp = requests.post(
            f"{INSTANCE_URL}/api/now/table/incident",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={
                "short_description": short_description,
                "description": description or short_description,
                "category": "Software",
                "contact_type": "integration",
            },
            timeout=10,
        )
        resp.raise_for_status()
        result = resp.json().get("result", {})
        LAST_ERROR = None
        return {"number": result.get("number"), "sys_id": result.get("sys_id")}
    except requests.RequestException as e:
        LAST_ERROR = str(e)
        return None


def add_work_note(sys_id: str, note: str) -> bool:
    """Writes a summary/recommendation back onto a real incident as a work
    note (visible to agents, not the end user). Returns False if
    ServiceNow isn't configured OR the write fails for any reason -- this
    is the one write operation in the whole client, and failure here must
    never propagate as an exception (a work-note write failing shouldn't
    take down whatever loop was reporting the incident in the first
    place)."""
    global LAST_ERROR
    if not is_configured():
        return False
    try:
        token = _get_token()
        resp = requests.patch(
            f"{INSTANCE_URL}/api/now/table/incident/{sys_id}",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"work_notes": note},
            timeout=10,
        )
        resp.raise_for_status()
        LAST_ERROR = None
        return True
    except requests.RequestException as e:
        LAST_ERROR = str(e)
        return False
