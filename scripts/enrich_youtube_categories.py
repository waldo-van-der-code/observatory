"""Backfill rule-based content categories on youtube_video_enrichment.

Adds a yt_categories JSON column (if missing) and populates it for all
foreground videos using title + channel keyword matching. No API calls.

Safe to re-run — uses INSERT OR IGNORE / UPDATE pattern.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from categories import categorise_youtube_video
from db import get_conn, init_db


def main() -> None:
    conn = get_conn()
    init_db(conn)

    # Add yt_categories column if it doesn't exist yet
    cols = [r[1] for r in conn.execute("PRAGMA table_info(youtube_video_enrichment)").fetchall()]
    if "yt_categories" not in cols:
        conn.execute("ALTER TABLE youtube_video_enrichment ADD COLUMN yt_categories TEXT")
        conn.commit()
        print("Added yt_categories column")

    rows = conn.execute("""
        SELECT v.video_id, v.title, v.channel, e.ambient_class
        FROM youtube_videos v
        JOIN youtube_video_enrichment e USING(video_id)
        WHERE e.ambient_class = 'foreground'
          AND (e.yt_categories IS NULL OR e.yt_categories = '[]')
    """).fetchall()

    if not rows:
        print("All foreground videos already categorised.")
        return

    print(f"Categorising {len(rows)} foreground videos...")
    updated = 0
    for row in rows:
        cats = categorise_youtube_video(row["title"] or "", row["channel"] or "")
        conn.execute(
            "UPDATE youtube_video_enrichment SET yt_categories=? WHERE video_id=?",
            (json.dumps(cats), row["video_id"]),
        )
        updated += 1

    conn.commit()
    conn.close()
    print(f"Done: {updated} videos categorised.")

    # Quick summary
    conn2 = get_conn()
    conn2.row_factory = __import__("sqlite3").Row
    cat_counts: dict[str, int] = {}
    for r in conn2.execute(
        "SELECT yt_categories FROM youtube_video_enrichment WHERE yt_categories IS NOT NULL AND yt_categories != '[]'"
    ).fetchall():
        try:
            for c in json.loads(r["yt_categories"]):
                cat_counts[c] = cat_counts.get(c, 0) + 1
        except Exception:
            pass
    top = sorted(cat_counts.items(), key=lambda x: -x[1])[:10]
    print("Top YouTube categories:", top)
    conn2.close()


if __name__ == "__main__":
    main()
