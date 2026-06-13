"""
Build brain_data.json from entertainment.db + layout.json + map_data.json.
Outputs data/processed/brain_data.json — one record per taste zone.
"""

from __future__ import annotations

import json
import math
import sqlite3
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).parent.parent
LAYOUT_PATH = ROOT / "config" / "layout.json"
EXEMPLARS_PATH = ROOT / "config" / "exemplars.json"
MAP_DATA_PATH = ROOT / "data" / "processed" / "map_data.json"
DB_PATH = ROOT / "data" / "processed" / "entertainment.db"
OUT_PATH = ROOT / "data" / "processed" / "brain_data.json"
ART_CACHE = ROOT / "data" / "cache" / "brain_art"

# Mirror from build_map_data.py — maps IMDb genre → zone
FILM_GENRE_MAP: dict[str, str] = {
    "Drama":       "DRAMA",
    "Biography":   "DRAMA",
    "Romance":     "DRAMA",
    "Music":       "SOUL_JAZZ",
    "Musical":     "SOUL_JAZZ",
    "Crime":       "CRIME_THRILLER",
    "Thriller":    "CRIME_THRILLER",
    "Mystery":     "CRIME_THRILLER",
    "Film-Noir":   "CRIME_THRILLER",
    "Horror":      "CRIME_THRILLER",
    "Sci-Fi":      "SCI_FI",
    "Fantasy":     "FANTASY_COMEDY",
    "Comedy":      "FANTASY_COMEDY",
    "Family":      "FANTASY_COMEDY",
    "Animation":   "ANIMATION",
    "Action":      "ACTION_ADV",
    "Adventure":   "ACTION_ADV",
    "Sport":       "ACTION_ADV",
    "War":         "HISTORY",
    "History":     "HISTORY",
    "Western":     "HISTORY",
    "Documentary": "ARTHOUSE",
}

BOOK_GENRE_MAP: dict[str, str] = {
    "Comic Fantasy":        "FANTASY_COMEDY",
    "Hard Science Fiction": "SCI_FI",
    "Science Fiction":      "SCI_FI",
    "Epic Fantasy":         "FANTASY_COMEDY",
    "Space Opera":          "SCI_FI",
    "Urban Fantasy":        "FANTASY_COMEDY",
    "Literary Fiction":     "DRAMA",
    "Philosophical Fiction":"ARTHOUSE",
    "Historical Adventure": "HISTORY",
    "Historical Fiction":   "HISTORY",
    "Crime Fiction":        "CRIME_THRILLER",
    "Fantasy":              "FANTASY_COMEDY",
    "Horror":               "CRIME_THRILLER",
}

# Audible title → zones (from build_map_data.py)
AUDIBLE_GENRES: dict[str, list[str]] = {
    "death's end":                       ["SCI_FI"],
    "the dark forest":                   ["SCI_FI"],
    "norse mythology":                   ["FANTASY_COMEDY"],
    "the colour of magic":               ["FANTASY_COMEDY"],
    "red dwarf":                         ["SCI_FI", "FANTASY_COMEDY"],
    "inspired":                          ["DRAMA"],
    "dark age":                          ["SCI_FI", "ACTION_ADV"],
    "iron gold":                         ["SCI_FI", "ACTION_ADV"],
    "the creative act":                  ["ARTHOUSE"],
    "the dispossessed":                  ["SCI_FI"],
    "the martian":                       ["SCI_FI"],
    "heaven's river":                    ["SCI_FI"],
    "dodger":                            ["FANTASY_COMEDY", "HISTORY"],
    "endymion":                          ["SCI_FI"],
    "night watch":                       ["FANTASY_COMEDY"],
    "wintersmith":                       ["FANTASY_COMEDY"],
    "thud!":                             ["FANTASY_COMEDY"],
    "how long 'til black future month?": ["SCI_FI", "FANTASY_COMEDY"],
    "brain rules for baby":              ["DRAMA"],
    "the shepherd's crown":              ["FANTASY_COMEDY"],
    "raising steam":                     ["FANTASY_COMEDY"],
    "warming the stone child":           ["FANTASY_COMEDY"],
    "oryx and crake":                    ["SCI_FI", "DRAMA"],
    "crucial conversations":             ["DRAMA"],
    "stranger in a strange land":        ["SCI_FI"],
    "i shall wear midnight":             ["FANTASY_COMEDY"],
}


def _euclidean(a: dict, b: dict) -> float:
    return math.sqrt((a["x"] - b["x"]) ** 2 + (a["y"] - b["y"]) ** 2)


def _compute_neighbors(nodes: list[dict]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for node in nodes:
        distances = [
            (other["id"], _euclidean(node, other))
            for other in nodes
            if other["id"] != node["id"]
        ]
        distances.sort(key=lambda t: t[1])
        result[node["id"]] = [t[0] for t in distances[:3]]
    return result


def _zone_for_item(media_type: str, genres_json: str | None, title: str) -> str | None:
    """Return the primary zone ID for an item, or None if unmappable."""
    if media_type == "music":
        return None  # handled separately as typography cards

    if media_type in ("film", "tv_show"):
        try:
            genres = json.loads(genres_json or "[]")
        except Exception:
            return None
        for genre in genres:
            zone = FILM_GENRE_MAP.get(genre)
            if zone:
                return zone
        return None

    if media_type == "book":
        try:
            genres = json.loads(genres_json or "[]")
        except Exception:
            genres = []
        for genre in genres:
            zone = BOOK_GENRE_MAP.get(genre)
            if zone:
                return zone
        return None

    if media_type == "audiobook":
        zones = AUDIBLE_GENRES.get(title.lower().strip())
        return zones[0] if zones else None

    return None


def _get_top_items(conn: sqlite3.Connection) -> dict[str, list[dict]]:
    """Return up to 8 top-rated items per zone. Poster URLs fetched lazily by the API."""
    rows = conn.execute("""
        SELECT
            m.id, m.title, m.media_type, m.source, m.source_id,
            m.cover_url, m.year, m.genres, m.author,
            MAX(ui.rating) AS rating
        FROM media_items m
        JOIN user_interactions ui ON ui.media_id = m.id
        WHERE m.media_type IN ('film', 'tv_show', 'book', 'audiobook')
          AND ui.rating IS NOT NULL
        GROUP BY m.id
        ORDER BY rating DESC, m.year DESC
    """).fetchall()

    zone_items: dict[str, list[dict]] = defaultdict(list)
    seen_per_zone: dict[str, set[str]] = defaultdict(set)

    for row in rows:
        zone = _zone_for_item(row["media_type"], row["genres"], row["title"])
        if not zone:
            continue
        if row["id"] in seen_per_zone[zone]:
            continue
        if len(zone_items[zone]) >= 8:
            continue
        seen_per_zone[zone].add(row["id"])
        zone_items[zone].append({
            "title": row["title"],
            "media_type": row["media_type"],
            "source": row["source"],
            "source_id": row["source_id"],
            # cover_url pre-populated if available (tmdb-searched items); else null
            "poster_url": row["cover_url"] or None,
            "year": row["year"],
            "rating": row["rating"],
        })

    return dict(zone_items)


def build() -> None:
    layout = json.loads(LAYOUT_PATH.read_text())
    exemplars = json.loads(EXEMPLARS_PATH.read_text())
    map_data = json.loads(MAP_DATA_PATH.read_text())

    # Index map_data by zone id
    map_index: dict[str, dict] = {n["id"]: n for n in map_data["nodes"]}

    # Compute neighbors from layout coordinates
    neighbors = _compute_neighbors(layout["nodes"])

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    top_items = _get_top_items(conn)
    conn.close()

    ART_CACHE.mkdir(parents=True, exist_ok=True)

    brain: list[dict] = []
    for node in layout["nodes"]:
        nid = node["id"]
        md = map_index.get(nid, {})

        music = md.get("music_raw", 0.0)
        film = md.get("film_raw", 0.0)
        book = md.get("book_raw", 0.0)
        total = music + film + book

        art_cached = (ART_CACHE / f"{nid}.png").exists()

        brain.append({
            "id": nid,
            "label": node["label"],
            "x": node["x"],
            "y": node["y"],
            "engagement": {
                "total": round(total, 2),
                "music": round(music, 2),
                "film": round(film, 2),
                "book": round(book, 4),
            },
            "temporal": md.get("temporal", {}),
            "exemplars": exemplars.get(nid, [])[:4],
            "top_items": top_items.get(nid, []),
            "neighbors": neighbors[nid],
            "explored": total > 10,
            "art_cached": art_cached,
        })

    OUT_PATH.write_text(json.dumps(brain, indent=2))
    print(f"Wrote {OUT_PATH} with {len(brain)} zones")

    max_total = max(z["engagement"]["total"] for z in brain)
    for z in brain:
        pct = z["engagement"]["total"] / max_total * 100
        items_ct = len(z["top_items"])
        print(f"  {z['id']:18s}  total={z['engagement']['total']:7.1f}  ({pct:4.0f}%)  items={items_ct}  neighbors={z['neighbors']}")


if __name__ == "__main__":
    build()
