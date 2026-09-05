#!/usr/bin/env python3
"""
Collects incident-classification datasets from multiple sources into
local JSON files, ready to upload to S3 (see collect_and_upload.sh, which
runs this and then does the upload with the AWS CLI):

  1. servicenow-incidents.json  -- REAL incidents exported live from your
     ServiceNow instance via the same OAuth client-credentials app used
     everywhere else in this project.
  2. synthetic-incidents.json   -- the hand-authored synthetic set from
     generate_synthetic_dataset.py, covering categories real data doesn't
     have enough volume in yet.
  3. sample-tickets.json        -- the original 8-ticket demo set every
     agent already uses as its fallback (data/sample_tickets.json).

Uses only the Python standard library (urllib) -- no pip install needed,
deliberately, to avoid depending on a working local pip environment.

Usage:
  SERVICENOW_INSTANCE_URL=https://yourinstance.service-now.com \\
  SERVICENOW_CLIENT_ID=... SERVICENOW_CLIENT_SECRET=... \\
  python collect_datasets.py [output_dir]
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

INSTANCE_URL = os.environ.get("SERVICENOW_INSTANCE_URL", "").rstrip("/")
CLIENT_ID = os.environ.get("SERVICENOW_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("SERVICENOW_CLIENT_SECRET", "")
OUTPUT_DIR = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "collected"


def _post_form(url: str, data: dict) -> dict:
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def _get_json(url: str, token: str) -> dict:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read())


def get_token() -> str:
    body = _post_form(f"{INSTANCE_URL}/oauth_token.do", {
        "grant_type": "client_credentials",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    })
    return body["access_token"]


def collect_servicenow_incidents(limit: int = 200) -> list[dict]:
    token = get_token()
    params = urllib.parse.urlencode({
        "sysparm_limit": limit,
        "sysparm_order_by": "-sys_created_on",
        "sysparm_fields": "number,short_description,description,category,subcategory,priority,state,assignment_group,close_notes,sys_created_on",
    })
    data = _get_json(f"{INSTANCE_URL}/api/now/table/incident?{params}", token)
    records = []
    for r in data.get("result", []):
        records.append({
            "id": r.get("number"),
            "source": "servicenow-live",
            "short_description": r.get("short_description", ""),
            "description": r.get("description", ""),
            "category": r.get("category", "") or "Unclassified",
            "subcategory": r.get("subcategory", ""),
            "priority": r.get("priority", ""),
            "assignment_group": r.get("assignment_group", {}).get("value", "") if isinstance(r.get("assignment_group"), dict) else "",
            "resolution": r.get("close_notes", ""),
            "created_at": r.get("sys_created_on", ""),
        })
    return records


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    script_dir = Path(__file__).parent

    if CLIENT_ID and CLIENT_SECRET and INSTANCE_URL:
        print(f"Collecting live incidents from {INSTANCE_URL} ...")
        try:
            live = collect_servicenow_incidents()
            (OUTPUT_DIR / "servicenow-incidents.json").write_text(json.dumps(live, indent=2))
            print(f"  -> {len(live)} real incidents written to servicenow-incidents.json")
        except (urllib.error.URLError, urllib.error.HTTPError, KeyError) as e:
            print(f"  !! ServiceNow collection failed: {e}")
    else:
        print("SERVICENOW_INSTANCE_URL/CLIENT_ID/CLIENT_SECRET not set -- skipping live collection.")

    synthetic_src = script_dir / "synthetic_incidents.json"
    if synthetic_src.exists():
        (OUTPUT_DIR / "synthetic-incidents.json").write_text(synthetic_src.read_text())
        count = len(json.loads(synthetic_src.read_text()))
        print(f"  -> {count} synthetic incidents copied to synthetic-incidents.json")

    sample_src = script_dir.parent / "data" / "sample_tickets.json"
    if sample_src.exists():
        (OUTPUT_DIR / "sample-tickets.json").write_text(sample_src.read_text())
        count = len(json.loads(sample_src.read_text()))
        print(f"  -> {count} original sample tickets copied to sample-tickets.json")

    print(f"\nAll collected files are in: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
