#!/usr/bin/env python3
"""Ingest Netflix ViewingActivity.csv + Ratings.csv into entertainment.db."""

import csv
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import app_ratings
from db import get_conn, init_db

RAW = Path(__file__).parent.parent / "data" / "raw"
VIEWING_CSV = RAW / "netflix_viewing.csv"
RATINGS_CSV = RAW / "netflix_ratings.csv"

PROFILE = "wally"
MIN_DURATION_S = 300  # skip watches shorter than 5 min (trailers/clips)
# Netflix lists these two works under one name, told apart only by capitals: title → (id, year)
SAME_NAME_WORKS = {"ONE PIECE": ("netflix:one-piece", 2023), "One Piece": ("netflix:one-piece-anime", 1999)}

# Title: Season/Part/etc N: Episode → standard Netflix TV format; newer exports can drop the word ("Title:  1: Episode")
_TV_SEASON = re.compile(
    r"^(.+?):\s*(?:(?:Season|Part|Book|Volume|Series|Collection|Limited Series|Mini[ -]Series)\s*\d*|\d+):",
    re.IGNORECASE,
)
# Title: Title 2: Episode → the season is named after the show, and the title itself may hold a colon
_TV_REPEATED = re.compile(r"^(.+?):\s*\1\b[^:]*:")
# Title: Arc/anything: Episode N (Episode M) → anime / non-standard arcs
_TV_EPISODE = re.compile(r"^(.+?):.+?\(Episode\s+[\d.]+\)$", re.IGNORECASE)


def parse_duration(s: str) -> int:
    parts = s.split(":")
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    return 0


def extract_show_or_movie(title: str) -> tuple[str, str]:
    """Return (clean_title, media_type)."""
    m = _TV_SEASON.match(title) or _TV_REPEATED.match(title)
    if m:
        return m.group(1).strip(), "tv_show"
    m = _TV_EPISODE.match(title)
    if m:
        return m.group(1).strip(), "tv_show"
    return title.strip(), "film"


def make_id(title: str) -> str:
    if title in SAME_NAME_WORKS:
        return SAME_NAME_WORKS[title][0]
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
        if title in SAME_NAME_WORKS:
            conn.execute("UPDATE media_items SET year=? WHERE id=? AND year IS NULL", (SAME_NAME_WORKS[title][1], item_id))

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


def _titles_played_as_shows() -> set[str]:
    """Rating rows have a bare title, so the viewing file (even short plays) has to say which ones are shows."""
    if not VIEWING_CSV.exists():
        return set()
    with open(VIEWING_CSV, newline="", encoding="utf-8-sig") as f:
        parsed = (extract_show_or_movie(r["Title"]) for r in csv.DictReader(f) if r["Profile Name"] == PROFILE)
        return {title for title, media_type in parsed if media_type == "tv_show"}


def ingest_ratings(conn) -> int:
    if not RATINGS_CSV.exists():
        return 0

    played_as_shows = _titles_played_as_shows()
    total = 0
    with open(RATINGS_CSV, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if row["Profile Name"] != PROFILE:
                continue
            thumbs = row.get("Thumbs Value", "").strip()
            if thumbs not in ("1", "2", "3"):
                continue

            # Ratings are at show level (no episode info in title)
            title = row["Title Name"].strip()
            item_id = make_id(title)

            # Ensure media_item exists (might not if very short/supplemental)
            existing = conn.execute("SELECT id FROM media_items WHERE id=?", (item_id,)).fetchone()
            if not existing:
                _, media_type = extract_show_or_movie(title)
                if title in played_as_shows or conn.execute(
                    "SELECT 1 FROM media_items WHERE lower(title)=lower(?) AND media_type='tv_show'", (title,)
                ).fetchone():
                    media_type = "tv_show"
                conn.execute(
                    "INSERT INTO media_items (id, media_type, title, source, source_id) VALUES (?,?,?,?,?)",
                    (item_id, media_type, title, "netflix", item_id),
                )

            rating = 1.5 if thumbs == "1" else 4.0  # thumbs down → 1.5★, thumbs up (2) or double up (3) → 4★
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

    app_ratings.reapply(conn)
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
