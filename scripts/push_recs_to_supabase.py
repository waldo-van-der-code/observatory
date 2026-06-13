#!/usr/bin/env python3
"""Push recommendations from local SQLite DB to Supabase recommendations table."""

import json
import re
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from db import get_conn

_cfg = Path("~/.config/observatory/config.env").expanduser().read_text()
_mu = re.search(r"SUPABASE_URL=(.+)", _cfg)
_mk = re.search(r"SUPABASE_SERVICE_ROLE_KEY=(.+)", _cfg)
SUPABASE_URL = _mu.group(1).strip() if _mu else ""
SERVICE_KEY = _mk.group(1).strip() if _mk else ""

HEADERS = {
    "apikey": SERVICE_KEY,
    "Authorization": f"Bearer {SERVICE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "resolution=merge-duplicates",
}

def push_recs():
    conn = get_conn()
    batch_id = "2026-06-03"

    # Get all active recs from local DB
    rows = conn.execute(
        "SELECT * FROM recommendations WHERE status='pending' ORDER BY confidence DESC"
    ).fetchall()

    print(f"Found {len(rows)} local recommendations")

    # Build payload
    payload = []
    for r in rows:
        payload.append({
            "media_type": r["media_type"],
            "title": r["title"],
            "author_director": r["author_or_director"],
            "year": None,
            "reason": r["reason"],
            "friction": r["potential_issue"],
            "confidence": r["confidence"],
            "status": "active",
            "batch_id": batch_id,
        })

    if not payload:
        print("No recommendations to push")
        return

    # Upsert in one call
    r = requests.post(
        f"{SUPABASE_URL}/rest/v1/recommendations",
        headers=HEADERS,
        json=payload,
    )
    if r.status_code in (200, 201):
        print(f"✓ Pushed {len(payload)} recommendations to Supabase")
    else:
        print(f"✗ Failed: {r.status_code} {r.text[:200]}")

    # Show count in Supabase
    cr = requests.get(
        f"{SUPABASE_URL}/rest/v1/recommendations?status=eq.active&select=id",
        headers={**HEADERS, "Prefer": "count=exact"},
    )
    total = cr.headers.get("content-range", "?/?").split("/")[-1]
    print(f"Total active recs in Supabase: {total}")

if __name__ == "__main__":
    push_recs()
