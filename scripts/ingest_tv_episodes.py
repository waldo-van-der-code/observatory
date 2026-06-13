"""
Fetch episode-level data from TMDB for all IMDB-rated TV shows and insert into DB.

Rules:
- Shows in PARTIAL_WATCHES: ingest only up to the specified episode count
- Shows in SKIP_EPISODE_INGEST: skip episode-level ingestion entirely (show-level IMDB rating kept)
- All other shows with rated/completed interaction: insert all aired episodes, marked completed
- Idempotent: skip episodes already in DB
- Season 0 (specials) skipped unless covered by episode count

PARTIAL_WATCHES: {imdb_id: max_episodes}  — user watched approx N episodes
SKIP_EPISODE_INGEST: {imdb_id}            — user watched too few to bother with episode rows
"""

import sqlite3
import time
import sys
import requests
from pathlib import Path

TMDB_KEY = Path("~/.config/tmdb/api_key").expanduser().read_text().strip()
DB_PATH = "data/processed/entertainment.db"
ONE_PIECE_IMDB = "tt0388629"
ONE_PIECE_MAX_EP = 1120
RATE_LIMIT_DELAY = 0.25  # seconds between TMDB requests

# Shows where only a limited number of episodes were actually watched
# Values are approximate global episode counts (not season counts)
PARTIAL_WATCHES = {
    "tt0096697": 20,   # The Simpsons (~20 episodes)
    "tt1843230": 1,    # Once Upon a Time (1 episode)
    "tt1196946": 70,   # The Mentalist (~3 seasons ≈ 70 episodes)
    "tt0433309": 37,   # Numb3rs (~2 seasons ≈ 37 episodes)
    "tt3551096": 20,   # Fresh Off the Boat (~20 episodes)
    "tt1439629": 71,   # Community (~3 seasons ≈ 71 episodes)
    "tt0439100": 50,   # Weeds (~4 seasons ≈ 50 episodes)
    "tt0141842": 3,    # The Sopranos (3 episodes)
    "tt1865718": 2,    # Gravity Falls (2 episodes)
    "tt0348913": 1,    # Dead Like Me (1 episode)
    "tt5057054": 2,    # Jack Ryan (2 episodes)
    "tt0358856": 20,   # Little Britain (20 episodes)
    "tt0165598": 5,    # That '70s Show (5 episodes)
    "tt2193021": 4,    # Arrow (4 episodes)
    "tt2191671": 10,   # Elementary (10 episodes)
}

# Shows where so few episodes were watched that episode rows add no signal
SKIP_EPISODE_INGEST = {
    "tt0182576",   # Family Guy (~1 episode)
    "tt0121955",   # South Park (~5 episodes, disliked)
    "tt6524350",   # Big Mouth (not seen)
    "tt8369840",   # Another Life (not seen)
    "tt18314214",  # Is It Cake? (not seen)
}

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def tmdb_get(path, params=None, retries=3):
    url = f"https://api.themoviedb.org/3{path}"
    p = {"api_key": TMDB_KEY}
    if params:
        p.update(params)
    for attempt in range(retries):
        try:
            r = requests.get(url, params=p, timeout=10)
            if r.status_code == 429:
                time.sleep(5)
                continue
            r.raise_for_status()
            return r.json()
        except Exception as e:
            if attempt == retries - 1:
                raise
            time.sleep(2)
    return None

def find_tmdb_id(imdb_id):
    data = tmdb_get(f"/find/{imdb_id}", {"external_source": "imdb_id"})
    time.sleep(RATE_LIMIT_DELAY)
    results = data.get("tv_results", [])
    if results:
        return results[0]["id"]
    return None

def fetch_season_episodes(tmdb_id, season_num):
    data = tmdb_get(f"/tv/{tmdb_id}/season/{season_num}")
    time.sleep(RATE_LIMIT_DELAY)
    return data.get("episodes", [])

def ingest_show(conn, show_id, imdb_id, title, rating, date_completed, genres_json):
    if imdb_id in SKIP_EPISODE_INGEST:
        print(f"  ⊘ Skipping episode ingest (in SKIP_EPISODE_INGEST)")
        return 0, 0

    tmdb_id = find_tmdb_id(imdb_id)
    if not tmdb_id:
        print(f"  ✗ No TMDB match for {title} ({imdb_id})")
        return 0, 0

    show_data = tmdb_get(f"/tv/{tmdb_id}")
    time.sleep(RATE_LIMIT_DELAY)
    total_seasons = show_data.get("number_of_seasons", 0)
    runtime_list = show_data.get("episode_run_time", [])
    default_runtime = runtime_list[0] if runtime_list else None

    if imdb_id == ONE_PIECE_IMDB:
        max_ep = ONE_PIECE_MAX_EP
    elif imdb_id in PARTIAL_WATCHES:
        max_ep = PARTIAL_WATCHES[imdb_id]
    else:
        max_ep = 99999

    global_ep = 0
    inserted = 0
    skipped = 0

    for season_num in range(1, total_seasons + 1):
        episodes = fetch_season_episodes(tmdb_id, season_num)
        for ep in episodes:
            ep_num = ep.get("episode_number", 0)
            if ep_num == 0:
                continue  # skip mid-season specials numbered 0

            global_ep += 1
            if global_ep > max_ep:
                break

            ep_id = f"tmdb:tv:{tmdb_id}:s{season_num:02d}e{ep_num:02d}"
            air_date = ep.get("air_date") or None
            ep_title = ep.get("name") or f"Episode {ep_num}"
            runtime = ep.get("runtime") or default_runtime

            # Check if already exists
            existing = conn.execute(
                "SELECT id FROM media_items WHERE id=?", (ep_id,)
            ).fetchone()
            if existing:
                skipped += 1
                # Still ensure interaction exists
                has_interaction = conn.execute(
                    "SELECT id FROM user_interactions WHERE media_id=? AND interaction='completed'",
                    (ep_id,)
                ).fetchone()
                if not has_interaction:
                    conn.execute(
                        "INSERT INTO user_interactions (media_id, interaction, rating, date_completed, source) VALUES (?,?,?,?,?)",
                        (ep_id, "completed", rating, air_date, "tmdb")
                    )
                continue

            conn.execute(
                """INSERT INTO media_items
                   (id, media_type, title, year, genres, series_name, series_pos, runtime_min, source, source_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    ep_id,
                    "tv_episode",
                    ep_title,
                    int(air_date[:4]) if air_date and len(air_date) >= 4 else None,
                    genres_json,
                    title,
                    global_ep,
                    runtime,
                    "tmdb",
                    str(tmdb_id),
                )
            )
            conn.execute(
                "INSERT INTO user_interactions (media_id, interaction, rating, date_completed, source) VALUES (?,?,?,?,?)",
                (ep_id, "completed", rating, air_date, "tmdb")
            )
            inserted += 1

        if global_ep >= max_ep:
            break

    conn.commit()
    return inserted, skipped

def main():
    conn = get_conn()

    # Get all IMDB TV shows that have been rated or completed
    shows = conn.execute("""
        SELECT DISTINCT m.id, m.title, m.source_id, m.genres,
               MAX(ui.rating) as rating,
               MAX(ui.date_completed) as date_completed
        FROM media_items m
        JOIN user_interactions ui ON ui.media_id = m.id
        WHERE m.source = 'imdb'
          AND m.media_type = 'tv_show'
          AND ui.interaction IN ('rated','completed')
          AND m.source_id IS NOT NULL
          AND m.source_id != ''
        GROUP BY m.id
        ORDER BY m.title
    """).fetchall()

    print(f"Found {len(shows)} IMDB TV shows with interactions")

    total_inserted = 0
    total_skipped = 0

    for i, show in enumerate(shows):
        imdb_id = show["source_id"]
        title = show["title"]
        rating = show["rating"]
        date_completed = show["date_completed"]
        genres_json = show["genres"]

        print(f"\n[{i+1}/{len(shows)}] {title} ({imdb_id})", flush=True)

        try:
            ins, skp = ingest_show(conn, show["id"], imdb_id, title, rating, date_completed, genres_json)
            total_inserted += ins
            total_skipped += skp
            print(f"  ✓ inserted={ins} skipped={skp}", flush=True)
        except Exception as e:
            print(f"  ✗ ERROR: {e}", flush=True)

    print(f"\n{'='*50}")
    print(f"Done. Total inserted: {total_inserted}, skipped: {total_skipped}")

    # Summary
    ep_count = conn.execute("SELECT COUNT(*) FROM media_items WHERE media_type='tv_episode'").fetchone()[0]
    print(f"Total tv_episode rows in DB: {ep_count}")

if __name__ == "__main__":
    main()
