#!/usr/bin/env python3
"""
enrich_for_web.py — Build story objects for films, books, directors and artists.

Fetches from TMDB (films/TV/directors), OpenLibrary (books), Last.fm (artists),
then upserts into the Supabase `enrichment` table.

Run: python3 scripts/enrich_for_web.py [--limit N] [--type film|book|director|artist] [--force]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from db import get_conn

# ── Config ────────────────────────────────────────────────────────────────────

TMDB_KEY  = (Path("~/.config/tmdb/api_key").expanduser().read_text().strip()
             if Path("~/.config/tmdb/api_key").expanduser().exists() else "")
LASTFM_KEY = (Path("~/.config/lastfm/api_key").expanduser().read_text().strip()
              if Path("~/.config/lastfm/api_key").expanduser().exists() else "")

SUPABASE_URL = "https://yuvjqdxigsusmplzdpvf.supabase.co"
SUPABASE_KEY = (Path("~/.config/observatory/config.env").expanduser().read_text()
                if Path("~/.config/observatory/config.env").expanduser().exists() else "")
# Extract service role key from config.env
_match = re.search(r"SUPABASE_SERVICE_ROLE_KEY=(.+)", SUPABASE_KEY)
SUPABASE_SERVICE_KEY = _match.group(1).strip() if _match else ""

TMDB_BASE   = "https://api.themoviedb.org/3"
TMDB_IMG    = "https://image.tmdb.org/t/p"
LASTFM_BASE = "http://ws.audioscrobbler.com/2.0/"
OL_BASE     = "https://openlibrary.org"

JUSTWATCH_SEARCH = "https://www.justwatch.com/de/Suche?q={}"
LETTERBOXD_SEARCH = "https://letterboxd.com/search/films/{}/"
GOODREADS_SEARCH = "https://www.goodreads.com/search?q={}"
IMDB_TITLE = "https://www.imdb.com/title/{}/"
IMDB_NAME  = "https://www.imdb.com/name/{}/"

# ── Supabase helpers ──────────────────────────────────────────────────────────

def supa_headers():
    return {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates",
    }

def upsert_enrichment(item_key: str, media_type: str, title: str, data: dict) -> bool:
    payload = {
        "item_key": item_key,
        "media_type": media_type,
        "title": title,
        "data": data,
    }
    r = requests.post(
        f"{SUPABASE_URL}/rest/v1/enrichment",
        headers=supa_headers(),
        json=payload,
        timeout=15,
    )
    if r.status_code in (200, 201):
        return True
    print(f"  ✗ Supabase upsert failed {r.status_code}: {r.text[:120]}")
    return False

def already_enriched(item_key: str) -> bool:
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/enrichment?item_key=eq.{requests.utils.quote(item_key)}&select=item_key",
        headers=supa_headers(),
        timeout=10,
    )
    return r.status_code == 200 and len(r.json()) > 0

# ── TMDB helpers ──────────────────────────────────────────────────────────────

def tmdb_get(path: str, params: dict | None = None) -> dict:
    if not TMDB_KEY:
        return {}
    p = {"api_key": TMDB_KEY, "language": "en-US", **(params or {})}
    r = requests.get(f"{TMDB_BASE}{path}", params=p, timeout=10)
    if r.status_code == 429:
        time.sleep(5)
        return tmdb_get(path, params)
    return r.json() if r.ok else {}

def imdb_to_tmdb(imdb_id: str, media_type: str) -> dict:
    """Find TMDB record from IMDB id."""
    result = tmdb_get(f"/find/{imdb_id}", {"external_source": "imdb_id"})
    if media_type in ("film", "movie"):
        hits = result.get("movie_results", [])
    else:
        hits = result.get("tv_results", [])
    return hits[0] if hits else {}

def streaming_de(tmdb_id: int, media_type: str) -> dict:
    """JustWatch streaming availability for Germany via TMDB."""
    path = f"/movie/{tmdb_id}/watch/providers" if media_type in ("film","movie") else f"/tv/{tmdb_id}/watch/providers"
    data = tmdb_get(path)
    de = data.get("results", {}).get("DE", {})
    return {
        "flatrate": [p["provider_name"] for p in de.get("flatrate", [])],
        "rent":     [p["provider_name"] for p in de.get("rent", [])],
        "buy":      [p["provider_name"] for p in de.get("buy", [])],
        "justwatch_url": de.get("link", JUSTWATCH_SEARCH.format("")),
    }

def tmdb_person(person_id: int) -> dict:
    return tmdb_get(f"/person/{person_id}", {"append_to_response": "movie_credits"})

def tmdb_movie_detail(tmdb_id: int) -> dict:
    return tmdb_get(f"/movie/{tmdb_id}", {
        "append_to_response": "credits,watch/providers,images",
    })

def tmdb_tv_detail(tmdb_id: int) -> dict:
    return tmdb_get(f"/tv/{tmdb_id}", {
        "append_to_response": "credits,watch/providers",
    })

def tmdb_search_person(name: str) -> dict:
    results = tmdb_get("/search/person", {"query": name})
    hits = results.get("results", [])
    return hits[0] if hits else {}

# ── Last.fm helpers ───────────────────────────────────────────────────────────

def lastfm_get(method: str, params: dict) -> dict:
    if not LASTFM_KEY:
        return {}
    p = {"method": method, "api_key": LASTFM_KEY, "format": "json", **params}
    r = requests.get(LASTFM_BASE, params=p, timeout=10)
    return r.json() if r.ok else {}

def lastfm_artist(name: str) -> dict:
    data = lastfm_get("artist.getinfo", {"artist": name})
    a = data.get("artist", {})
    if not a:
        return {}
    bio = a.get("bio", {}).get("summary", "")
    # Strip Last.fm HTML links
    bio = re.sub(r'<a href="[^"]*"[^>]*>([^<]*)</a>', r'\1', bio)
    bio = re.sub(r'<[^>]+>', '', bio).strip()
    # First 3 sentences
    sentences = re.split(r'(?<=[.!?])\s+', bio)
    bio_short = " ".join(sentences[:3])
    tags = [t["name"] for t in a.get("tags", {}).get("tag", [])[:5]]
    similar = [s["name"] for s in a.get("similar", {}).get("artist", [])[:5]]
    return {
        "bio": bio_short,
        "tags": tags,
        "similar": similar,
        "listeners": a.get("stats", {}).get("listeners", ""),
        "url": a.get("url", ""),
    }

# ── OpenLibrary helpers ───────────────────────────────────────────────────────

def ol_book(goodreads_id: str | None, title: str, author: str | None) -> dict:
    # Try OpenLibrary search
    q = f"{title} {author or ''}".strip()
    r = requests.get(f"{OL_BASE}/search.json", params={"q": q, "limit": 1}, timeout=10)
    if not r.ok:
        return {}
    docs = r.json().get("docs", [])
    if not docs:
        return {}
    doc = docs[0]
    ol_key = doc.get("key", "")
    cover_id = doc.get("cover_i")
    cover = f"https://covers.openlibrary.org/b/id/{cover_id}-L.jpg" if cover_id else ""

    # Get description
    desc = ""
    if ol_key:
        wr = requests.get(f"{OL_BASE}{ol_key}.json", timeout=8)
        if wr.ok:
            wd = wr.json()
            raw = wd.get("description", "")
            if isinstance(raw, dict):
                raw = raw.get("value", "")
            desc = raw[:500] if raw else ""

    # Author info
    author_bio = ""
    author_photo = ""
    author_ids = doc.get("author_key", [])
    if author_ids:
        ar = requests.get(f"{OL_BASE}/authors/{author_ids[0]}.json", timeout=8)
        if ar.ok:
            ad = ar.json()
            raw_bio = ad.get("bio", "")
            if isinstance(raw_bio, dict):
                raw_bio = raw_bio.get("value", "")
            author_bio = raw_bio[:300] if raw_bio else ""
            photo_ids = ad.get("photos", [])
            if photo_ids and photo_ids[0] > 0:
                author_photo = f"https://covers.openlibrary.org/a/id/{photo_ids[0]}-M.jpg"

    return {
        "cover_url": cover,
        "description": desc,
        "author_bio": author_bio,
        "author_photo": author_photo,
        "ol_key": ol_key,
        "pages": doc.get("number_of_pages_median", 0),
        "first_published": doc.get("first_publish_year"),
        "subjects": doc.get("subject", [])[:8],
        "goodreads_url": f"https://www.goodreads.com/search?q={requests.utils.quote(title)}",
        "ol_url": f"https://openlibrary.org{ol_key}" if ol_key else "",
    }

# ── Enrichment functions ──────────────────────────────────────────────────────

def enrich_film(row: dict, user_ratings: dict, force: bool = False) -> bool:
    """Build story object for a film or TV show."""
    item_key = f"{row['media_type']}:{row['id']}"
    if not force and already_enriched(item_key):
        return False

    imdb_id = row["source_id"] if row["source"] == "imdb" else None
    tmdb_id = None
    tmdb_data = {}
    media_type = row["media_type"]

    if imdb_id:
        found = imdb_to_tmdb(imdb_id, media_type)
        tmdb_id = found.get("id")
        time.sleep(0.26)

    # Fall back to title search for non-IMDB sources
    if not tmdb_id:
        endpoint = "/search/movie" if media_type in ("film", "movie") else "/search/tv"
        results = tmdb_get(endpoint, {"query": row["title"], "year": row.get("year", "")})
        hits = results.get("results", [])
        if hits:
            tmdb_id = hits[0]["id"]
        time.sleep(0.26)

    if tmdb_id:
        if media_type in ("film", "movie"):
            tmdb_data = tmdb_movie_detail(tmdb_id)
        else:
            tmdb_data = tmdb_tv_detail(tmdb_id)
        time.sleep(0.26)  # ~4 req/s to stay under TMDB limit

    # Poster + backdrop
    poster_path = tmdb_data.get("poster_path", "")
    backdrop_path = tmdb_data.get("backdrop_path", "")
    poster = f"{TMDB_IMG}/w500{poster_path}" if poster_path else ""
    backdrop = f"{TMDB_IMG}/w1280{backdrop_path}" if backdrop_path else ""

    # Cast (top 5)
    credits = tmdb_data.get("credits", {})
    cast = [
        {
            "name": c["name"],
            "character": c.get("character", ""),
            "profile": f"{TMDB_IMG}/w185{c['profile_path']}" if c.get("profile_path") else "",
        }
        for c in credits.get("cast", [])[:5]
    ]

    # Crew — director(s)
    directors = [
        c["name"] for c in credits.get("crew", []) if c.get("job") == "Director"
    ]
    if not directors and row.get("director"):
        directors = [d.strip() for d in row["director"].split(",")]

    # Streaming DE
    streaming = streaming_de(tmdb_id, media_type) if tmdb_id else {
        "flatrate": [], "rent": [], "buy": [],
        "justwatch_url": JUSTWATCH_SEARCH.format(requests.utils.quote(row["title"])),
    }

    # Your ratings history
    ur = user_ratings.get(row["id"], {})

    story = {
        "title": row["title"],
        "year": row.get("year") or tmdb_data.get("release_date", "")[:4],
        "media_type": media_type,
        "tagline": tmdb_data.get("tagline", ""),
        "overview": tmdb_data.get("overview", ""),
        "poster_url": poster,
        "backdrop_url": backdrop,
        "runtime_min": tmdb_data.get("runtime") or row.get("runtime_min"),
        "genres": [g["name"] for g in tmdb_data.get("genres", [])] or
                  json.loads(row["genres"] or "[]"),
        "vote_average": tmdb_data.get("vote_average"),
        "cast": cast,
        "directors": directors,
        "imdb_id": imdb_id or tmdb_data.get("imdb_id"),
        "tmdb_id": tmdb_id,
        "streaming": streaming,
        # Your personal data
        "your_rating": ur.get("rating"),
        "date_watched": ur.get("date_completed"),
        # Linkouts
        "links": {
            "imdb": IMDB_TITLE.format(imdb_id) if imdb_id else "",
            "justwatch": streaming.get("justwatch_url", ""),
            "letterboxd": LETTERBOXD_SEARCH.format(requests.utils.quote(row["title"])),
            "tmdb": f"https://www.themoviedb.org/{'movie' if media_type in ('film','movie') else 'tv'}/{tmdb_id}" if tmdb_id else "",
        },
    }

    ok = upsert_enrichment(item_key, media_type, row["title"], story)
    print(f"  {'✓' if ok else '✗'} {row['title']} ({media_type})")
    return ok


def enrich_book(row: dict, user_ratings: dict, force: bool = False) -> bool:
    """Build story object for a book."""
    item_key = f"book:{row['id']}"
    if not force and already_enriched(item_key):
        return False

    ol = ol_book(row.get("source_id"), row["title"], row.get("author"))
    time.sleep(0.5)

    ur = user_ratings.get(row["id"], {})

    story = {
        "title": row["title"],
        "author": row.get("author", ""),
        "year": row.get("year"),
        "media_type": "book",
        "series_name": row.get("series_name"),
        "series_pos": row.get("series_pos"),
        "page_count": row.get("page_count") or ol.get("pages"),
        "cover_url": ol.get("cover_url", ""),
        "description": ol.get("description", ""),
        "subjects": ol.get("subjects", []),
        "author_bio": ol.get("author_bio", ""),
        "author_photo": ol.get("author_photo", ""),
        "genres": json.loads(row.get("genres") or "[]"),
        # Your personal data
        "your_rating": ur.get("rating"),
        "date_read": ur.get("date_completed"),
        "shelf": ur.get("shelf"),
        # Linkouts
        "links": {
            "goodreads": f"https://www.goodreads.com/search?q={requests.utils.quote(row['title'])}",
            "openlibrary": ol.get("ol_url", ""),
            "audible": f"https://www.audible.de/search?keywords={requests.utils.quote(row['title'])}",
        },
    }

    ok = upsert_enrichment(item_key, "book", row["title"], story)
    print(f"  {'✓' if ok else '✗'} {row['title']} (book)")
    return ok


def enrich_director(name: str, film_history: list, force: bool = False) -> bool:
    """Build story object for a director."""
    item_key = f"director:{name}"
    if not force and already_enriched(item_key):
        return False

    # Find on TMDB
    person_hit = tmdb_search_person(name)
    time.sleep(0.26)
    person_data = {}
    if person_hit:
        person_data = tmdb_person(person_hit["id"])
        time.sleep(0.26)

    profile_path = person_data.get("profile_path") or person_hit.get("profile_path", "")
    photo = f"{TMDB_IMG}/w185{profile_path}" if profile_path else ""

    # Bio — first 3 sentences
    bio = person_data.get("biography", "")
    sentences = re.split(r'(?<=[.!?])\s+', bio)
    bio_short = " ".join(sentences[:3]) if sentences else ""

    # Their films in your history
    your_films = sorted(film_history, key=lambda x: x["rating"] or 0, reverse=True)

    # Known for (TMDB top credits)
    known_for = []
    for c in person_data.get("movie_credits", {}).get("cast", [])[:5]:
        known_for.append({"title": c["title"], "year": str(c.get("release_date", ""))[:4]})

    story = {
        "name": name,
        "media_type": "director",
        "photo_url": photo,
        "bio": bio_short,
        "birthday": person_data.get("birthday", ""),
        "place_of_birth": person_data.get("place_of_birth", ""),
        "tmdb_id": person_data.get("id"),
        "known_for": known_for,
        # Your watch history for this director
        "your_films": [
            {
                "title": f["title"],
                "year": f.get("year"),
                "rating": f.get("rating"),
                "date_watched": f.get("date_completed"),
            }
            for f in your_films
        ],
        "your_count": len(your_films),
        "your_avg": round(sum(f["rating"] for f in your_films if f["rating"]) /
                          max(1, sum(1 for f in your_films if f["rating"])), 1),
        # Linkouts
        "links": {
            "imdb": IMDB_NAME.format(person_data.get("imdb_id", "")) if person_data.get("imdb_id") else "",
            "tmdb": f"https://www.themoviedb.org/person/{person_data.get('id')}" if person_data.get("id") else "",
            "letterboxd": f"https://letterboxd.com/director/{name.lower().replace(' ', '-')}/",
        },
    }

    ok = upsert_enrichment(item_key, "director", name, story)
    print(f"  {'✓' if ok else '✗'} {name} (director)")
    return ok


def enrich_artist(name: str, spotify_stats: dict, force: bool = False) -> bool:
    """Build story object for a music artist."""
    item_key = f"artist:{name}"
    if not force and already_enriched(item_key):
        return False

    lfm = lastfm_artist(name)
    time.sleep(0.2)

    story = {
        "name": name,
        "media_type": "artist",
        "bio": lfm.get("bio", ""),
        "tags": lfm.get("tags", []),
        "similar": lfm.get("similar", []),
        "listeners": lfm.get("listeners", ""),
        "lastfm_url": lfm.get("url", ""),
        # Your Spotify data
        "your_plays": spotify_stats.get("plays", 0),
        "your_hours": round(spotify_stats.get("ms", 0) / 3_600_000, 1),
        "your_top_tracks": spotify_stats.get("top_tracks", []),
        "your_top_albums": spotify_stats.get("top_albums", []),
        "your_years_active": spotify_stats.get("years", []),
        # Linkouts
        "links": {
            "lastfm": lfm.get("url", f"https://www.last.fm/music/{requests.utils.quote(name)}"),
            "spotify": f"https://open.spotify.com/search/{requests.utils.quote(name)}",
        },
    }

    ok = upsert_enrichment(item_key, "artist", name, story)
    print(f"  {'✓' if ok else '✗'} {name} (artist)")
    return ok


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Enrich culture data for the web dashboard")
    parser.add_argument("--type", choices=["film", "book", "director", "artist", "all"],
                        default="all", help="What to enrich")
    parser.add_argument("--limit", type=int, default=0, help="Max items per type (0=all)")
    parser.add_argument("--force", action="store_true", help="Re-enrich even if already done")
    args = parser.parse_args()

    if not SUPABASE_SERVICE_KEY:
        print("✗ SUPABASE_SERVICE_ROLE_KEY not found in ~/.config/observatory/config.env")
        sys.exit(1)

    conn = get_conn()
    do_all = args.type == "all"

    # ── User ratings lookup ────────────────────────────────────────────────────
    user_ratings = {}
    for r in conn.execute(
        "SELECT media_id, rating, date_completed, shelf FROM user_interactions "
        "WHERE rating IS NOT NULL OR shelf IS NOT NULL ORDER BY id DESC"
    ).fetchall():
        if r["media_id"] not in user_ratings:
            user_ratings[r["media_id"]] = dict(r)

    # ── Films & TV ────────────────────────────────────────────────────────────
    if do_all or args.type == "film":
        print(f"\n── Films & TV ──────────────────────────────")
        if not TMDB_KEY:
            print("  ⚠  No TMDB key — skipping films")
        else:
            rows = conn.execute("""
                SELECT DISTINCT m.id, m.title, m.media_type, m.year, m.source, m.source_id,
                       m.genres, m.runtime_min, m.director
                FROM media_items m JOIN user_interactions ui ON ui.media_id=m.id
                WHERE m.media_type IN ('film','movie','tv_show')
                  AND ui.interaction IN ('completed','rated')
                ORDER BY CASE m.source WHEN 'imdb' THEN 0 ELSE 1 END,
                         ui.date_completed DESC NULLS LAST
            """).fetchall()
            if args.limit:
                rows = rows[:args.limit]
            for row in rows:
                enrich_film(dict(row), user_ratings, args.force)

    # ── Books ─────────────────────────────────────────────────────────────────
    if do_all or args.type == "book":
        print(f"\n── Books ───────────────────────────────────")
        rows = conn.execute("""
            SELECT m.id, m.title, m.author, m.year, m.source, m.source_id,
                   m.genres, m.page_count, m.series_name, m.series_pos
            FROM media_items m JOIN user_interactions ui ON ui.media_id=m.id
            WHERE m.media_type='book' AND ui.shelf IN ('read','currently-reading')
            ORDER BY ui.date_completed DESC NULLS LAST
        """).fetchall()
        if args.limit:
            rows = rows[:args.limit]
        for row in rows:
            enrich_book(dict(row), user_ratings, args.force)

    # ── Directors ─────────────────────────────────────────────────────────────
    if do_all or args.type == "director":
        print(f"\n── Directors ───────────────────────────────")
        if not TMDB_KEY:
            print("  ⚠  No TMDB key — skipping directors")
        else:
            dir_rows = conn.execute("""
                SELECT m.director, m.id, m.title, m.year,
                       ui.rating, ui.date_completed
                FROM media_items m JOIN user_interactions ui ON ui.media_id=m.id
                WHERE m.director IS NOT NULL AND m.media_type IN ('film','movie')
                  AND ui.rating IS NOT NULL AND m.director NOT LIKE '%,%'
                ORDER BY m.director
            """).fetchall()
            # Group by director
            directors: dict[str, list] = {}
            for r in dir_rows:
                directors.setdefault(r["director"], []).append(dict(r))
            # Only enrich directors with 2+ rated films
            directors = {k: v for k, v in directors.items() if len(v) >= 2}
            items = list(directors.items())
            if args.limit:
                items = items[:args.limit]
            for name, films in items:
                enrich_director(name, films, args.force)

    # ── Artists ───────────────────────────────────────────────────────────────
    if do_all or args.type == "artist":
        print(f"\n── Artists ─────────────────────────────────")
        if not LASTFM_KEY:
            print("  ⚠  No Last.fm key — skipping artists")
        else:
            # Top artists from Spotify (exclude white noise)
            SKIP = {"sleep-o-phant", "Richards Kindermusikladen"}
            artist_rows = conn.execute("""
                SELECT artist,
                       count(*) plays,
                       sum(ms_played) ms
                FROM spotify_plays
                WHERE artist IS NOT NULL
                GROUP BY artist
                HAVING count(*) >= 20
                ORDER BY plays DESC
            """).fetchall()
            items = [r for r in artist_rows if r["artist"] not in SKIP]
            if args.limit:
                items = items[:args.limit]

            # Build per-artist Spotify stats
            for row in items:
                name = row["artist"]
                # Top tracks
                tracks = conn.execute("""
                    SELECT track, count(*) cnt FROM spotify_plays
                    WHERE artist=? AND track IS NOT NULL
                    GROUP BY track ORDER BY cnt DESC LIMIT 5
                """, (name,)).fetchall()
                # Top albums
                albums = conn.execute("""
                    SELECT album, count(*) cnt FROM spotify_plays
                    WHERE artist=? AND album IS NOT NULL
                    GROUP BY album ORDER BY cnt DESC LIMIT 3
                """, (name,)).fetchall()
                # Years active in your listening
                years = conn.execute("""
                    SELECT substr(ended_at,1,4) yr, count(*) cnt
                    FROM spotify_plays WHERE artist=? AND ended_at IS NOT NULL
                    GROUP BY yr ORDER BY cnt DESC LIMIT 5
                """, (name,)).fetchall()
                stats = {
                    "plays": row["plays"],
                    "ms": row["ms"],
                    "top_tracks": [{"title": t["track"], "plays": t["cnt"]} for t in tracks],
                    "top_albums": [{"title": a["album"], "plays": a["cnt"]} for a in albums],
                    "years": [{"year": y["yr"], "plays": y["cnt"]} for y in years],
                }
                enrich_artist(name, stats, args.force)

    print("\n✓ Enrichment complete.")


if __name__ == "__main__":
    main()
