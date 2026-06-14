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
               (id, media_type, title, author, director, year, genres, series_name, series_pos, source, source_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                item["id"],
                item["media_type"],
                item["title"],
                item.get("author"),
                item.get("director"),
                item.get("year"),
                json.dumps(item.get("genres", [])),
                item.get("series_name"),
                item.get("series_pos"),
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
               VALUES (?, ?, ?, ?, ?, ?)""",
            (ix["media_id"], ix["interaction"], ix["rating"],
             ix.get("shelf"), ix.get("date_completed"),
             ix.get("source", "fixture")),
        )
        inserted_interactions += 1

    inserted_plays = 0
    for play in data.get("spotify_plays", []):
        conn.execute(
            "INSERT INTO spotify_plays (ended_at, artist, track, ms_played, album) VALUES (?,?,?,?,?)",
            (play.get("ended_at"), play.get("artist"), play.get("track"),
             play.get("ms_played"), play.get("album")),
        )
        inserted_plays += 1

    tp = data.get("taste_profile")
    if tp:
        existing = conn.execute("SELECT id FROM taste_profile ORDER BY id DESC LIMIT 1").fetchone()
        if not existing:
            conn.execute(
                "INSERT INTO taste_profile "
                "(generated_at, genre_fingerprint, film_genre_fingerprint, top_themes, "
                "rating_calibration, taste_clusters, dislikes_pattern, top_authors, top_directors, raw_response) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    tp.get("generated_at"),
                    json.dumps(tp.get("genre_fingerprint", {})),
                    json.dumps(tp.get("film_genre_fingerprint", {})),
                    json.dumps(tp.get("top_themes", [])),
                    json.dumps(tp.get("rating_calibration", {})),
                    json.dumps(tp.get("taste_clusters", [])),
                    json.dumps(tp.get("dislikes_pattern", [])),
                    json.dumps(tp.get("top_authors", [])),
                    json.dumps(tp.get("top_directors", [])),
                    json.dumps(tp.get("raw_response", {})),
                ),
            )
            print("Loaded taste_profile")

    # ── TikTok ────────────────────────────────────────────────────────────────
    inserted_tiktok_vids = 0
    for v in data.get("tiktok_videos", []):
        if conn.execute("SELECT 1 FROM tiktok_videos WHERE video_id=?", (v["video_id"],)).fetchone():
            continue
        conn.execute(
            "INSERT INTO tiktok_videos (video_id, url, title, description, hashtags, categories, "
            "enrichment_status, enrichment_attempts) VALUES (?,?,?,?,?,?,?,?)",
            (v["video_id"], v["url"], v.get("title"), v.get("description"),
             v.get("hashtags"), v.get("categories"),
             v.get("enrichment_status"), v.get("enrichment_attempts", 0)),
        )
        inserted_tiktok_vids += 1

    inserted_tiktok_ints = 0
    for t in data.get("tiktok_interactions", []):
        if conn.execute("SELECT 1 FROM tiktok_interactions WHERE source_key=?", (t["source_key"],)).fetchone():
            continue
        conn.execute(
            "INSERT INTO tiktok_interactions (source_key, video_id, raw_url, interaction_type, "
            "rating, interaction_date, source_list, source_index) VALUES (?,?,?,?,?,?,?,?)",
            (t["source_key"], t["video_id"], t["raw_url"], t["interaction_type"],
             t["rating"], t["interaction_date"], t.get("source_list"), t.get("source_index")),
        )
        inserted_tiktok_ints += 1

    # ── YouTube ───────────────────────────────────────────────────────────────
    inserted_yt_vids = 0
    for v in data.get("youtube_videos", []):
        if conn.execute("SELECT 1 FROM youtube_videos WHERE video_id=?", (v["video_id"],)).fetchone():
            continue
        conn.execute(
            "INSERT INTO youtube_videos (video_id, title, channel, duration_sec, url) VALUES (?,?,?,?,?)",
            (v["video_id"], v.get("title"), v.get("channel"), v.get("duration_sec"), v.get("url")),
        )
        inserted_yt_vids += 1

    inserted_yt_enrichment = 0
    for e in data.get("youtube_video_enrichment", []):
        if conn.execute("SELECT 1 FROM youtube_video_enrichment WHERE video_id=?", (e["video_id"],)).fetchone():
            continue
        conn.execute(
            "INSERT INTO youtube_video_enrichment (video_id, ambient_class, ambient_reason, "
            "ambient_source, topics, yt_categories, enrichment_model, prompt_version, enriched_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (e["video_id"], e.get("ambient_class"), e.get("ambient_reason"),
             e.get("ambient_source"), e.get("topics"), e.get("yt_categories"),
             e.get("enrichment_model"), e.get("prompt_version"), e.get("enriched_at")),
        )
        inserted_yt_enrichment += 1

    inserted_yt_events = 0
    for ev in data.get("youtube_watch_events", []):
        if conn.execute("SELECT 1 FROM youtube_watch_events WHERE event_id=?", (ev["event_id"],)).fetchone():
            continue
        conn.execute(
            "INSERT INTO youtube_watch_events (event_id, video_id, watched_at, source, source_index) "
            "VALUES (?,?,?,?,?)",
            (ev["event_id"], ev["video_id"], ev["watched_at"],
             ev.get("source"), ev.get("source_index")),
        )
        inserted_yt_events += 1

    inserted_yt_chapters = 0
    for c in data.get("youtube_chapters", []):
        if conn.execute("SELECT 1 FROM youtube_chapters WHERE chapter_id=?", (c["chapter_id"],)).fetchone():
            continue
        conn.execute(
            "INSERT INTO youtube_chapters (chapter_id, start_date, end_date, name, summary) "
            "VALUES (?,?,?,?,?)",
            (c["chapter_id"], c.get("start_date"), c.get("end_date"),
             c.get("name"), c.get("summary")),
        )
        inserted_yt_chapters += 1

    # ── Recommendations ───────────────────────────────────────────────────────
    inserted_recs = 0
    if not conn.execute("SELECT 1 FROM recommendations LIMIT 1").fetchone():
        for r in data.get("recommendations", []):
            conn.execute(
                "INSERT INTO recommendations (generated_at, media_type, title, author_or_director, "
                "reason, potential_issue, confidence, status) VALUES (?,?,?,?,?,?,?,?)",
                (r.get("generated_at"), r["media_type"], r["title"], r.get("author_or_director"),
                 r.get("reason"), r.get("potential_issue"), r.get("confidence", 0.7),
                 r.get("status", "pending")),
            )
            inserted_recs += 1

    conn.commit()
    conn.close()

    if inserted_tiktok_vids:
        print(f"Loaded {inserted_tiktok_vids} TikTok videos, {inserted_tiktok_ints} interactions")
    if inserted_yt_vids:
        print(f"Loaded {inserted_yt_vids} YouTube videos, {inserted_yt_events} watch events, "
              f"{inserted_yt_enrichment} enrichment, {inserted_yt_chapters} chapters")
    if inserted_recs:
        print(f"Loaded {inserted_recs} recommendations")

    MAP_DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(FIXTURE_MAP, MAP_DATA_PATH)

    total_items = inserted_items + skipped_items
    print(f"Loaded {inserted_items} items ({skipped_items} already present, {total_items} total)")
    print(f"Loaded {inserted_interactions} interactions")
    if inserted_plays:
        print(f"Loaded {inserted_plays} Spotify plays")
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
