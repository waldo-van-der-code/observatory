#!/usr/bin/env python3
"""Ingest individual TV episodes for partially-watched shows into entertainment.db.

Only runs for shows explicitly listed in PARTIAL_WATCHES. Shows in SKIP_EPISODE_INGEST
are rated at show level only — do not ingest episode rows for them.

Without these guards, any IMDB-rated TV show would trigger a full-series ingest,
inflating watch counts to 800+ for shows like The Simpsons.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from db import get_conn, init_db

# IMDb IDs of shows rated at show level only — do NOT expand into episodes.
# Typically shows disliked after a few eps, or shows too long to bother tracking.
SKIP_EPISODE_INGEST = {
    "tt0096697",  # The Simpsons (also in PARTIAL_WATCHES, this is the safety fallback)
    "tt0182576",  # Family Guy
    "tt0121955",  # South Park
}

# IMDb ID → max number of episodes to ingest (actual watched count).
# Episodes are taken from earliest season first.
PARTIAL_WATCHES: dict[str, int] = {
    "tt0096697": 20,  # The Simpsons — watched ~20 eps across early seasons
}


def ingest_show(conn, imdb_id: str, max_eps: int) -> int:
    """Ingest up to max_eps episodes for a show. Returns number inserted."""
    if imdb_id in SKIP_EPISODE_INGEST and imdb_id not in PARTIAL_WATCHES:
        print(f"  Skipping {imdb_id} — in SKIP_EPISODE_INGEST")
        return 0

    # Check TMDB xref
    row = conn.execute(
        "SELECT tmdb_id FROM imdb_xref WHERE imdb_id=?", (imdb_id,)
    ).fetchone()
    if not row:
        print(f"  No TMDB xref for {imdb_id} — run server.py search first to populate xref")
        return 0

    tmdb_id = row["tmdb_id"]

    # Check how many are already ingested
    existing = conn.execute(
        "SELECT COUNT(*) n FROM media_items WHERE source='tmdb' AND series_name IS NOT NULL "
        "AND source_id LIKE ?", (f"{tmdb_id}-%",)
    ).fetchone()["n"]

    if existing >= max_eps:
        print(f"  {imdb_id}: {existing} episodes already present (limit {max_eps}) — nothing to do")
        return 0

    print(f"  {imdb_id}: {existing} episodes present, limit {max_eps} — TMDB fetch needed")
    # Actual TMDB episode fetch would go here when needed.
    # Keeping this stub safe: return 0 rather than accidentally over-ingesting.
    return 0


def main():
    conn = get_conn()
    init_db(conn)

    print("TV episode ingest — guarded mode")
    print(f"  SKIP_EPISODE_INGEST: {len(SKIP_EPISODE_INGEST)} shows blocked")
    print(f"  PARTIAL_WATCHES: {len(PARTIAL_WATCHES)} shows with episode caps")

    total = 0
    for imdb_id, max_eps in PARTIAL_WATCHES.items():
        print(f"\nProcessing {imdb_id} (cap: {max_eps} eps):")
        n = ingest_show(conn, imdb_id, max_eps)
        total += n

    print(f"\nDone: {total} episodes inserted")

    # Verification
    counts = conn.execute(
        "SELECT series_name, COUNT(*) n FROM media_items "
        "WHERE media_type='tv_episode' GROUP BY series_name ORDER BY n DESC LIMIT 10"
    ).fetchall()
    if counts:
        print("\nEpisode counts by show:")
        for r in counts:
            print(f"  {r['series_name']}: {r['n']}")
    else:
        print("\nNo tv_episode rows in DB.")


if __name__ == "__main__":
    main()
