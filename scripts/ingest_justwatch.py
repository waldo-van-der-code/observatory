#!/Users/waldo.vanderhaeghen/Library/Scripts/watcher-env/bin/python3
"""Ingest JustWatch seen/liked CSVs into entertainment.db."""

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from db import get_conn, init_db

RAW = Path(__file__).parent.parent / "data" / "raw"
SEEN_CSV  = RAW / "justwatch_seen.csv"
LIKED_CSV = RAW / "justwatch_liked.csv"


def _media_type(type_str: str) -> str:
    t = type_str.strip().lower()
    if "show" in t or "series" in t or t == "tv":
        return "tv_show"
    return "film"


def _make_id(title: str, year: str) -> str:
    slug = title.lower().replace(" ", "_")[:40]
    return f"jw:{slug}:{year}"


def _find_existing(conn, title: str, year: str | None) -> str | None:
    """Check if a film with this title+year is already in the DB from IMDb."""
    year_i = int(year) if year and year.isdigit() else None
    if year_i:
        row = conn.execute(
            "SELECT id FROM media_items WHERE lower(title)=lower(?) AND year=?",
            (title, year_i),
        ).fetchone()
        if row:
            return row["id"]
    # fallback: title match only
    row = conn.execute(
        "SELECT id FROM media_items WHERE lower(title)=lower(?)", (title,)
    ).fetchone()
    return row["id"] if row else None


def ingest_seen(conn) -> int:
    if not SEEN_CSV.exists():
        print("justwatch_seen.csv not found — skipping")
        return 0
    count = 0
    with open(SEEN_CSV, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            title = row["title"].strip()
            orig  = row.get("original_title", title).strip() or title
            year  = row.get("year", "").strip()
            mtype = _media_type(row.get("type", "film"))

            item_id = _find_existing(conn, orig, year) or _find_existing(conn, title, year)
            if not item_id:
                item_id = _make_id(orig, year)
                year_i = int(year) if year.isdigit() else None
                conn.execute(
                    "INSERT OR IGNORE INTO media_items "
                    "(id, media_type, title, year, source, source_id) VALUES (?,?,?,?,?,?)",
                    (item_id, mtype, orig, year_i, "justwatch", item_id),
                )

            existing = conn.execute(
                "SELECT id FROM user_interactions WHERE media_id=? AND source='justwatch_seen'",
                (item_id,),
            ).fetchone()
            if not existing:
                conn.execute(
                    "INSERT INTO user_interactions (media_id, interaction, shelf, source) "
                    "VALUES (?,?,?,?)",
                    (item_id, "completed", "seen", "justwatch_seen"),
                )
                count += 1
    conn.commit()
    return count


def ingest_liked(conn) -> int:
    if not LIKED_CSV.exists():
        print("justwatch_liked.csv not found — skipping")
        return 0
    count = 0
    with open(LIKED_CSV, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            title = row["title"].strip()
            orig  = row.get("original_title", title).strip() or title
            year  = row.get("year", "").strip()
            mtype = _media_type(row.get("type", "film"))

            item_id = _find_existing(conn, orig, year) or _find_existing(conn, title, year)
            if not item_id:
                item_id = _make_id(orig, year)
                year_i = int(year) if year.isdigit() else None
                conn.execute(
                    "INSERT OR IGNORE INTO media_items "
                    "(id, media_type, title, year, source, source_id) VALUES (?,?,?,?,?,?)",
                    (item_id, mtype, orig, year_i, "justwatch", item_id),
                )

            existing = conn.execute(
                "SELECT id FROM user_interactions WHERE media_id=? AND source='justwatch_liked'",
                (item_id,),
            ).fetchone()
            if not existing:
                # Liked = strong positive signal; treat as 4.5/5
                conn.execute(
                    "INSERT INTO user_interactions (media_id, interaction, rating, shelf, source) "
                    "VALUES (?,?,?,?,?)",
                    (item_id, "rated", 4.5, "liked", "justwatch_liked"),
                )
                count += 1
    conn.commit()
    return count


def main():
    conn = get_conn()
    init_db(conn)
    seen  = ingest_seen(conn)
    liked = ingest_liked(conn)
    print(f"JustWatch: {seen} seen, {liked} liked ingested")


if __name__ == "__main__":
    main()
