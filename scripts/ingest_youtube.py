"""Ingest youtube-watch-history/watch-history.md into entertainment.db.

Parses the pre-processed markdown (title, channel, duration, date per video)
and applies deterministic ambient classification before upserting into the
youtube_videos, youtube_watch_events, and youtube_video_enrichment tables.

Phase 2 (enrich_youtube.py) will apply LLM topic tagging and chapter detection.
"""

import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from db import get_conn, init_db

HISTORY_MD = Path(__file__).parent.parent / "youtube-watch-history" / "watch-history.md"
OVERRIDES   = Path(__file__).parent.parent / "config" / "ambient_overrides.json"

# ── Month name → number ───────────────────────────────────────────────────────

MONTH_NAMES = {
    "January": 1, "February": 2, "March": 3, "April": 4,
    "May": 5, "June": 6, "July": 7, "August": 8,
    "September": 9, "October": 10, "November": 11, "December": 12,
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4,
    "Jun": 6, "Jul": 7, "Aug": 8, "Sep": 9,
    "Oct": 10, "Nov": 11, "Dec": 12,
}

# ── Ambient classification rules ──────────────────────────────────────────────

CHILDCARE_CHANNELS = {
    "Bluey - Official Channel",
}
AMBIENT_CHANNELS = {
    "Adam Eschborn",           # timer videos
    "Nashville Bird Cam",      # bird cam live stream
    "Fireplace 4K",            # fireplace ambience
    "Soothing Relaxation",     # sleep/relaxation music
    "The Timer",               # pomodoro timers
    "Entspannungsmusik by Feature Beats",  # German relaxation music
    "Psychi Trips",            # psychedelic visual mixes
    "Sehnend",                 # ambient focus music
}
KARAOKE_CHANNELS = {
    "Sing King",
    "KaraFun Karaoke",
    "Johnny Ds KilleR KaraoKe",
    "Zoom Karaoke Official",
}

AMBIENT_TITLE_KW = [
    "fireplace", "timer", "bird cam", "bird feeder", "lofi", "lo-fi",
    "ambience", "ambient", "relaxation", "sleep music", "pomodoro",
    "entspannungsmusik", "wellness", "spa musik", "meditation",
    "beautiful piano", "psychedelic", "trippy music mix",
    "crackling", "burning logs",
]
CHILDCARE_TITLE_KW = ["bluey"]
KARAOKE_TITLE_KW   = ["karaoke", "sing along", "singalong"]
LIVE_STREAM_KW     = ["🔴live", "🔴 live", "24/7", "24 hours", "24hours",
                      "live stream", "live 24"]


def classify_ambient(title: str, channel: str, duration_sec: int,
                     overrides: dict) -> tuple[str, str]:
    """Return (ambient_class, reason). All rule-based — LLM handles unknowns."""
    vid_check_key = channel  # overrides keyed by channel or title substring

    t = title.lower()
    c = channel

    # Manual overrides from config/ambient_overrides.json
    if c in overrides.get("channels", {}):
        return overrides["channels"][c], f"override:channel:{c}"
    for kw, cls in overrides.get("title_keywords", {}).items():
        if kw.lower() in t:
            return cls, f"override:title:{kw}"

    # Childcare
    if c in CHILDCARE_CHANNELS or any(k in t for k in CHILDCARE_TITLE_KW):
        reason = f"channel:{c}" if c in CHILDCARE_CHANNELS else "title:bluey"
        return "childcare_background", reason

    # Karaoke / social
    if c in KARAOKE_CHANNELS or any(k in t for k in KARAOKE_TITLE_KW):
        return "social_background", f"channel:{c}" if c in KARAOKE_CHANNELS else "title:karaoke"

    # Named ambient channels
    if c in AMBIENT_CHANNELS:
        return "ambient", f"channel:{c}"

    # Title keyword ambient
    for kw in AMBIENT_TITLE_KW:
        if kw in t:
            return "ambient", f"title:{kw}"

    # Live streams > 90 min → ambient
    if any(k in t for k in LIVE_STREAM_KW) and duration_sec > 5400:
        return "ambient", "live_stream>90min"

    # Very long — > 10h is almost certainly background content
    if duration_sec > 36000:
        return "ambient", "duration>10h"

    return "foreground", ""


# ── Parsing helpers ───────────────────────────────────────────────────────────

# Matches: - [Title](URL) — Channel `duration` · DD Mon
# Uses lazy .+? for title so brackets inside (e.g. "[HD]") are handled via backtracking.
VIDEO_LINE_RE = re.compile(
    r'^-\s+\[(.+?)\]\((https?://[^)]+)\)\s+—\s+(.*?)\s+`([^`]+)`\s+·\s+(\d{1,2}\s+\w+)\s*$'
)
DURATION_RE = re.compile(r'^(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?$')


def parse_duration(s: str) -> int:
    """'1h30m', '45m20s', '11m21s' → seconds."""
    m = DURATION_RE.match(s.strip())
    if not m:
        return 0
    h, mm, ss = m.group(1), m.group(2), m.group(3)
    return int(h or 0) * 3600 + int(mm or 0) * 60 + int(ss or 0)


def extract_video_id(url: str) -> str | None:
    m = re.search(r'[?&]v=([A-Za-z0-9_-]{11})', url)
    return m.group(1) if m else None


def parse_date(day_month: str, year: int) -> str:
    """'01 May' + 2026 → '2026-05-01'."""
    parts = day_month.strip().split()
    if len(parts) == 2:
        try:
            day   = int(parts[0])
            month = MONTH_NAMES.get(parts[1], 0)
            if month:
                return f"{year}-{month:02d}-{day:02d}"
        except (ValueError, KeyError):
            pass
    return f"{year}-01-01"


def make_event_id(video_id: str, date: str, source_index: int) -> str:
    """Stable unique ID per watch event. source_index handles same-video same-day duplicates."""
    raw = f"{video_id}|{date}|{source_index}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def parse_history(path: Path, overrides: dict) -> list[dict]:
    """Parse watch-history.md → list of video event dicts."""
    entries = []
    current_year = 0
    idx = 0

    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.rstrip()

        if line.startswith("## "):
            try:
                yr = int(line[3:].strip())
                # Skip obviously bogus years (Google Takeout uses year 1 for corrupted timestamps)
                current_year = yr if yr >= 2000 else 0
            except ValueError:
                pass
            continue

        if line.startswith("### ") or not line.startswith("- ["):
            continue

        m = VIDEO_LINE_RE.match(line)
        if not m or not current_year:
            continue

        title, url, channel, dur_str, day_month = m.groups()
        channel = channel.strip()

        video_id = extract_video_id(url)
        if not video_id:
            continue

        duration_sec = parse_duration(dur_str)
        date         = parse_date(day_month, current_year)
        event_id     = make_event_id(video_id, date, idx)
        ambient_class, ambient_reason = classify_ambient(
            title, channel, duration_sec, overrides
        )

        entries.append({
            "video_id":      video_id,
            "title":         title,
            "url":           url,
            "channel":       channel,
            "duration_sec":  duration_sec,
            "date":          date,
            "event_id":      event_id,
            "source_index":  idx,
            "ambient_class": ambient_class,
            "ambient_reason": ambient_reason,
        })
        idx += 1

    return entries


def ingest(conn, entries: list[dict]) -> tuple[int, int]:
    """Clear and re-insert all YouTube data. Returns (unique_videos, total_events).

    Watch events and video catalog are fully rebuilt on every run (stable source).
    LLM enrichment rows (ambient_source='llm') are preserved by deleting only
    rule-based rows first, then re-inserting them.
    """
    # Preserve LLM enrichment — collect video_ids that have LLM results
    llm_enriched = set(
        r[0] for r in conn.execute(
            "SELECT video_id FROM youtube_video_enrichment WHERE ambient_source = 'llm'"
        ).fetchall()
    )

    # Clear watch data (fully derived from source file — safe to rebuild)
    # Chapters and LLM enrichment are preserved (they're generated separately)
    conn.execute("DELETE FROM youtube_chapter_evidence")
    conn.execute("DELETE FROM youtube_watch_events")
    # Delete only rule-based enrichment rows (preserve LLM)
    conn.execute("DELETE FROM youtube_video_enrichment WHERE ambient_source = 'rule' OR ambient_source IS NULL")
    conn.execute("DELETE FROM youtube_videos")

    seen_videos: set[str] = set()
    n_events = 0

    for e in entries:
        conn.execute("""
            INSERT INTO youtube_videos (video_id, title, channel, duration_sec, url)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(video_id) DO NOTHING
        """, (e["video_id"], e["title"], e["channel"], e["duration_sec"], e["url"]))
        seen_videos.add(e["video_id"])

        conn.execute("""
            INSERT INTO youtube_watch_events
                (event_id, video_id, watched_at, source, source_index)
            VALUES (?, ?, ?, 'markdown', ?)
        """, (e["event_id"], e["video_id"], e["date"], e["source_index"]))
        n_events += 1

        # Insert rule-based enrichment only if no LLM result exists
        if e["video_id"] not in llm_enriched:
            conn.execute("""
                INSERT OR IGNORE INTO youtube_video_enrichment
                    (video_id, ambient_class, ambient_reason, ambient_source, enriched_at)
                VALUES (?, ?, ?, 'rule', datetime('now'))
            """, (e["video_id"], e["ambient_class"], e["ambient_reason"]))

    conn.commit()
    return len(seen_videos), n_events


def main():
    if not HISTORY_MD.exists():
        print(f"No watch history found at {HISTORY_MD}", file=sys.stderr)
        sys.exit(1)

    overrides = {}
    if OVERRIDES.exists():
        overrides = json.loads(OVERRIDES.read_text())

    conn = get_conn()
    init_db(conn)

    entries = parse_history(HISTORY_MD, overrides)
    n_videos, n_events = ingest(conn, entries)

    # Summary
    rows = conn.execute("""
        SELECT e.ambient_class, COUNT(*) cnt
        FROM youtube_video_enrichment e
        GROUP BY e.ambient_class
        ORDER BY cnt DESC
    """).fetchall()

    print(f"YouTube ingested: {n_videos} unique videos, {n_events} watch events")
    for r in rows:
        print(f"  {r['ambient_class'] or 'unknown':<22} {r['cnt']:>4}")


if __name__ == "__main__":
    main()
