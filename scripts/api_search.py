"""Async search abstraction over TMDB and Open Library."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

import httpx

TMDB_KEY_FILE = Path.home() / ".config" / "tmdb" / "api_key"
TMDB_BASE = "https://api.themoviedb.org/3"
TMDB_IMG = "https://image.tmdb.org/t/p/w185"
OL_BASE = "https://openlibrary.org"
OL_COVER = "https://covers.openlibrary.org/b/id/{}-M.jpg"


def _tmdb_key() -> str:
    key = os.environ.get("TMDB_API_KEY", "")
    if not key and TMDB_KEY_FILE.exists():
        key = TMDB_KEY_FILE.read_text().strip()
    return key


def _tmdb_genres(genre_ids: list[int], genre_map: dict[int, str]) -> list[str]:
    return [genre_map[g] for g in genre_ids if g in genre_map]


async def _fetch_tmdb_genre_map(client: httpx.AsyncClient, api_key: str) -> dict[int, str]:
    results: dict[int, str] = {}
    for kind in ("movie", "tv"):
        r = await client.get(f"{TMDB_BASE}/genre/{kind}/list", params={"api_key": api_key})
        if r.status_code == 200:
            for g in r.json().get("genres", []):
                results[g["id"]] = g["name"]
    return results


async def _fetch_tmdb_imdb_id(client: httpx.AsyncClient, api_key: str,
                               media_type: str, tmdb_id: int) -> str | None:
    kind = "movie" if media_type == "film" else "tv"
    r = await client.get(f"{TMDB_BASE}/{kind}/{tmdb_id}/external_ids",
                         params={"api_key": api_key})
    if r.status_code == 200:
        return r.json().get("imdb_id")
    return None


async def _search_tmdb(client: httpx.AsyncClient, api_key: str, query: str,
                        media_type: str, existing_ids: set[str]) -> list[dict]:
    if not api_key:
        return []

    genre_map = await _fetch_tmdb_genre_map(client, api_key)
    params: dict[str, Any] = {"api_key": api_key, "query": query, "page": 1}

    if media_type == "film":
        endpoint, kinds = f"{TMDB_BASE}/search/movie", {"movie"}
    elif media_type == "tv":
        endpoint, kinds = f"{TMDB_BASE}/search/tv", {"tv"}
    else:
        endpoint, kinds = f"{TMDB_BASE}/search/multi", {"movie", "tv"}

    r = await client.get(endpoint, params=params)
    if r.status_code != 200:
        return []

    items = r.json().get("results", [])[:6]
    results = []
    for it in items:
        kind = it.get("media_type", "movie" if media_type == "film" else
                       "tv" if media_type == "tv" else it.get("media_type", "movie"))
        if kind not in kinds:
            continue
        tmdb_id = it["id"]
        mt = "film" if kind == "movie" else "tv_show"
        source_id = f"{kind}:{tmdb_id}"
        db_id = f"tmdb:{source_id}"

        if db_id in existing_ids:
            continue

        imdb_id = await _fetch_tmdb_imdb_id(client, api_key, mt, tmdb_id)

        title = it.get("title") or it.get("name", "")
        year_str = (it.get("release_date") or it.get("first_air_date") or "")[:4]
        year = int(year_str) if year_str.isdigit() else None
        genres = _tmdb_genres(it.get("genre_ids", []), genre_map)
        poster = it.get("poster_path")
        cover_url = f"{TMDB_IMG}{poster}" if poster else ""
        subtitle = f"{year}" if year else ""

        results.append({
            "id": db_id,
            "source": "tmdb",
            "source_id": source_id,
            "media_type": mt,
            "title": title,
            "subtitle": subtitle,
            "author": None,
            "director": None,
            "year": year,
            "genres": genres,
            "description": it.get("overview", ""),
            "cover_url": cover_url,
            "imdb_id": imdb_id,
            "watchlist": False,
            "rating": None,
        })
    return results


async def _search_openlibrary(client: httpx.AsyncClient, query: str,
                               existing_ids: set[str]) -> list[dict]:
    params = {"q": query, "limit": 6, "fields": "key,title,author_name,first_publish_year,subject,cover_i,ia"}
    r = await client.get(f"{OL_BASE}/search.json", params=params)
    if r.status_code != 200:
        return []

    results = []
    for doc in r.json().get("docs", [])[:6]:
        work_key = doc.get("key", "")
        source_id = work_key.replace("/works/", "") if "/works/" in work_key else work_key.strip("/")
        db_id = f"ol:{source_id}"

        if db_id in existing_ids:
            continue

        title = doc.get("title", "")
        authors = doc.get("author_name") or []
        author = authors[0] if authors else None
        year = doc.get("first_publish_year")
        subjects = (doc.get("subject") or [])[:4]
        cover_id = doc.get("cover_i")
        cover_url = OL_COVER.format(cover_id) if cover_id else ""
        subtitle = f"{author} · {year}" if author and year else (author or str(year or ""))

        results.append({
            "id": db_id,
            "source": "openlibrary",
            "source_id": source_id,
            "media_type": "book",
            "title": title,
            "subtitle": subtitle,
            "author": author,
            "director": None,
            "year": year,
            "genres": subjects,
            "description": "",
            "cover_url": cover_url,
            "imdb_id": None,
            "watchlist": False,
            "rating": None,
        })
    return results


async def _search_musicbrainz(client: httpx.AsyncClient, query: str,
                              existing_ids: set[str]) -> list[dict]:
    headers = {"User-Agent": "EntertainmentDashboard/1.0 (personal project)"}
    params = {"query": query, "fmt": "json", "limit": 8}
    try:
        r = await client.get("https://musicbrainz.org/ws/2/artist", params=params, headers=headers)
        if r.status_code != 200:
            return []
        items = []
        for it in r.json().get("artists", [])[:6]:
            mb_id = it.get("id", "")
            db_id = f"mb:artist:{mb_id}"
            if db_id in existing_ids:
                continue
            name = it.get("name", "")
            tags = [t["name"] for t in (it.get("tags") or [])[:3]]
            items.append({
                "id": db_id,
                "source": "musicbrainz",
                "source_id": mb_id,
                "media_type": "music",
                "title": name,
                "subtitle": " · ".join(tags) if tags else it.get("disambiguation", ""),
                "author": None,
                "director": None,
                "year": None,
                "genres": tags,
                "description": it.get("disambiguation", ""),
                "cover_url": "",
                "imdb_id": None,
                "watchlist": False,
                "rating": None,
            })
        return items
    except Exception:
        return []


async def _search_itunes_podcast(client: httpx.AsyncClient, query: str,
                                  existing_ids: set[str]) -> list[dict]:
    try:
        r = await client.get(
            "https://itunes.apple.com/search",
            params={"term": query, "media": "podcast", "entity": "podcast", "limit": 8}
        )
        if r.status_code != 200:
            return []
        items = []
        for it in r.json().get("results", [])[:6]:
            pod_id = str(it.get("collectionId", ""))
            db_id = f"itunes:podcast:{pod_id}"
            if db_id in existing_ids:
                continue
            title = it.get("collectionName", "")
            artist = it.get("artistName", "")
            genres = it.get("genres", [])
            cover = it.get("artworkUrl100", "").replace("100x100", "300x300")
            episode_count = it.get("trackCount", 0)
            items.append({
                "id": db_id,
                "source": "itunes",
                "source_id": pod_id,
                "media_type": "podcast",
                "title": title,
                "subtitle": artist + (f" · {episode_count} ep." if episode_count else ""),
                "author": artist,
                "director": None,
                "year": None,
                "genres": genres[:3],
                "description": "",
                "cover_url": cover,
                "imdb_id": None,
                "watchlist": False,
                "rating": None,
            })
        return items
    except Exception:
        return []


async def search(query: str, media_type: str = "all",
                 existing_ids: set[str] | None = None) -> list[dict]:
    """Fan out to TMDB, Open Library, MusicBrainz, and iTunes in parallel."""
    if existing_ids is None:
        existing_ids = set()

    api_key = _tmdb_key()
    timeout = httpx.Timeout(8.0)

    async with httpx.AsyncClient(timeout=timeout) as client:
        tasks = []
        if media_type in ("all", "film", "tv"):
            tasks.append(_search_tmdb(client, api_key, query, media_type, existing_ids))
        if media_type in ("all", "book"):
            tasks.append(_search_openlibrary(client, query, existing_ids))
        if media_type in ("music",):
            tasks.append(_search_musicbrainz(client, query, existing_ids))
        if media_type in ("podcast",):
            tasks.append(_search_itunes_podcast(client, query, existing_ids))

        results_nested = await asyncio.gather(*tasks, return_exceptions=True)

    combined: list[dict] = []
    for chunk in results_nested:
        if isinstance(chunk, list):
            combined.extend(chunk)
    return combined
