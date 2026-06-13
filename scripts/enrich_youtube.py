"""Phase 2 YouTube enrichment: LLM topic tagging + life chapter detection.

Runs Claude Haiku on foreground videos to:
  1. Assign 2-3 topic tags per video (what is it actually about?)
  2. Detect ambient class for videos the rules couldn't classify (unknown)
  3. Name 2-month life chapter windows from title clusters

All LLM calls are cached by stable hash — re-runs cost $0 for unchanged videos.
Cache: data/cache/youtube_enrichment.json

Usage:
  python3 scripts/enrich_youtube.py              # full run
  python3 scripts/enrich_youtube.py --dry-run    # show counts, no API calls
  python3 scripts/enrich_youtube.py --chapters-only  # skip topics, only chapters
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from db import get_conn, init_db

CACHE_PATH  = Path(__file__).parent.parent / "data" / "cache" / "youtube_enrichment.json"
MODEL       = "claude-haiku-4-5-20251001"
PROMPT_VER  = "v1"
TOPIC_BATCH = 30  # videos per LLM call for topic tagging


# ── Anthropic client (reused from build_profile.py) ───────────────────────────

def _get_client():
    import anthropic
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        for cmd in [
            ["security", "find-generic-password", "-s", "anthropic-api-key", "-w"],
            ["security", "find-internet-password", "-s", "anthropic.com", "-w"],
        ]:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            if r.returncode == 0 and r.stdout.strip():
                key = r.stdout.strip()
                break
    if not key:
        raise RuntimeError(
            "No API key found.\n"
            "Options:\n"
            "  1. Run via Claude Code (no key needed — it runs in-session).\n"
            "  2. Set ANTHROPIC_API_KEY=sk-ant-... before running standalone."
        )
    import anthropic
    return anthropic.Anthropic(api_key=key)


def _call_json(client, prompt: str, max_tokens: int, required_keys: list[str]):
    for attempt in range(1, 4):
        resp = client.messages.create(
            model=MODEL,
            max_tokens=max_tokens,
            system="You are a structured JSON generator. Return only valid JSON, no markdown fences.",
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        try:
            parsed = json.loads(text)
            if required_keys:
                missing = [k for k in required_keys if k not in parsed]
                if missing:
                    raise ValueError(f"Missing keys: {missing}")
            return parsed
        except (json.JSONDecodeError, ValueError) as e:
            if attempt == 3:
                raise RuntimeError(f"Invalid JSON after 3 attempts: {e}\n{text[:200]}") from e
    raise RuntimeError("unreachable")


# ── Cache helpers ─────────────────────────────────────────────────────────────

def load_cache() -> dict:
    if CACHE_PATH.exists():
        try:
            return json.loads(CACHE_PATH.read_text())
        except json.JSONDecodeError:
            pass
    return {"topic_tags": {}, "chapters": {}}


def save_cache(cache: dict):
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, indent=2, ensure_ascii=False))


def topic_cache_key(video_id: str, title: str, channel: str) -> str:
    raw = f"{video_id}|{title}|{channel}|{MODEL}|{PROMPT_VER}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def chapter_cache_key(window_label: str, titles_blob: str) -> str:
    raw = f"{window_label}|{titles_blob}|{MODEL}|{PROMPT_VER}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


# ── Topic tagging ─────────────────────────────────────────────────────────────

TOPIC_PROMPT = """Given these YouTube videos a person watched, assign 2-3 specific topic tags per video describing what it's actually about. Use concrete topics (e.g. "One Piece analysis", "home electrical DIY", "board game tutorial", "SNL sketch", "AI tools") rather than generic tags.

For each video, also assess: is this genuinely foreground (intentional) viewing or should it be reclassified? The original rule classification is included.

Return JSON with this exact structure:
{{"results": [{{"id": "video_id", "topics": ["topic1", "topic2"], "ambient_class": "foreground"}}]}}

Videos:
{videos_json}"""

def enrich_topics(client, videos: list[dict], cache: dict) -> int:
    """Tag topics for a batch of foreground videos. Returns count of new API calls."""
    topic_cache = cache.setdefault("topic_tags", {})
    need_api: list[dict] = []

    for v in videos:
        key = topic_cache_key(v["video_id"], v["title"], v["channel"])
        if key not in topic_cache:
            need_api.append({**v, "_cache_key": key})

    if not need_api:
        return 0

    n_calls = 0
    for i in range(0, len(need_api), TOPIC_BATCH):
        batch = need_api[i : i + TOPIC_BATCH]
        videos_json = json.dumps(
            [{"id": v["video_id"], "title": v["title"], "channel": v["channel"],
              "duration_min": round(v["duration_sec"] / 60, 1),
              "current_class": v["ambient_class"]}
             for v in batch],
            ensure_ascii=False
        )
        prompt = TOPIC_PROMPT.format(videos_json=videos_json)
        result = _call_json(client, prompt, max_tokens=2048, required_keys=["results"])
        for item in result.get("results", []):
            vid_id = item.get("id", "")
            matching = next((b for b in batch if b["video_id"] == vid_id), None)
            if matching:
                key = matching["_cache_key"]
                topic_cache[key] = {
                    "video_id":    vid_id,
                    "topics":      item.get("topics", []),
                    "ambient_class": item.get("ambient_class", matching["ambient_class"]),
                    "model":       MODEL,
                    "prompt_ver":  PROMPT_VER,
                }
        n_calls += 1
        time.sleep(0.5)  # gentle rate limiting

    return n_calls


# ── Chapter detection ─────────────────────────────────────────────────────────

CHAPTER_PROMPT = """These YouTube videos were watched in {window}. Based on the titles, channels, and video mix, describe what life phase or interest this represents for the viewer — not just a topic, but a context (project, obsession, life event, etc.).

Return JSON:
{{"name": "short chapter name (2-5 words)", "summary": "1-2 sentence description of what this period represents"}}

Videos ({count} total, sample shown):
{videos_sample}"""

def detect_chapters(client, conn, cache: dict) -> int:
    """Detect 2-month life chapters from foreground video clusters. Returns new API calls."""
    chapter_cache = cache.setdefault("chapters", {})
    n_calls = 0

    rows = conn.execute("""
        SELECT strftime('%Y-%m', w.watched_at) month, v.title, v.channel, v.duration_sec
        FROM youtube_watch_events w
        JOIN youtube_videos v USING(video_id)
        JOIN youtube_video_enrichment e USING(video_id)
        WHERE e.ambient_class = 'foreground'
          AND w.watched_at IS NOT NULL
        ORDER BY w.watched_at
    """).fetchall()

    # Group into 2-month windows
    from collections import defaultdict
    monthly: dict[str, list] = defaultdict(list)
    for r in rows:
        monthly[r["month"]].append({"title": r["title"], "channel": r["channel"],
                                    "dur_sec": r["duration_sec"]})

    sorted_months = sorted(monthly.keys())
    # Pair consecutive months into windows
    windows: list[tuple[str, str, list]] = []
    i = 0
    while i < len(sorted_months):
        m1 = sorted_months[i]
        m2 = sorted_months[i + 1] if i + 1 < len(sorted_months) else m1
        combined = monthly[m1] + (monthly[m2] if m2 != m1 else [])
        if combined:
            windows.append((m1, m2, combined))
        i += 2

    for (m_start, m_end, videos_in_window) in windows:
        window_label = f"{m_start} to {m_end}" if m_start != m_end else m_start
        titles_blob = "|".join(v["title"] for v in videos_in_window)
        key = chapter_cache_key(window_label, titles_blob)
        if key in chapter_cache:
            continue

        # Sample up to 20 videos for the prompt
        sample = videos_in_window[:20]
        videos_sample = "\n".join(
            f'- [{v["title"]}] ({v["channel"]}) {round(v["dur_sec"]/60)}min'
            for v in sample
        )
        prompt = CHAPTER_PROMPT.format(
            window=window_label,
            count=len(videos_in_window),
            videos_sample=videos_sample,
        )
        result = _call_json(client, prompt, max_tokens=256, required_keys=["name", "summary"])
        chapter_cache[key] = {
            "window":  window_label,
            "m_start": m_start,
            "m_end":   m_end,
            "name":    result["name"],
            "summary": result["summary"],
            "model":   MODEL,
            "prompt_ver": PROMPT_VER,
        }
        n_calls += 1
        time.sleep(0.3)

    return n_calls


# ── Write enrichment to DB ────────────────────────────────────────────────────

def write_topics_to_db(conn, cache: dict):
    topic_cache = cache.get("topic_tags", {})
    for entry in topic_cache.values():
        vid_id = entry.get("video_id")
        if not vid_id:
            continue
        conn.execute("""
            INSERT INTO youtube_video_enrichment
                (video_id, ambient_class, ambient_reason, ambient_source,
                 topics, enrichment_model, prompt_version, enriched_at)
            VALUES (?, ?, 'llm_topic', 'llm', ?, ?, ?, datetime('now'))
            ON CONFLICT(video_id) DO UPDATE SET
                ambient_class=excluded.ambient_class,
                ambient_source='llm',
                topics=excluded.topics,
                enrichment_model=excluded.enrichment_model,
                prompt_version=excluded.prompt_version,
                enriched_at=excluded.enriched_at
        """, (
            vid_id,
            entry.get("ambient_class", "foreground"),
            json.dumps(entry.get("topics", [])),
            MODEL,
            PROMPT_VER,
        ))
    conn.commit()


def write_chapters_to_db(conn, cache: dict):
    conn.execute("DELETE FROM youtube_chapter_evidence")
    conn.execute("DELETE FROM youtube_chapters")
    chapter_cache = cache.get("chapters", {})
    for i, entry in enumerate(sorted(chapter_cache.values(), key=lambda x: x.get("m_start", ""))):
        chapter_id = f"ch_{i:03d}_{entry.get('m_start', '').replace('-', '')}"
        conn.execute("""
            INSERT INTO youtube_chapters
                (chapter_id, start_date, end_date, name, summary)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(chapter_id) DO UPDATE SET
                name=excluded.name, summary=excluded.summary
        """, (
            chapter_id,
            entry.get("m_start", "") + "-01",
            entry.get("m_end", "") + "-28",  # approximate
            entry.get("name", ""),
            entry.get("summary", ""),
        ))
    conn.commit()


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Enrich YouTube watch history with LLM.")
    parser.add_argument("--dry-run", action="store_true", help="Show stats, no API calls.")
    parser.add_argument("--chapters-only", action="store_true", help="Skip topic tagging.")
    args = parser.parse_args()

    conn = get_conn()
    init_db(conn)

    foreground = conn.execute("""
        SELECT v.video_id, v.title, v.channel, v.duration_sec, e.ambient_class
        FROM youtube_videos v
        JOIN youtube_video_enrichment e USING(video_id)
        WHERE e.ambient_class IN ('foreground', 'unknown')
        ORDER BY v.title
    """).fetchall()

    if not foreground:
        print("No foreground videos found. Run ingest_youtube.py first.")
        sys.exit(1)

    cache = load_cache()
    topic_cache = cache.get("topic_tags", {})
    n_cached = sum(
        1 for v in foreground
        if topic_cache_key(v["video_id"], v["title"], v["channel"]) in topic_cache
    )
    print(f"Foreground videos: {len(foreground)} ({n_cached} already cached, "
          f"{len(foreground) - n_cached} need API calls)")

    if args.dry_run:
        chapter_cache = cache.get("chapters", {})
        print(f"Chapters cached: {len(chapter_cache)}")
        print("Dry run — no API calls made.")
        return

    client = _get_client()
    videos_list = [dict(v) for v in foreground]

    if not args.chapters_only:
        print("Tagging topics…")
        n_calls = enrich_topics(client, videos_list, cache)
        save_cache(cache)
        print(f"  {n_calls} API calls made; writing to DB…")
        write_topics_to_db(conn, cache)

    print("Detecting life chapters…")
    n_ch = detect_chapters(client, conn, cache)
    save_cache(cache)
    print(f"  {n_ch} chapter calls; writing to DB…")
    write_chapters_to_db(conn, cache)

    # Summary
    chapters = conn.execute("SELECT name, start_date, end_date FROM youtube_chapters ORDER BY start_date").fetchall()
    print(f"\nChapters detected ({len(chapters)}):")
    for c in chapters:
        print(f"  {c['start_date'][:7]} → {c['end_date'][:7]}  {c['name']}")

    tagged = conn.execute(
        "SELECT COUNT(*) n FROM youtube_video_enrichment WHERE ambient_source = 'llm'"
    ).fetchone()["n"]
    print(f"\nTopic-tagged videos: {tagged}")


if __name__ == "__main__":
    main()
