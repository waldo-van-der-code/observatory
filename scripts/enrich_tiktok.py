"""Enrich TikTok liked and favorited videos with yt-dlp metadata.

Scope: tiktok_videos WHERE enrichment_status IN ('pending', 'failed')
         AND enrichment_attempts < 3

Usage:
    python3 scripts/enrich_tiktok.py             # enrich all eligible
    python3 scripts/enrich_tiktok.py --limit 20  # test run (first 20)

Resumable: safe to stop and restart. Already-enriched videos are skipped.
Rate-limited to ~1 request/1.5s with exponential backoff on failures.

yt-dlp is best-effort — TikTok can break extractors at any time. Videos
that are deleted, private, or region-blocked will fail and be tracked as
enrichment_status='failed'. After 3 attempts a video is no longer retried.
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from categories import derive_categories
from db import get_conn, init_db

YT_DLP = shutil.which("yt-dlp") or "/opt/homebrew/bin/yt-dlp"


def enrich_video(conn, video_id: str, url: str) -> tuple[bool, str]:
    """Fetch yt-dlp metadata for one video. Returns (success, error_msg)."""
    if not Path(YT_DLP).exists():
        return False, f"yt-dlp not found at {YT_DLP}"

    try:
        result = subprocess.run(
            [
                YT_DLP,
                "--dump-json",
                "--no-download",
                "--no-playlist",
                "--ignore-no-formats-error",
                "--socket-timeout", "20",
                url,
            ],
            capture_output=True,
            timeout=30,
            text=True,
        )
    except subprocess.TimeoutExpired:
        return False, "timeout after 30s"
    except Exception as e:
        return False, str(e)[:300]

    if result.returncode != 0:
        err = (result.stderr or "unknown error").strip()[:500]
        return False, err

    try:
        meta = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        return False, f"JSON parse error: {e}"

    hashtags = meta.get("tags") or []
    if not hashtags:
        # TikTok puts hashtags in description text rather than the tags field
        raw_text = (meta.get("description") or meta.get("title") or "")
        hashtags = re.findall(r'#(\w+)', raw_text)
    categories = derive_categories(hashtags)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    conn.execute(
        """UPDATE tiktok_videos SET
               title                      = ?,
               description                = ?,
               hashtags                   = ?,
               categories                 = ?,
               enrichment_status          = 'success',
               enrichment_error           = NULL,
               raw_metadata_json          = ?,
               enriched_at                = ?
           WHERE video_id = ?""",
        (
            meta.get("title"),
            (meta.get("description") or "")[:1000],
            json.dumps(hashtags),
            json.dumps(categories),
            json.dumps(meta)[:50_000],
            now,
            video_id,
        ),
    )
    conn.commit()
    return True, ""


def main() -> None:
    parser = argparse.ArgumentParser(description="Enrich TikTok liked/favorited videos")
    parser.add_argument("--limit", type=int, default=0, help="Max videos to enrich (0=all)")
    args = parser.parse_args()

    conn = get_conn()
    init_db(conn)

    rows = conn.execute("""
        SELECT video_id, url FROM tiktok_videos
        WHERE enrichment_status IN ('pending', 'failed')
          AND enrichment_attempts < 3
        ORDER BY enrichment_status ASC, enrichment_attempts ASC
    """).fetchall()

    if args.limit > 0:
        rows = rows[:args.limit]

    total = len(rows)
    if total == 0:
        print("Nothing to enrich. All eligible videos are already processed.")
        return

    print(f"Enriching {total} videos (yt-dlp at {YT_DLP})")
    success = failed = 0

    for i, row in enumerate(rows, 1):
        video_id = row["video_id"]
        url = row["url"]

        # Increment attempt counter before trying (so partial failures are tracked)
        conn.execute(
            """UPDATE tiktok_videos
               SET enrichment_attempts = enrichment_attempts + 1,
                   last_enrichment_attempt_at = ?
               WHERE video_id = ?""",
            (datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"), video_id),
        )
        conn.commit()

        ok, err = enrich_video(conn, video_id, url)
        if ok:
            success += 1
            status_str = "OK"
        else:
            conn.execute(
                "UPDATE tiktok_videos SET enrichment_status='failed', enrichment_error=? WHERE video_id=?",
                (err[:500], video_id),
            )
            conn.commit()
            failed += 1
            status_str = f"FAIL: {err[:80]}"

        print(f"[{i:>5}/{total}] {video_id}  {status_str}")

        # Rate-limit: 1.5s base delay; double after failure (min 1.5, max 6)
        delay = 1.5 if ok else min(6.0, 1.5 * (2 ** min(3, failed)))
        time.sleep(delay)

    conn.close()
    print(f"\nDone: {success} enriched, {failed} failed out of {total} attempted.")
    print("Run `python3 scripts/build_dashboard.py` to update the dashboard.")


if __name__ == "__main__":
    main()
