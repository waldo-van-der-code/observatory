"""FastAPI server for entertainment dashboard — search, watchlist, ratings."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "scripts"))

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from api_search import _tmdb_key, search
from db import get_conn, get_watchlist, get_or_create_item, init_db

DASHBOARD = Path(__file__).parent / "dashboard.html"
BRAIN_HTML = Path(__file__).parent / "brain.html"
STATIC_DIR = Path(__file__).parent / "static"
BRAIN_DATA = Path(__file__).parent / "data" / "processed" / "brain_data.json"
BRAIN_ART  = Path(__file__).parent / "data" / "cache" / "brain_art"

app = FastAPI(title="Entertainment Center")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Allow file:// pages to call the API (origin is "null" for local files)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup():
    with get_conn() as conn:
        init_db(conn)
    if not _tmdb_key():
        print(
            "\n⚠️  TMDB_API_KEY not found. Film/TV search will be disabled.\n"
            "   Get a free key at https://www.themoviedb.org/settings/api\n"
            "   Then: mkdir -p ~/.config/tmdb && echo 'YOUR_KEY' > ~/.config/tmdb/api_key\n"
        )


# ── Pages ─────────────────────────────────────────────────────────────────────

@app.get("/", response_class=FileResponse)
def index():
    return FileResponse(DASHBOARD, media_type="text/html")


# ── Search ────────────────────────────────────────────────────────────────────

def _get_user_state(conn) -> tuple[set[str], dict[str, float | None]]:
    """Return (watchlist_ids, {item_id: rating}) for all search-added items."""
    wl_rows = get_watchlist(conn)
    wl_ids = {r["id"] for r in wl_rows}
    # Ratings stored separately — fetch all rated search items
    rated_rows = conn.execute("""
        SELECT m.id, ui.rating FROM media_items m
        JOIN user_interactions ui ON ui.media_id = m.id
        WHERE ui.rating IS NOT NULL AND m.source IN ('tmdb', 'openlibrary')
    """).fetchall()
    ratings = {r["id"]: r["rating"] for r in rated_rows}
    return wl_ids, ratings


@app.get("/api/search")
async def api_search(
    q: str = Query(..., min_length=1),
    type: str = Query("all"),
):
    if type not in ("all", "film", "tv", "book"):
        raise HTTPException(400, "type must be all | film | tv | book")

    conn = get_conn()
    try:
        wl_ids, ratings = _get_user_state(conn)
    finally:
        conn.close()

    results = await search(q, media_type=type, existing_ids=set())

    for item in results:
        item["watchlist"] = item["id"] in wl_ids
        item["rating"] = ratings.get(item["id"])

    return JSONResponse(results)


# ── Write: upsert item ────────────────────────────────────────────────────────

class ItemIn(BaseModel):
    id: str = ""          # canonical search ID e.g. "ol:OL20743965W" or "tmdb:movie:123"
    source: str
    source_id: str
    media_type: str
    title: str
    subtitle: str = ""
    author: str | None = None
    director: str | None = None
    year: int | None = None
    genres: list[str] = []
    description: str = ""
    cover_url: str = ""
    imdb_id: str | None = None


@app.post("/api/items")
def api_upsert_item(body: ItemIn):
    conn = get_conn()
    try:
        db_id = get_or_create_item(conn, body.model_dump())
    finally:
        conn.close()
    return {"item_id": db_id}


# ── Write: record interaction ─────────────────────────────────────────────────

class InteractionIn(BaseModel):
    item_id: str
    interaction_type: str   # "shelf" | "rating"
    value: str              # "to-watch" | "to-read" | "1".."5"


@app.post("/api/interactions")
def api_interaction(body: InteractionIn):
    if body.interaction_type not in ("shelf", "rating"):
        raise HTTPException(400, "interaction_type must be shelf | rating")

    conn = get_conn()
    try:
        now = datetime.now(timezone.utc).isoformat()

        if body.interaction_type == "shelf":
            # Remove any existing shelf interaction for this item first
            conn.execute(
                "DELETE FROM user_interactions WHERE media_id=? AND shelf IS NOT NULL",
                (body.item_id,),
            )
            conn.execute(
                "INSERT INTO user_interactions (media_id, interaction, shelf, date_added) "
                "VALUES (?,?,?,?)",
                (body.item_id, "watchlist", body.value, now),
            )
        else:
            rating = float(body.value)
            conn.execute(
                "DELETE FROM user_interactions WHERE media_id=? AND rating IS NOT NULL",
                (body.item_id,),
            )
            conn.execute(
                "INSERT INTO user_interactions (media_id, interaction, rating, date_added) "
                "VALUES (?,?,?,?)",
                (body.item_id, "rated", rating, now),
            )
        conn.commit()
    finally:
        conn.close()
    return {"ok": True}


# ── Read: current watchlist state ─────────────────────────────────────────────

@app.get("/api/watchlist")
def api_watchlist():
    conn = get_conn()
    try:
        items = get_watchlist(conn)
    finally:
        conn.close()
    return JSONResponse(items)


# ── Remove from watchlist ─────────────────────────────────────────────────────

@app.delete("/api/watchlist/{item_id:path}")
def api_remove_watchlist(item_id: str):
    conn = get_conn()
    try:
        conn.execute(
            "DELETE FROM user_interactions WHERE media_id=? AND shelf IS NOT NULL",
            (item_id,),
        )
        conn.commit()
    finally:
        conn.close()
    return {"ok": True}


# ── TMDB related (fast — no Claude) ──────────────────────────────────────────

@app.get("/api/related/{item_id:path}")
async def api_related(item_id: str):
    """Return TMDB similar titles for a film/TV item."""
    import httpx as _httpx

    api_key = _tmdb_key()
    if not api_key or not item_id.startswith("tmdb:"):
        return JSONResponse([])

    # item_id format: tmdb:movie:123 or tmdb:tv:123
    parts = item_id.split(":")
    if len(parts) != 3:
        return JSONResponse([])
    _, kind, tmdb_id = parts

    url = f"https://api.themoviedb.org/3/{kind}/{tmdb_id}/similar"
    async with _httpx.AsyncClient(timeout=6.0) as client:
        r = await client.get(url, params={"api_key": api_key})
    if r.status_code != 200:
        return JSONResponse([])

    items = []
    for it in r.json().get("results", [])[:5]:
        title = it.get("title") or it.get("name", "")
        year_str = (it.get("release_date") or it.get("first_air_date") or "")[:4]
        year = int(year_str) if year_str.isdigit() else None
        poster = it.get("poster_path")
        items.append({
            "id": f"tmdb:{kind}:{it['id']}",
            "title": title,
            "year": year,
            "cover_url": f"https://image.tmdb.org/t/p/w185{poster}" if poster else "",
            "media_type": "film" if kind == "movie" else "tv_show",
        })
    return JSONResponse(items)


# ── Detail page ───────────────────────────────────────────────────────────────

@app.get("/api/detail/{item_id:path}")
async def api_detail(item_id: str):
    import httpx as _httpx

    api_key = _tmdb_key()
    timeout = _httpx.Timeout(8.0)

    # ── TMDB film or TV ──────────────────────────────────────────────────────
    if item_id.startswith("tmdb:"):
        parts = item_id.split(":")
        if len(parts) != 3 or not api_key:
            return JSONResponse({"error": "invalid id or no api key"}, 400)
        _, kind, tmdb_id = parts

        async with _httpx.AsyncClient(timeout=timeout) as client:
            detail_r, credits_r, providers_r = await __import__("asyncio").gather(
                client.get(f"https://api.themoviedb.org/3/{kind}/{tmdb_id}",
                           params={"api_key": api_key}),
                client.get(f"https://api.themoviedb.org/3/{kind}/{tmdb_id}/credits",
                           params={"api_key": api_key}),
                client.get(f"https://api.themoviedb.org/3/{kind}/{tmdb_id}/watch/providers",
                           params={"api_key": api_key}),
            )

        if detail_r.status_code != 200:
            return JSONResponse({"error": "not found"}, 404)

        d = detail_r.json()
        credits = credits_r.json() if credits_r.status_code == 200 else {}
        providers_raw = providers_r.json() if providers_r.status_code == 200 else {}

        # cast top 5
        cast = [
            {"name": c["name"], "character": c.get("character", ""), "profile": f"https://image.tmdb.org/t/p/w92{c['profile_path']}" if c.get("profile_path") else ""}
            for c in credits.get("cast", [])[:5]
        ]
        # director(s)
        directors = [p["name"] for p in credits.get("crew", []) if p.get("job") == "Director"]
        # creators for TV
        if kind == "tv":
            directors = [c["name"] for c in d.get("created_by", [])] or directors

        # streaming in DE
        de = providers_raw.get("results", {}).get("DE", {})
        streaming = [p["provider_name"] for p in de.get("flatrate", [])]
        rent = [p["provider_name"] for p in de.get("rent", [])]
        buy  = [p["provider_name"] for p in de.get("buy", [])]
        jw_link = de.get("link", "")

        poster = d.get("poster_path")
        backdrop = d.get("backdrop_path")
        title = d.get("title") or d.get("name", "")
        year_str = (d.get("release_date") or d.get("first_air_date") or "")[:4]
        runtime = d.get("runtime") or (d.get("episode_run_time") or [None])[0]
        seasons = d.get("number_of_seasons")

        return JSONResponse({
            "id": item_id,
            "media_type": "film" if kind == "movie" else "tv_show",
            "title": title,
            "year": int(year_str) if year_str.isdigit() else None,
            "tagline": d.get("tagline", ""),
            "overview": d.get("overview", ""),
            "genres": [g["name"] for g in d.get("genres", [])],
            "vote_average": round(d.get("vote_average", 0), 1),
            "vote_count": d.get("vote_count", 0),
            "runtime_min": runtime,
            "seasons": seasons,
            "poster_url": f"https://image.tmdb.org/t/p/w342{poster}" if poster else "",
            "backdrop_url": f"https://image.tmdb.org/t/p/w780{backdrop}" if backdrop else "",
            "directors": directors,
            "cast": cast,
            "streaming_de": streaming,
            "rent_de": rent,
            "buy_de": buy,
            "justwatch_url": jw_link,
            "imdb_id": d.get("imdb_id", ""),
        })

    # ── Open Library book ─────────────────────────────────────────────────────
    if item_id.startswith("ol:"):
        work_id = item_id[3:]  # e.g. OL20743965W
        async with _httpx.AsyncClient(timeout=timeout) as client:
            work_r = await client.get(f"https://openlibrary.org/works/{work_id}.json")

        if work_r.status_code != 200:
            return JSONResponse({"error": "not found"}, 404)

        w = work_r.json()

        description = w.get("description", "")
        if isinstance(description, dict):
            description = description.get("value", "")

        subjects = (w.get("subjects") or [])[:8]
        authors_raw = w.get("authors") or []
        author_keys = [a.get("author", {}).get("key", "") for a in authors_raw]

        # Fetch first author name
        author_name = ""
        if author_keys:
            async with _httpx.AsyncClient(timeout=timeout) as client:
                ar = await client.get(f"https://openlibrary.org{author_keys[0]}.json")
            if ar.status_code == 200:
                author_name = ar.json().get("name", "")

        # Cover
        covers = w.get("covers") or []
        cover_url = f"https://covers.openlibrary.org/b/id/{covers[0]}-L.jpg" if covers else ""

        # First publish year
        first_year = w.get("first_publish_date", "")

        from urllib.parse import quote_plus
        goodreads = f"https://www.goodreads.com/search?q={quote_plus(w.get('title', ''))}"
        audible_q = quote_plus(f"{w.get('title', '')} {author_name}".strip())
        audible = f"https://www.audible.de/search?keywords={audible_q}"

        return JSONResponse({
            "id": item_id,
            "media_type": "book",
            "title": w.get("title", ""),
            "author": author_name,
            "year": first_year,
            "description": description,
            "subjects": subjects,
            "cover_url": cover_url,
            "goodreads_url": goodreads,
            "audible_url": audible,
            "ol_url": f"https://openlibrary.org/works/{work_id}",
        })

    return JSONResponse({"error": "unknown item type"}, 400)


# ── Brain routes ──────────────────────────────────────────────────────────────

@app.get("/brain", response_class=FileResponse)
def brain_page():
    return FileResponse(BRAIN_HTML, media_type="text/html")


@app.get("/api/brain/zones")
def api_brain_zones():
    """Rebuild brain_data.json and return all zone data."""
    import subprocess
    scripts_dir = Path(__file__).parent / "scripts"
    result = subprocess.run(
        ["python3", str(scripts_dir / "build_brain.py")],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        raise HTTPException(500, f"build_brain.py failed: {result.stderr[:500]}")
    data = json.loads(BRAIN_DATA.read_text())
    return JSONResponse(data)


@app.get("/api/brain/zone/{zone_id}/posters")
async def api_brain_posters(zone_id: str):
    """Return top_items for a zone with TMDB poster URLs resolved lazily."""
    import httpx as _httpx

    if not BRAIN_DATA.exists():
        raise HTTPException(503, "brain_data.json not built yet — call /api/brain/zones first")

    zones = json.loads(BRAIN_DATA.read_text())
    zone = next((z for z in zones if z["id"] == zone_id), None)
    if zone is None:
        raise HTTPException(404, f"Zone {zone_id!r} not found")

    api_key = _tmdb_key()
    items = zone.get("top_items", [])

    async def _resolve_poster(item: dict) -> dict:
        if item.get("poster_url"):
            return item
        src = item.get("source", "")
        src_id = item.get("source_id") or ""
        if api_key and src == "imdb" and src_id.startswith("tt"):
            try:
                async with _httpx.AsyncClient(timeout=5.0) as client:
                    r = await client.get(
                        f"https://api.themoviedb.org/3/find/{src_id}",
                        params={"api_key": api_key, "external_source": "imdb_id"},
                    )
                if r.status_code == 200:
                    data = r.json()
                    for bucket in ("movie_results", "tv_results"):
                        results = data.get(bucket, [])
                        if results and results[0].get("poster_path"):
                            item = dict(item)
                            item["poster_url"] = (
                                f"https://image.tmdb.org/t/p/w185{results[0]['poster_path']}"
                            )
                            break
            except Exception:
                pass
        return item

    import asyncio
    resolved = await asyncio.gather(*[_resolve_poster(it) for it in items])
    return JSONResponse(list(resolved))


@app.post("/api/brain/zone/{zone_id}/art")
async def api_brain_art(zone_id: str):
    """Lazy AI atmospheric art for a zone. Caches to disk; graceful fallback."""
    import os

    if not BRAIN_DATA.exists():
        raise HTTPException(503, "brain_data.json not built yet")

    zones = json.loads(BRAIN_DATA.read_text())
    zone = next((z for z in zones if z["id"] == zone_id), None)
    if zone is None:
        raise HTTPException(404, f"Zone {zone_id!r} not found")

    BRAIN_ART.mkdir(parents=True, exist_ok=True)
    cache_path = BRAIN_ART / f"{zone_id}.png"

    if cache_path.exists():
        return JSONResponse({"art_url": f"/brain/art/{zone_id}"})

    exemplars = ", ".join(zone.get("exemplars", [])[:2])
    prompt = (
        f"A fairy-tale {zone['label']} realm, glowing manuscript illumination style, "
        f"featuring {exemplars}, rich amber and forest-green palette, dreamlike, "
        "no text, square format"
    )

    openai_key = os.environ.get("OPENAI_API_KEY", "")
    replicate_token = os.environ.get("REPLICATE_API_TOKEN", "")

    if openai_key:
        import httpx as _httpx
        async with _httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(
                "https://api.openai.com/v1/images/generations",
                headers={"Authorization": f"Bearer {openai_key}"},
                json={"model": "dall-e-3", "prompt": prompt, "size": "1024x1024", "n": 1},
            )
        if r.status_code == 200:
            img_url = r.json()["data"][0]["url"]
            async with _httpx.AsyncClient(timeout=30.0) as client:
                img_r = await client.get(img_url)
            if img_r.status_code == 200:
                cache_path.write_bytes(img_r.content)
                return JSONResponse({"art_url": f"/brain/art/{zone_id}"})

    elif replicate_token:
        import httpx as _httpx
        async with _httpx.AsyncClient(timeout=90.0) as client:
            r = await client.post(
                "https://api.replicate.com/v1/models/stability-ai/sdxl/predictions",
                headers={
                    "Authorization": f"Token {replicate_token}",
                    "Content-Type": "application/json",
                },
                json={"input": {"prompt": prompt, "width": 1024, "height": 1024}},
            )
        if r.status_code == 201:
            pred = r.json()
            pred_id = pred["id"]
            for _ in range(30):
                import asyncio
                await asyncio.sleep(3)
                async with _httpx.AsyncClient(timeout=10.0) as client:
                    poll = await client.get(
                        f"https://api.replicate.com/v1/predictions/{pred_id}",
                        headers={"Authorization": f"Token {replicate_token}"},
                    )
                pd = poll.json()
                if pd.get("status") == "succeeded":
                    img_url = pd["output"][0] if pd.get("output") else None
                    if img_url:
                        async with _httpx.AsyncClient(timeout=30.0) as client:
                            img_r = await client.get(img_url)
                        if img_r.status_code == 200:
                            cache_path.write_bytes(img_r.content)
                            return JSONResponse({"art_url": f"/brain/art/{zone_id}"})
                    break
                if pd.get("status") in ("failed", "canceled"):
                    break

    return JSONResponse({"art_url": None, "message": "No image key configured"})


@app.get("/brain/art/{zone_id}")
def brain_art_file(zone_id: str):
    path = BRAIN_ART / f"{zone_id}.png"
    if not path.exists():
        raise HTTPException(404, "Art not generated yet")
    return FileResponse(path, media_type="image/png")
