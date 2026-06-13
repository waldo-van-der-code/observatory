#!/usr/bin/env python3
"""Generate taste profile + recommendations via Claude, store in entertainment.db."""

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import anthropic

sys.path.insert(0, str(Path(__file__).parent))
from db import get_conn, init_db

MODEL = "claude-haiku-4-5-20251001"

CACHE_DIR = Path(__file__).parent.parent / "data" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
PROFILE_CACHE = CACHE_DIR / "claude_profile_cache.json"

def _load_taste_seed() -> str:
    seed_path = Path("~/.config/observatory/taste_seed.txt").expanduser()
    return seed_path.read_text().strip() if seed_path.exists() else ""

TASTE_SEED = _load_taste_seed()


def _get_client() -> anthropic.Anthropic:
    """Direct Anthropic API only (this is a personal project, not KA/Bedrock)."""
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
            "No ANTHROPIC_API_KEY found.\n"
            "Options:\n"
            "  1. Re-run profile generation via Claude Code (no key needed — it runs in-session).\n"
            "  2. Set ANTHROPIC_API_KEY=sk-ant-... from console.anthropic.com before running standalone."
        )
    return anthropic.Anthropic(api_key=key)


def _call_json(client: anthropic.Anthropic, prompt: str, max_tokens: int,
               required_keys: list[str]) -> dict | list:
    for attempt in range(1, 4):
        resp = client.messages.create(
            model=MODEL,
            max_tokens=max_tokens,
            system="You are a structured JSON generator. Return only valid JSON, no explanation.",
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
                raise RuntimeError(f"Claude returned invalid JSON after 3 attempts: {e}\n{text}") from e
    raise RuntimeError("unreachable")


def build_history_json(conn) -> list[dict]:
    rows = conn.execute("""
        SELECT m.id, m.title, m.author, m.media_type, m.year,
               m.series_name, m.series_pos, m.genres,
               ui.rating, ui.interaction, ui.shelf, ui.date_completed
        FROM media_items m
        JOIN user_interactions ui ON ui.media_id = m.id
        ORDER BY ui.date_completed DESC NULLS LAST
    """).fetchall()
    return [dict(r) for r in rows]


def interactions_hash(history: list[dict]) -> str:
    s = json.dumps(history, sort_keys=True, default=str)
    return hashlib.sha256(s.encode()).hexdigest()[:16]


def load_cache(key: str) -> dict | None:
    if PROFILE_CACHE.exists():
        data = json.loads(PROFILE_CACHE.read_text())
        if data.get("key") == key:
            return data.get("profile")
    return None


def save_cache(key: str, profile: dict, recs: list) -> None:
    PROFILE_CACHE.write_text(
        json.dumps({"key": key, "profile": profile, "recommendations": recs}, indent=2)
    )


def generate_profile(client: anthropic.Anthropic, history: list[dict]) -> dict:
    rated = [h for h in history if h.get("rating")]
    history_text = json.dumps(rated, default=str)

    prompt = f"""You are building a personal entertainment taste profile covering books, films, and TV.

{TASTE_SEED}

Here is the user's complete rated media history (JSON):
{history_text}

Produce a JSON object with exactly these keys:
{{
  "profile_summary": "2-4 sentences capturing the user's overall taste in one direct voice. Be specific: name genres, name reference titles, identify the recurring intellectual or emotional thread. No hedging. Example register: 'A reader drawn to ideas at civilizational scale — hard SF, morally complex power struggles, comic philosophy that takes itself seriously.'",
  "genre_fingerprint": {{"genre_name": 0.0_to_1.0, ...}},
  "film_genre_fingerprint": {{"genre_name": 0.0_to_1.0, ...}},
  "top_themes": ["narrative/thematic theme 1", ...],
  "rating_calibration": {{"mean": 4.36, "tendency": "generous|harsh|balanced", "five_star_threshold": "short description"}},
  "taste_clusters": [{{"name": "cluster name", "media": "books|films|mixed", "items": ["title1", "title2"], "description": "2-sentence why these cohere"}}],
  "dislikes_pattern": ["pattern 1", "pattern 2", ...],
  "top_authors": [{{"name": "author", "avg_rating": 4.5, "count": 10}}],
  "top_directors": [{{"name": "director", "avg_rating": 4.5, "count": 2}}]
}}

Rules:
- profile_summary: direct, specific, no hedging. 2-4 sentences max.
- genre_fingerprint: books only. Score 0-1. Include 8-12 genres. Use names like "Hard Science Fiction", "Comic Fantasy", "Epic Fantasy".
- film_genre_fingerprint: films and TV only. Score 0-1. Include 8-12 genres. Use cinema genre names like "Science Fiction", "Drama", "Thriller", "Action", "Historical", "Comedy", "Documentary".
- top_themes: 4-6 narrative/thematic patterns that appear across both books AND films (transcend medium).
- taste_clusters: 4-6 cohesive groups. Mix book clusters AND film/TV clusters — label each with "media" field. Use actual rated titles.
- top_authors: all authors with 2+ rated books, sorted by avg_rating desc.
- top_directors: all directors with 2+ rated films, sorted by avg_rating desc.
- Return ONLY the JSON object."""

    return _call_json(client, prompt, max_tokens=2500,
                      required_keys=["genre_fingerprint", "top_themes", "rating_calibration",
                                     "taste_clusters", "dislikes_pattern", "top_authors",
                                     "profile_summary"])


def generate_recommendations(client: anthropic.Anthropic, profile: dict,
                             consumed_titles: set[str]) -> list[dict]:
    prompt = f"""You are a personal media recommendation engine covering books, films, and TV.

The user's taste profile:
{json.dumps(profile, indent=2)}

Titles already consumed (do NOT recommend these):
{json.dumps(sorted(consumed_titles))}

Recommend exactly: 25 books, 15 films, and 10 TV shows this user is most likely to rate 5 stars.
Return a JSON array where each item has exactly:
{{
  "media_type": "book" | "film" | "tv_show",
  "title": "exact title",
  "author_or_director": "name",
  "reason": "2 sentences grounded in their specific taste clusters and themes — name specific titles they rated highly as reference points",
  "potential_issue": "1 honest sentence on why they might not like it, based on their dislikes pattern",
  "confidence": 0.0_to_1.0
}}

Rules:
- Real published/released titles only.
- Prioritise standalone works or completed series.
- For films: use their film_genre_fingerprint and top_directors as primary signals.
- For books: use their genre_fingerprint and top_authors as primary signals.
- Match their highest-rated titles' energy, not their average.
- Return ONLY the JSON array."""

    result = _call_json(client, prompt, max_tokens=6000, required_keys=[])
    if isinstance(result, list):
        return result
    for v in result.values():
        if isinstance(v, list):
            return v
    return []


def generate_recommendations_extended(client: anthropic.Anthropic, profile: dict,
                                      consumed_titles: set[str]) -> list[dict]:
    """Generate music, podcast, and comics recommendations (no TMDB tokens)."""
    prompt = f"""You are a personal media recommendation engine for music, podcasts, and comics/graphic novels.

The user's taste profile:
{json.dumps(profile, indent=2)}

Known consumed titles (do NOT recommend these):
{json.dumps(sorted(list(consumed_titles)[:200]))}

Recommend:
- Exactly 10 music albums or artists (based on their Spotify listening history showing trance/electronic/ambient affinity, plus their intellectual taste profile)
- Exactly 10 podcasts (matching their intellectual interests: hard science, civilizational thinking, morally complex narratives, long-form ideas)
- Exactly 10 comics/graphic novels (matching their literary taste for complex narratives and visual storytelling)

Return a JSON array where each item has exactly:
{{
  "media_type": "music" | "podcast" | "comic",
  "title": "album or artist name | podcast title | comic/graphic novel title",
  "author_or_director": "artist/band | publisher/host | author/artist",
  "reason": "2 sentences grounded in their specific taste — reference their known preferences",
  "potential_issue": "1 honest sentence on why they might not like it",
  "confidence": 0.0_to_1.0
}}

Rules:
- Real titles only. For music: prefer albums over artists when specific.
- For podcasts: intellectual, long-form, evidence-based or narrative-driven — no entertainment gossip.
- For comics: literary graphic novels or acclaimed series, not superhero mainstream.
- Return ONLY the JSON array."""

    result = _call_json(client, prompt, max_tokens=4000, required_keys=[])
    if isinstance(result, list):
        return result
    for v in result.values():
        if isinstance(v, list):
            return v
    return []


def store_profile(conn, profile: dict) -> None:
    conn.execute("DELETE FROM taste_profile")
    conn.execute(
        "INSERT INTO taste_profile "
        "(generated_at, genre_fingerprint, film_genre_fingerprint, top_themes, rating_calibration, "
        "taste_clusters, dislikes_pattern, top_authors, top_directors, raw_response) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            datetime.now(timezone.utc).isoformat(),
            json.dumps(profile.get("genre_fingerprint", {})),
            json.dumps(profile.get("film_genre_fingerprint", {})),
            json.dumps(profile.get("top_themes", [])),
            json.dumps(profile.get("rating_calibration", {})),
            json.dumps(profile.get("taste_clusters", [])),
            json.dumps(profile.get("dislikes_pattern", [])),
            json.dumps(profile.get("top_authors", [])),
            json.dumps(profile.get("top_directors", [])),
            json.dumps(profile),
        ),
    )
    conn.commit()


def store_recommendations(conn, recs: list[dict]) -> None:
    conn.execute("DELETE FROM recommendations WHERE status='pending'")
    now = datetime.now(timezone.utc).isoformat()
    for r in recs:
        if not isinstance(r, dict):
            continue
        conn.execute(
            "INSERT INTO recommendations "
            "(generated_at, media_type, title, author_or_director, reason, potential_issue, confidence) "
            "VALUES (?,?,?,?,?,?,?)",
            (now, r.get("media_type"), r.get("title"), r.get("author_or_director"),
             r.get("reason"), r.get("potential_issue"), r.get("confidence")),
        )
    conn.commit()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true", help="Force re-run even if cache is valid")
    parser.add_argument("--refresh-recs", action="store_true", help="Re-run recommendations only")
    parser.add_argument("--dry-run", action="store_true", help="Print prompt context, no API call")
    args = parser.parse_args()

    conn = get_conn()
    init_db(conn)
    history = build_history_json(conn)
    cache_key = interactions_hash(history)
    print(f"History: {len(history)} interactions, cache key: {cache_key}")

    if args.dry_run:
        rated = [h for h in history if h.get("rating")]
        print(f"Would send {len(rated)} rated items to Claude")
        print(json.dumps(rated[:3], indent=2, default=str))
        return

    client = _get_client()

    cached = None if (args.refresh or args.refresh_recs) else load_cache(cache_key)
    if args.refresh_recs and not args.refresh:
        # Reload profile from cache or DB without regenerating it
        cached = load_cache(cache_key) or json.loads(
            conn.execute("SELECT raw_response FROM taste_profile").fetchone()["raw_response"]
        )
    elif cached:
        print("Cache hit — skipping profile generation")
        store_profile(conn, cached)
    else:
        print("Calling Claude for taste profile…")
        profile = generate_profile(client, history)
        print(f"Profile keys: {list(profile.keys())}")
        store_profile(conn, profile)
        cached = profile

    consumed = {h["title"] for h in history}
    print(f"Generating recommendations (excluding {len(consumed)} consumed titles)…")
    recs = generate_recommendations(client, cached, consumed)
    print(f"Got {len(recs)} book/film/TV recommendations")
    print("Generating music/podcast/comics recommendations…")
    recs_extended = generate_recommendations_extended(client, cached, consumed)
    print(f"Got {len(recs_extended)} music/podcast/comics recommendations")
    store_recommendations(conn, recs + recs_extended)

    if not (args.refresh or args.refresh_recs):
        save_cache(cache_key, cached, recs)

    print("Done. Run build_dashboard.py to render.")


if __name__ == "__main__":
    main()
