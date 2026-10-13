#!/usr/bin/env python3
"""Daily Audible sync: fetch finished audiobooks via the unofficial `audible` API,
merge with titles already in the DB, write data/raw/audible_finished.csv, run ingest.

    python3 scripts/sync_audible.py [--dry-run]

Needs credentials from scripts/audible_login.py. Exit codes: 0 ok, 2 auth/API failure
(cron wrapper alerts on non-zero).
"""
import csv
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

CRED = Path(os.environ.get("AUDIBLE_CREDENTIALS", Path.home() / ".config" / "audible" / "credentials.json"))
CSV_PATH = Path(__file__).parent.parent / "data" / "raw" / "audible_finished.csv"
GROUPS = "product_desc,contributors,is_finished,listening_status,percent_complete"


def is_finished(item: dict) -> bool:
    if item.get("is_finished"):
        return True
    ls = item.get("listening_status") or {}
    return bool(ls.get("is_finished"))


def to_row(item: dict) -> dict:
    authors = ", ".join(a.get("name", "") for a in item.get("authors") or [] if a.get("name"))
    return {"title": (item.get("title") or "").strip(), "author": authors}


def fetch_finished(client) -> list[dict]:
    rows, page = [], 1
    while True:
        resp = client.get("1.0/library", num_results=200, page=page, response_groups=GROUPS)
        items = resp.get("items", [])
        rows += [to_row(i) for i in items if is_finished(i)]
        if len(items) < 200:
            return [r for r in rows if r["title"]]
        page += 1


def existing_db_rows() -> list[dict]:
    """Audible rows already in the DB; ingest_audible.main() wipes them, so keep them."""
    from db import get_conn
    conn = get_conn()
    try:
        return [{"title": r["title"], "author": r["author"] or ""} for r in conn.execute(
            "SELECT DISTINCT m.title, m.author FROM media_items m "
            "LEFT JOIN user_interactions u ON u.media_id=m.id "
            "WHERE m.source='audible' OR u.source='audible'").fetchall()]
    finally:
        conn.close()


def merge(*groups: list[dict]) -> list[dict]:
    seen, out = set(), []
    for g in groups:
        for r in g:
            k = r["title"].strip().lower()
            if k and k not in seen:
                seen.add(k)
                out.append(r)
    return out


def main() -> int:
    dry = "--dry-run" in sys.argv
    try:
        import audible
        auth = audible.Authenticator.from_file(CRED)
        with audible.Client(auth=auth) as client:
            fetched = fetch_finished(client)
    except Exception as e:
        print(f"Audible sync FAILED (re-run audible_login.py if auth expired): {e!r}", file=sys.stderr)
        return 2

    prev = []
    if CSV_PATH.exists():
        with open(CSV_PATH, newline="", encoding="utf-8-sig") as f:
            prev = list(csv.DictReader(f))
    merged = merge(fetched, prev, existing_db_rows())
    print(f"Audible: {len(fetched)} finished via API, {len(merged)} after merge")
    if dry:
        known = {r["title"].lower() for r in prev}
        for r in fetched:
            if r["title"].lower() not in known:
                print(f"  new: {r['title']} — {r['author']}")
        return 0

    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["title", "author"])
        w.writeheader()
        w.writerows(merged)
    import ingest_audible
    ingest_audible.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
