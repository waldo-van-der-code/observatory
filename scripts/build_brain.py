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

# Copied from enrich_music_genres.py — maps MusicBrainz tags to taste zones
MUSIC_TAG_TAXONOMY: dict[str, str] = {
    # SOUL_JAZZ
    "soul": "SOUL_JAZZ", "r&b": "SOUL_JAZZ", "rhythm and blues": "SOUL_JAZZ",
    "blues": "SOUL_JAZZ", "gospel": "SOUL_JAZZ", "funk": "SOUL_JAZZ",
    "jazz": "SOUL_JAZZ", "bebop": "SOUL_JAZZ", "swing": "SOUL_JAZZ",
    "big band": "SOUL_JAZZ", "gypsy jazz": "SOUL_JAZZ", "manouche": "SOUL_JAZZ",
    "acid jazz": "SOUL_JAZZ", "nu jazz": "SOUL_JAZZ", "jazz fusion": "SOUL_JAZZ",
    "neo soul": "SOUL_JAZZ", "bossa nova": "SOUL_JAZZ", "samba": "SOUL_JAZZ",
    "motown": "SOUL_JAZZ", "electro swing": "SOUL_JAZZ", "doo-wop": "SOUL_JAZZ",
    "smooth jazz": "SOUL_JAZZ", "cool jazz": "SOUL_JAZZ",
    # FOLK_SINGER
    "folk": "FOLK_SINGER", "singer-songwriter": "FOLK_SINGER",
    "singer/songwriter": "FOLK_SINGER", "country": "FOLK_SINGER",
    "americana": "FOLK_SINGER", "folk rock": "FOLK_SINGER",
    "chamber folk": "FOLK_SINGER", "chamberfolk": "FOLK_SINGER",
    "neofolk": "FOLK_SINGER", "neo-folk": "FOLK_SINGER",
    "anti-folk": "FOLK_SINGER", "sadcore": "FOLK_SINGER",
    "baroque pop": "FOLK_SINGER", "chanson": "FOLK_SINGER",
    "new weird america": "FOLK_SINGER", "alt-country": "FOLK_SINGER",
    "acoustic": "FOLK_SINGER", "protest": "FOLK_SINGER",
    "celtic": "FOLK_SINGER", "bluegrass": "FOLK_SINGER",
    "appalachian": "FOLK_SINGER", "storytelling": "FOLK_SINGER",
    "torch song": "FOLK_SINGER",
    # ELECTRONIC_HIP
    "hip hop": "ELECTRONIC_HIP", "hip-hop": "ELECTRONIC_HIP",
    "rap": "ELECTRONIC_HIP", "trip-hop": "ELECTRONIC_HIP",
    "trip hop": "ELECTRONIC_HIP", "downtempo": "ELECTRONIC_HIP",
    "electronic": "ELECTRONIC_HIP", "electronica": "ELECTRONIC_HIP",
    "house": "ELECTRONIC_HIP", "techno": "ELECTRONIC_HIP",
    "drum and bass": "ELECTRONIC_HIP", "dnb": "ELECTRONIC_HIP",
    "dubstep": "ELECTRONIC_HIP", "electro": "ELECTRONIC_HIP",
    "idm": "ELECTRONIC_HIP", "intelligent dance music": "ELECTRONIC_HIP",
    "breakbeat": "ELECTRONIC_HIP", "jungle": "ELECTRONIC_HIP",
    "glitch": "ELECTRONIC_HIP", "chillhop": "ELECTRONIC_HIP",
    "lo-fi": "ELECTRONIC_HIP", "lo fi": "ELECTRONIC_HIP",
    "lo-fi hip hop": "ELECTRONIC_HIP", "future bass": "ELECTRONIC_HIP",
    "chill out": "ELECTRONIC_HIP", "chillout": "ELECTRONIC_HIP",
    # ROCK — classic/electric rock, blues rock, punk, glam, prog
    "rock": "ROCK", "classic rock": "ROCK",
    "blues rock": "ROCK", "hard rock": "ROCK",
    "psychedelic rock": "ROCK", "psychedelia": "ROCK",
    "neo-psychedelia": "ROCK", "prog rock": "ROCK",
    "progressive rock": "ROCK", "new wave": "ROCK",
    "post-punk": "ROCK", "punk": "ROCK",
    "punk rock": "ROCK", "glam rock": "ROCK",
    "soft rock": "ROCK", "adult contemporary": "ROCK",
    "krautrock": "ROCK",
    # INDIE_WORLD — indie, alt, world, pop crossover
    "indie rock": "INDIE_WORLD", "indie pop": "INDIE_WORLD",
    "indie folk": "INDIE_WORLD", "alternative rock": "INDIE_WORLD",
    "alternative": "INDIE_WORLD", "art rock": "INDIE_WORLD",
    "post-rock": "INDIE_WORLD", "post rock": "INDIE_WORLD",
    "world music": "INDIE_WORLD", "afrobeat": "INDIE_WORLD",
    "afrobeats": "INDIE_WORLD", "latin": "INDIE_WORLD",
    "reggae": "INDIE_WORLD", "ska": "INDIE_WORLD",
    "pop": "INDIE_WORLD", "cabaret": "INDIE_WORLD", "comedy": "INDIE_WORLD",
    "lounge": "INDIE_WORLD", "exotica": "INDIE_WORLD",
    "tropicália": "INDIE_WORLD", "tropicalia": "INDIE_WORLD",
    "cumbia": "INDIE_WORLD", "flamenco": "INDIE_WORLD",
    "fado": "INDIE_WORLD", "tango": "INDIE_WORLD",
    "balkan": "INDIE_WORLD", "klezmer": "INDIE_WORLD",
    # ARTHOUSE
    "experimental": "ARTHOUSE", "avant-garde": "ARTHOUSE",
    "ambient": "ARTHOUSE", "noise": "ARTHOUSE",
    "drone": "ARTHOUSE", "modern classical": "ARTHOUSE",
    "contemporary classical": "ARTHOUSE", "classical": "ARTHOUSE",
    "minimalism": "ARTHOUSE", "minimalist": "ARTHOUSE",
    "sound art": "ARTHOUSE", "field recordings": "ARTHOUSE",
    "musique concrète": "ARTHOUSE", "musique concrete": "ARTHOUSE",
    "post-minimalism": "ARTHOUSE", "neo-classical": "ARTHOUSE",
    "neoclassical": "ARTHOUSE",
}

ROOT = Path(__file__).parent.parent
LAYOUT_PATH   = ROOT / "config" / "layout.json"
EXEMPLARS_PATH = ROOT / "config" / "exemplars.json"
MAP_DATA_PATH = ROOT / "data" / "processed" / "map_data.json"
DB_PATH       = ROOT / "data" / "processed" / "entertainment.db"
OUT_PATH      = ROOT / "data" / "processed" / "brain_data.json"
MB_CACHE_PATH = ROOT / "data" / "cache" / "mb_genres.json"
ART_CACHE     = ROOT / "data" / "cache" / "brain_art"

NODE_IDS = [
    "SOUL_JAZZ", "FOLK_SINGER", "ELECTRONIC_HIP", "INDIE_WORLD",
    "ROCK",
    "DRAMA", "CRIME_THRILLER", "ARTHOUSE", "SCI_FI",
    "FANTASY_COMEDY", "ACTION_ADV", "ANIMATION", "HISTORY",
]

NOISE_ARTISTS = {
    "sleep-o-phant", "jason stephenson", "richards kindermusikleder", "kalle klang",
}

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
    """Return up to 12 top-rated items per zone. Poster URLs fetched lazily by the API."""
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


def _get_labels(conn: sqlite3.Connection, mb_cache: dict) -> dict[str, list[dict]]:
    """Build top-60 map labels per zone: [{text, type, weight}] sorted by weight desc."""
    # {zone: [(text, type, raw_score), ...]}
    zone_raw: dict[str, list[tuple[str, str, float]]] = defaultdict(list)

    # ── Music artists ────────────────────────────────────────────────────────
    rows = conn.execute(
        "SELECT artist, SUM(ms_played)/3600000.0 as hours "
        "FROM spotify_plays WHERE artist IS NOT NULL GROUP BY artist ORDER BY hours DESC"
    ).fetchall()

    for artist, hours in rows:
        if not hours or artist.lower() in NOISE_ARTISTS:
            continue
        tags = mb_cache.get(artist, [])
        if not tags:
            continue
        tag_weights = [1.0, 0.7, 0.5, 0.4, 0.3]
        mapped: dict[str, float] = defaultdict(float)
        for i, tag in enumerate(tags[:5]):
            node = MUSIC_TAG_TAXONOMY.get(tag)
            if node:
                mapped[node] += tag_weights[i]
        if not mapped:
            continue
        primary_zone = max(mapped, key=lambda k: mapped[k])
        zone_raw[primary_zone].append((artist, "music", float(hours)))

    # ── Films / TV shows ─────────────────────────────────────────────────────
    rows = conn.execute("""
        SELECT m.title, m.genres, MAX(ui.rating) as rating
        FROM media_items m
        JOIN user_interactions ui ON ui.media_id = m.id
        WHERE m.media_type IN ('film', 'tv_show')
          AND ui.rating IS NOT NULL
          AND m.genres IS NOT NULL
        GROUP BY m.id
        ORDER BY rating DESC
    """).fetchall()

    seen_film: dict[str, set[str]] = defaultdict(set)
    for title, genres_json, rating in rows:
        try:
            genres = json.loads(genres_json)
        except Exception:
            continue
        for genre in genres:
            zone = FILM_GENRE_MAP.get(genre)
            if zone and title not in seen_film[zone]:
                zone_raw[zone].append((title, "film", float(rating)))
                seen_film[zone].add(title)
                break  # primary genre only

    # ── Books (Goodreads) ────────────────────────────────────────────────────
    rows = conn.execute("""
        SELECT m.title, m.genres, MAX(ui.rating) as rating
        FROM media_items m
        JOIN user_interactions ui ON ui.media_id = m.id
        WHERE m.media_type = 'book'
          AND m.genres IS NOT NULL
        GROUP BY m.id
    """).fetchall()

    seen_book: dict[str, set[str]] = defaultdict(set)
    for title, genres_json, rating in rows:
        try:
            genres = json.loads(genres_json)
        except Exception:
            continue
        for genre in genres:
            zone = BOOK_GENRE_MAP.get(genre)
            if zone and title not in seen_book[zone]:
                zone_raw[zone].append((title, "book", float(rating or 3.0)))
                seen_book[zone].add(title)
                break

    # ── Audiobooks (Audible) ─────────────────────────────────────────────────
    audio_rows = conn.execute(
        "SELECT title FROM media_items WHERE source='audible'"
    ).fetchall()
    for (title,) in audio_rows:
        zones = AUDIBLE_GENRES.get(title.lower().strip())
        if zones:
            primary_zone = zones[0]
            if title not in seen_book[primary_zone]:
                zone_raw[primary_zone].append((title, "book", 3.5))
                seen_book[primary_zone].add(title)

    # ── Normalize per zone and pick top 15 ───────────────────────────────────
    result: dict[str, list[dict]] = {}
    for zone in NODE_IDS:
        items = zone_raw.get(zone, [])
        if not items:
            result[zone] = []
            continue

        items.sort(key=lambda x: x[2], reverse=True)
        max_raw = items[0][2]

        compiled = []
        for text, typ, raw in items[:60]:
            compiled.append({
                "text": text,
                "type": typ,
                "weight": round(raw / max_raw, 3) if max_raw > 0 else 0.0,
            })
        result[zone] = compiled

    return result


BRAIN_HTML = ROOT / "brain.html"
_PLACEHOLDER = "/* BRAIN_DATA_PLACEHOLDER */"


def _patch_brain_html(brain: list[dict]) -> None:
    html = BRAIN_HTML.read_text()
    inline = f"window.BRAIN_ZONES = {json.dumps(brain, separators=(',', ':'))};"
    patched = html.replace(_PLACEHOLDER, inline)
    if patched == html:
        print("Warning: brain.html placeholder not found — skipping inline patch")
        return
    BRAIN_HTML.write_text(patched)
    print(f"Patched brain.html with inline zone data ({len(inline)} chars)")


def build() -> None:
    layout = json.loads(LAYOUT_PATH.read_text())
    exemplars = json.loads(EXEMPLARS_PATH.read_text())
    map_data = json.loads(MAP_DATA_PATH.read_text())

    mb_cache: dict = {}
    if MB_CACHE_PATH.exists():
        mb_cache = json.loads(MB_CACHE_PATH.read_text())
    else:
        print(f"Warning: {MB_CACHE_PATH} not found — music labels will be empty")

    # Index map_data by zone id
    map_index: dict[str, dict] = {n["id"]: n for n in map_data["nodes"]}

    # Compute neighbors from layout coordinates
    neighbors = _compute_neighbors(layout["nodes"])

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    top_items = _get_top_items(conn)
    labels = _get_labels(conn, mb_cache)
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
            "labels": labels.get(nid, []),
            "neighbors": neighbors[nid],
            "explored": total > 10,
            "art_cached": art_cached,
        })

    OUT_PATH.write_text(json.dumps(brain, indent=2))
    print(f"Wrote {OUT_PATH} with {len(brain)} zones")

    _patch_brain_html(brain)

    max_total = max(z["engagement"]["total"] for z in brain)
    for z in brain:
        pct = z["engagement"]["total"] / max_total * 100
        lbl_ct = len(z["labels"])
        items_ct = len(z["top_items"])
        print(f"  {z['id']:18s}  total={z['engagement']['total']:7.1f}  ({pct:4.0f}%)  labels={lbl_ct:2d}  items={items_ct}")


if __name__ == "__main__":
    build()
