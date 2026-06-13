#!/usr/bin/env python3
"""Load synthetic fixture data into entertainment.db for developer testing.

This lets you see the Brain map and dashboard populated without any personal
GDPR exports or API keys.

Usage:
    python3 scripts/load_fixtures.py         # load 32 synthetic records
    python3 scripts/load_fixtures.py --reset  # drop DB first, then load clean

After running:
    python3 scripts/build_brain.py
    uvicorn server:app --reload
    # → http://localhost:8000/brain.html
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from db import get_conn, init_db

ROOT = Path(__file__).parent.parent
FIXTURE_JSON  = ROOT / "data" / "fixtures" / "fixture_data.json"
FIXTURE_MAP   = ROOT / "data" / "fixtures" / "fixture_map_data.json"
DB_PATH       = ROOT / "data" / "processed" / "entertainment.db"
MAP_DATA_PATH = ROOT / "data" / "processed" / "map_data.json"


def _ensure_spotify_table(conn) -> None:
    """build_brain.py queries spotify_plays — create it empty if absent."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS spotify_plays (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            ended_at  TEXT,
            artist    TEXT,
            track     TEXT,
            ms_played INTEGER,
            album     TEXT
        )
    """)
    conn.commit()


def load(reset: bool = False) -> None:
    if reset and DB_PATH.exists():
        DB_PATH.unlink()
        print("Dropped existing DB.")

    data = json.loads(FIXTURE_JSON.read_text())

    conn = get_conn()
    init_db(conn)
    _ensure_spotify_table(conn)

    inserted_items = 0
    skipped_items  = 0
    for item in data["media_items"]:
        existing = conn.execute(
            "SELECT id FROM media_items WHERE id = ?", (item["id"],)
        ).fetchone()
        if existing:
            skipped_items += 1
            continue

        conn.execute(
            """INSERT INTO media_items
               (id, media_type, title, author, director, year, genres, source, source_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                item["id"],
                item["media_type"],
                item["title"],
                item.get("author"),
                item.get("director"),
                item.get("year"),
                json.dumps(item.get("genres", [])),
                item["source"],
                item["source_id"],
            ),
        )
        inserted_items += 1

    inserted_interactions = 0
    for ix in data["interactions"]:
        existing = conn.execute(
            "SELECT id FROM user_interactions WHERE media_id = ? AND interaction = ?",
            (ix["media_id"], ix["interaction"]),
        ).fetchone()
        if existing:
            continue
        conn.execute(
            """INSERT INTO user_interactions
               (media_id, interaction, rating, shelf, date_completed, source)
               VALUES (?, ?, ?, ?, ?, 'fixture')""",
            (ix["media_id"], ix["interaction"], ix["rating"],
             ix.get("shelf"), ix.get("date_completed")),
        )
        inserted_interactions += 1

    conn.commit()
    conn.close()

    MAP_DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(FIXTURE_MAP, MAP_DATA_PATH)

    total_items = inserted_items + skipped_items
    print(f"Loaded {inserted_items} items ({skipped_items} already present, {total_items} total)")
    print(f"Loaded {inserted_interactions} interactions")
    print(f"Copied fixture map data → {MAP_DATA_PATH}")
    print()
    print("Next steps:")
    print("  python3 scripts/build_brain.py")
    print("  uvicorn server:app --reload")
    print("  → http://localhost:8000/brain.html")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--reset", action="store_true", help="Drop the DB before loading (fresh start)")
    args = parser.parse_args()
    load(reset=args.reset)
