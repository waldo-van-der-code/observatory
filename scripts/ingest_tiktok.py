"""Ingest TikTok GDPR export (user_data_tiktok.json) into entertainment.db.

Sources ingested:
  Watch History   → interaction_type='watched', rating=2
  Like List       → interaction_type='liked',   rating=4
  Favorite Videos → interaction_type='favorited', rating=5

Searches, share history, and hashtags are intentionally ignored.

Idempotent: every row has a deterministic source_key (sha256 of the five-tuple
source_list|interaction_type|date|url|index), so re-runs insert zero new rows.
"""

import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from db import get_conn, init_db

RAW = Path(__file__).parent.parent / "data" / "raw"
SOURCE_FILE = RAW / "user_data_tiktok.json"

_VIDEO_ID_RE = re.compile(r"/video/(\d+)")

RATING_MAP = {"watched": 2, "liked": 4, "favorited": 5}

# (top_key, sub_key, list_key, date_field, url_field, interaction_type)
SOURCES = [
    ("Your Activity",       "Watch History",   "VideoList",         "Date", "Link", "watched"),
    ("Likes and Favorites", "Like List",       "ItemFavoriteList",  "date", "link", "liked"),
    ("Likes and Favorites", "Favorite Videos", "FavoriteVideoList", "Date", "Link", "favorited"),
]


def make_source_key(*parts: str) -> str:
    s = "|".join(str(p) for p in parts)
    return hashlib.sha256(s.encode()).hexdigest()


def extract_video_id(url: str) -> str | None:
    m = _VIDEO_ID_RE.search(url)
    return m.group(1) if m else None


def ingest(conn) -> None:
    totals: dict[str, dict[str, int]] = {}

    for top_key, sub_key, list_key, date_field, url_field, interaction_type in SOURCES:
        source_label = f"{top_key} / {sub_key}"
        items = (
            data.get(top_key, {}).get(sub_key, {}).get(list_key) or []
        )
        inserted = skipped = unparsed = 0

        for idx, item in enumerate(items):
            raw_url: str = item.get(url_field, "").strip()
            date: str = item.get(date_field, "").strip()
            video_id = extract_video_id(raw_url)

            sk = make_source_key(source_label, interaction_type, date, raw_url, idx)

            if video_id is None:
                conn.execute(
                    """INSERT OR IGNORE INTO tiktok_unparsed_urls
                           (source_key, raw_url, interaction_type, interaction_date,
                            source_list, source_index, reason)
                       VALUES (?,?,?,?,?,?,?)""",
                    (sk, raw_url, interaction_type, date, source_label, idx, "no_video_id"),
                )
                unparsed += 1
                continue

            # Upsert video stub (never overwrites enriched metadata)
            conn.execute(
                """INSERT INTO tiktok_videos (video_id, url)
                   VALUES (?,?)
                   ON CONFLICT(video_id) DO UPDATE SET url = excluded.url""",
                (video_id, raw_url),
            )

            # Idempotent interaction row
            cur = conn.execute(
                """INSERT OR IGNORE INTO tiktok_interactions
                       (source_key, video_id, raw_url, interaction_type, rating,
                        interaction_date, source_list, source_index)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (sk, video_id, raw_url, interaction_type, RATING_MAP[interaction_type],
                 date, source_label, idx),
            )
            if cur.rowcount > 0:
                inserted += 1
            else:
                skipped += 1

        conn.commit()
        totals[source_label] = {"inserted": inserted, "skipped": skipped, "unparsed": unparsed}

    # Mark liked/favorited videos as pending enrichment (only if not yet classified)
    conn.execute(
        """UPDATE tiktok_videos
           SET enrichment_status = 'pending'
           WHERE enrichment_status IS NULL
             AND video_id IN (
               SELECT DISTINCT video_id FROM tiktok_interactions
               WHERE interaction_type IN ('liked', 'favorited')
             )"""
    )
    conn.commit()

    # Summary
    print("\n=== TikTok ingest complete ===")
    for label, counts in totals.items():
        print(f"  {label}: {counts['inserted']} inserted, {counts['skipped']} skipped, {counts['unparsed']} unparsed")

    rows = conn.execute(
        "SELECT interaction_type, COUNT(*) c FROM tiktok_interactions GROUP BY interaction_type"
    ).fetchall()
    print("\nInteraction totals:")
    for r in rows:
        print(f"  {r[0]}: {r[1]}")

    unparsed_total = conn.execute("SELECT COUNT(*) FROM tiktok_unparsed_urls").fetchone()[0]
    pending = conn.execute(
        "SELECT COUNT(*) FROM tiktok_videos WHERE enrichment_status='pending'"
    ).fetchone()[0]
    print(f"\nUnparsed URLs: {unparsed_total}")
    print(f"Enrichment-eligible (pending): {pending}")


if __name__ == "__main__":
    if not SOURCE_FILE.exists():
        print(f"ERROR: {SOURCE_FILE} not found.")
        print("Copy it first: cp ~/Downloads/user_data_tiktok.json data/raw/user_data_tiktok.json")
        sys.exit(1)

    with open(SOURCE_FILE, encoding="utf-8") as f:
        data = json.load(f)

    conn = get_conn()
    init_db(conn)
    ingest(conn)
    conn.close()
