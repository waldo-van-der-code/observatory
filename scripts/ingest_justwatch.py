#!/usr/bin/env python3
"""Ingest JustWatch seen/liked CSVs into entertainment.db."""

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import app_ratings
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


def _find_existing(conn, title: str, year: str | None, mtype: str) -> str | None:
    """Find the work this JustWatch row is about, or None to create a new item.

    Only titles in the same type group qualify; a film never attaches to a show.
    Prefer an IMDb row, then the lowest id, for a stable result.
    """
    year_i = int(year) if year and str(year).isdigit() else None
    placeholders = ("film", "movie") if mtype == "film" else ("tv_show",)
    cands = sorted(conn.execute(
        "SELECT id, year, source FROM media_items WHERE lower(title)=lower(?) "
        f"AND media_type IN ({','.join('?' * len(placeholders))})",
        (title, *placeholders),
    ).fetchall(), key=lambda r: (r["source"] != "imdb", r["id"]))
    if not cands:
        return None
    if year_i is not None:
        for c in cands:
            if c["year"] == year_i:
                return c["id"]
        off_by_one = [c for c in cands if c["year"] is not None and abs(c["year"] - year_i) == 1]
        if len(off_by_one) == 1:
            return off_by_one[0]["id"]
        # A yearless row is the same work only when nothing says otherwise.
        if not any(c["year"] is not None for c in cands):
            return cands[0]["id"]
        return None
    if len(cands) == 1:
        return cands[0]["id"]
    return None


def ingest_seen(conn) -> int:
    if not SEEN_CSV.exists():
        print("justwatch_seen.csv not found — skipping")
        return 0
    # Rebuild: any earlier justwatch_seen row (possibly attached to the wrong work) goes away.
    conn.execute("DELETE FROM user_interactions WHERE source='justwatch_seen'")
    count = 0
    with open(SEEN_CSV, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            title = row["title"].strip()
            orig  = row.get("original_title", title).strip() or title
            year  = row.get("year", "").strip()
            mtype = _media_type(row.get("type", "film"))

            item_id = _find_existing(conn, orig, year, mtype) or _find_existing(conn, title, year, mtype)
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
    # Rebuild: any earlier justwatch_liked row (possibly attached to the wrong work) goes away.
    # A row re-rated in the app has source 'oracle' and survives.
    conn.execute("DELETE FROM user_interactions WHERE source='justwatch_liked'")
    count = 0
    with open(LIKED_CSV, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            title = row["title"].strip()
            orig  = row.get("original_title", title).strip() or title
            year  = row.get("year", "").strip()
            mtype = _media_type(row.get("type", "film"))

            item_id = _find_existing(conn, orig, year, mtype) or _find_existing(conn, title, year, mtype)
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
    app_ratings.reapply(conn)
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
