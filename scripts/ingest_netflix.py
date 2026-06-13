#!/usr/bin/env python3
"""Ingest Netflix ViewingActivity.csv + Ratings.csv into entertainment.db."""

import csv
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from db import get_conn, init_db

RAW = Path(__file__).parent.parent / "data" / "raw"
VIEWING_CSV = RAW / "netflix_viewing.csv"
RATINGS_CSV = RAW / "netflix_ratings.csv"

PROFILE = "wally"
MIN_DURATION_S = 300  # skip watches shorter than 5 min (trailers/clips)

# Title: Season/Part/etc N: Episode → standard Netflix TV format
_TV_SEASON = re.compile(
    r"^(.+?):\s*(?:Season|Part|Book|Volume|Series|Collection|Limited Series|Mini[ -]Series)\s*\d*:",
    re.IGNORECASE,
)
# Title: Arc/anything: Episode N (Episode M) → anime / non-standard arcs
_TV_EPISODE = re.compile(r"^(.+?):.+?\(Episode\s+[\d.]+\)$", re.IGNORECASE)


def parse_duration(s: str) -> int:
    parts = s.split(":")
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    return 0


def extract_show_or_movie(title: str) -> tuple[str, str]:
    """Return (clean_title, media_type)."""
    m = _TV_SEASON.match(title)
    if m:
        return m.group(1).strip(), "tv_show"
    m = _TV_EPISODE.match(title)
    if m:
        return m.group(1).strip(), "tv_show"
    return title.strip(), "film"


def make_id(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return f"netflix:{slug}"


def ingest_viewing(conn) -> tuple[int, int]:
    if not VIEWING_CSV.exists():
        print("netflix_viewing.csv not found — skipping")
        return 0, 0

    # Collect most recent watch date + media_type per title (aggregated at show level)
    most_recent: dict[str, str] = {}
    media_types: dict[str, str] = {}

    with open(VIEWING_CSV, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if row["Profile Name"] != PROFILE:
                continue
            if row["Supplemental Video Type"]:
                continue
            dur = parse_duration(row["Duration"])
            if dur < MIN_DURATION_S:
                continue

            clean_title, media_type = extract_show_or_movie(row["Title"])
            date = row["Start Time"][:10]

            if clean_title not in most_recent or date > most_recent[clean_title]:
                most_recent[clean_title] = date
            media_types[clean_title] = media_type

    inserted = updated = 0
    for title, last_date in most_recent.items():
        media_type = media_types[title]
        item_id = make_id(title)

        existing = conn.execute("SELECT id FROM media_items WHERE id=?", (item_id,)).fetchone()
        if existing:
            updated += 1
        else:
            conn.execute(
                "INSERT INTO media_items (id, media_type, title, source, source_id) VALUES (?,?,?,?,?)",
                (item_id, media_type, title, "netflix", item_id),
            )
            inserted += 1

        # Upsert a single "completed" interaction (most recent watch)
        conn.execute(
            "DELETE FROM user_interactions WHERE media_id=? AND source='netflix' AND interaction='completed'",
            (item_id,),
        )
        conn.execute(
            "INSERT INTO user_interactions (media_id, interaction, date_completed, source) VALUES (?,?,?,?)",
            (item_id, "completed", last_date, "netflix"),
        )

    conn.commit()
    return inserted, updated


def ingest_ratings(conn) -> int:
    if not RATINGS_CSV.exists():
        return 0

    total = 0
    with open(RATINGS_CSV, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if row["Profile Name"] != PROFILE:
                continue
            thumbs = row.get("Thumbs Value", "").strip()
            if thumbs not in ("1", "3"):
                continue

            # Ratings are at show level (no episode info in title)
            title = row["Title Name"].strip()
            item_id = make_id(title)

            # Ensure media_item exists (might not if very short/supplemental)
            existing = conn.execute("SELECT id FROM media_items WHERE id=?", (item_id,)).fetchone()
            if not existing:
                _, media_type = extract_show_or_movie(title)
                conn.execute(
                    "INSERT INTO media_items (id, media_type, title, source, source_id) VALUES (?,?,?,?,?)",
                    (item_id, media_type, title, "netflix", item_id),
                )

            rating = 4.0 if thumbs == "3" else 1.5  # thumbs up → 4★, thumbs down → 1.5★
            date = row.get("Event Utc Ts", "")[:10] or None

            conn.execute(
                "DELETE FROM user_interactions WHERE media_id=? AND source='netflix' AND interaction='rated'",
                (item_id,),
            )
            conn.execute(
                "INSERT INTO user_interactions (media_id, interaction, rating, date_completed, source) VALUES (?,?,?,?,?)",
                (item_id, "rated", rating, date, "netflix"),
            )
            total += 1

    conn.commit()
    return total


def main():
    conn = get_conn()
    init_db(conn)

    ins, upd = ingest_viewing(conn)
    print(f"Netflix viewing: {ins} inserted, {upd} updated")

    rated = ingest_ratings(conn)
    print(f"Netflix ratings: {rated} thumb ratings ingested")

    shows = conn.execute(
        "SELECT count(*) n FROM media_items WHERE source='netflix' AND media_type='tv_show'"
    ).fetchone()["n"]
    films = conn.execute(
        "SELECT count(*) n FROM media_items WHERE source='netflix' AND media_type='film'"
    ).fetchone()["n"]
    print(f"Totals: {shows} shows, {films} films/specials")


if __name__ == "__main__":
    main()
