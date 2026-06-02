"""
Phase 2: Aggregate enriched data into per-node raw scores.
Outputs: data/processed/map_data.json
Sources: Spotify (music) + IMDb ratings + Netflix viewing duration + Goodreads (books)
"""
import sqlite3, json, csv, re
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).parent.parent
DB_PATH    = ROOT / "data/processed/entertainment.db"
MB_CACHE   = ROOT / "data/cache/mb_genres.json"
OUT_PATH   = ROOT / "data/processed/map_data.json"

NODE_IDS = [
    "SOUL_JAZZ", "FOLK_SINGER", "ELECTRONIC_HIP", "INDIE_WORLD",
    "DRAMA", "CRIME_THRILLER", "ARTHOUSE", "SCI_FI",
    "FANTASY_COMEDY", "ACTION_ADV", "ANIMATION", "HISTORY",
]

NOISE_ARTISTS = {
    "sleep-o-phant", "jason stephenson", "richards kindermusikleder",
    "kalle klang",
}

# ---------- Music tag → node ----------
import sys as _sys
_sys.path.insert(0, str(Path(__file__).parent))
from enrich_music_genres import MUSIC_TAG_TAXONOMY

# ---------- Film IMDb genre → node ----------
FILM_GENRE_MAP = {
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

# ---------- Book genre fingerprint → node ----------
BOOK_GENRE_MAP = {
    "Comic Fantasy":       "FANTASY_COMEDY",
    "Hard Science Fiction":"SCI_FI",
    "Science Fiction":     "SCI_FI",
    "Epic Fantasy":        "FANTASY_COMEDY",
    "Space Opera":         "SCI_FI",
    "Urban Fantasy":       "FANTASY_COMEDY",
    "Literary Fiction":    "DRAMA",
    "Philosophical Fiction":"ARTHOUSE",
    "Historical Adventure":"HISTORY",
    "Historical Fiction":  "HISTORY",
    "Crime Fiction":       "CRIME_THRILLER",
    "Fantasy":             "FANTASY_COMEDY",
    "Horror":              "CRIME_THRILLER",
}

YEAR_BUCKETS = {
    (2014, 2016): "2014-16",
    (2017, 2019): "2017-19",
    (2020, 2022): "2020-22",
    (2023, 2026): "2023-26",
}

def year_bucket(year: int) -> str | None:
    for (lo, hi), label in YEAR_BUCKETS.items():
        if lo <= year <= hi:
            return label
    return None


def build_music(con: sqlite3.Connection, mb_cache: dict) -> tuple[dict, dict]:
    """Returns (music_raw per node, temporal per node)."""
    rows = con.execute(
        "SELECT artist, ms_played, ended_at FROM spotify_plays WHERE artist IS NOT NULL"
    ).fetchall()

    music_raw: dict[str, float] = defaultdict(float)
    temporal:  dict[str, dict[str, float]] = {nid: defaultdict(float) for nid in NODE_IDS}

    for artist, ms_played, ended_at in rows:
        if not ms_played or artist.lower() in NOISE_ARTISTS:
            continue
        tags = mb_cache.get(artist, [])
        if not tags:
            continue

        # Weight tags: first tag full weight, others decay
        tag_weights = [1.0, 0.7, 0.5, 0.4, 0.3]
        mapped: dict[str, float] = defaultdict(float)
        for i, tag in enumerate(tags[:5]):
            node = MUSIC_TAG_TAXONOMY.get(tag)
            if node:
                mapped[node] += tag_weights[i]

        if not mapped:
            continue

        # Distribute ms_played proportionally across mapped nodes
        total_w = sum(mapped.values())
        hours = ms_played / 3_600_000
        for node, w in mapped.items():
            share = hours * (w / total_w)
            music_raw[node] += share
            if ended_at:
                try:
                    year = int(ended_at[:4])
                    bucket = year_bucket(year)
                    if bucket:
                        temporal[node][bucket] += share
                except (ValueError, TypeError):
                    pass

    return dict(music_raw), {n: dict(d) for n, d in temporal.items()}


def build_film(con: sqlite3.Connection) -> dict[str, float]:
    """Weighted film score per node: count × avg_rating."""
    rows = con.execute("""
        SELECT m.genres, ui.rating
        FROM media_items m
        JOIN user_interactions ui ON m.id = ui.media_id
        WHERE m.genres IS NOT NULL
          AND ui.rating IS NOT NULL
          AND m.media_type IN ('film', 'tv_show')
    """).fetchall()

    node_ratings: dict[str, list[float]] = defaultdict(list)
    for genres_json, rating in rows:
        try:
            genres = json.loads(genres_json)
        except Exception:
            continue
        nodes_hit = set()
        for genre in genres:
            node = FILM_GENRE_MAP.get(genre)
            if node and node not in nodes_hit:
                node_ratings[node].append(float(rating))
                nodes_hit.add(node)

    # score = count × avg_rating (penalises genres with few items)
    return {
        node: len(ratings) * (sum(ratings) / len(ratings))
        for node, ratings in node_ratings.items()
    }


def _strip_episode(title: str) -> str:
    """'Show: Season 1: Ep Title (Episode 3)' → 'Show'."""
    m = re.match(r"^(.+?)(?::\s*Season\s*\d|:\s*Series\s*\d|:\s*Part\s*\d)", title, re.IGNORECASE)
    return m.group(1).strip() if m else title.strip()


def _parse_duration(dur: str) -> float:
    """'01:23:45' → hours as float."""
    parts = dur.strip().split(":")
    try:
        h, m, s = int(parts[0]), int(parts[1]), int(parts[2])
        return h + m / 60 + s / 3600
    except Exception:
        return 0.0


def build_netflix(con: sqlite3.Connection) -> dict[str, float]:
    """
    Parse netflix_viewing.csv (wally profile) for watch duration per title.
    Cross-reference against IMDb media_items by normalized title to inherit genres.
    Returns film_raw contribution per genre node (in hours).
    """
    viewing_path = ROOT / "data/raw/netflix_viewing.csv"
    if not viewing_path.exists():
        return {}

    # Sum watch hours per base title (wally profile only, skip very short clips < 2 min)
    title_hours: dict[str, float] = defaultdict(float)
    with open(viewing_path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if row.get("Profile Name", "").strip().lower() != "wally":
                continue
            hours = _parse_duration(row.get("Duration", ""))
            if hours < 2 / 60:  # skip clips under 2 minutes
                continue
            base = _strip_episode(row["Title"])
            title_hours[base] += hours

    # Build lookup: normalized title → genres from IMDb-sourced media_items
    rows = con.execute("""
        SELECT title, genres FROM media_items
        WHERE source = 'imdb' AND genres IS NOT NULL
    """).fetchall()
    imdb_genres: dict[str, list] = {}
    for title, genres_json in rows:
        try:
            imdb_genres[title.lower().strip()] = json.loads(genres_json)
        except Exception:
            pass

    # Match Netflix titles to IMDb genres; weight by watch hours
    node_hours: dict[str, float] = defaultdict(float)
    matched, unmatched = 0, 0
    for title, hours in title_hours.items():
        genres = imdb_genres.get(title.lower())
        if not genres:
            unmatched += 1
            continue
        matched += 1
        nodes_hit: set = set()
        for genre in genres:
            node = FILM_GENRE_MAP.get(genre)
            if node and node not in nodes_hit:
                node_hours[node] += hours
                nodes_hit.add(node)

    print(f"  Netflix: {matched} titles matched to IMDb genres, {unmatched} unmatched "
          f"({matched/(matched+unmatched)*100:.0f}% hit rate)")
    return dict(node_hours)


JUSTWATCH_GENRES: dict[str, list[str]] = {
    "3 body problem":                          ["SCI_FI", "DRAMA"],
    "anora":                                   ["DRAMA"],
    "bo burnham: inside":                      ["ARTHOUSE", "FANTASY_COMEDY"],
    "brooklyn nine-nine":                      ["FANTASY_COMEDY"],
    "caught stealing":                         ["ACTION_ADV", "CRIME_THRILLER"],
    "common side effects":                     ["FANTASY_COMEDY", "DRAMA"],
    "conclave":                                ["DRAMA", "CRIME_THRILLER"],
    "dead poets society":                      ["DRAMA"],
    "dune":                                    ["SCI_FI", "ACTION_ADV"],
    "dune: part two":                          ["SCI_FI", "ACTION_ADV"],
    "dungeon meshi":                           ["FANTASY_COMEDY", "ANIMATION"],
    "fallout":                                 ["SCI_FI", "ACTION_ADV"],
    "fleabag":                                 ["DRAMA", "FANTASY_COMEDY"],
    "free guy":                                ["FANTASY_COMEDY", "ACTION_ADV"],
    "hamilton":                                ["HISTORY", "DRAMA"],
    "harry potter and the prisoner of azkaban":["FANTASY_COMEDY"],
    "logan":                                   ["ACTION_ADV", "DRAMA"],
    "monty python's flying circus":            ["FANTASY_COMEDY"],
    "oppenheimer":                             ["HISTORY", "DRAMA"],
    "palm springs":                            ["FANTASY_COMEDY"],
    "parks and recreation":                    ["FANTASY_COMEDY"],
    "scavengers reign":                        ["SCI_FI", "ANIMATION"],
    "squid game":                              ["DRAMA", "CRIME_THRILLER"],
    "the big lebowski":                        ["FANTASY_COMEDY", "CRIME_THRILLER"],
    "the deuce":                               ["DRAMA", "CRIME_THRILLER"],
    "the inbetweeners":                        ["FANTASY_COMEDY"],
    "the playlist":                            ["DRAMA"],
    "travelers":                               ["SCI_FI"],
    "whiplash":                                ["DRAMA"],
}


def build_justwatch(con: sqlite3.Connection) -> dict[str, float]:
    """JustWatch rated items — hardcoded genres, weighted by rating."""
    jw_rows = con.execute("""
        SELECT m.title, ui.rating
        FROM media_items m
        JOIN user_interactions ui ON m.id = ui.media_id
        WHERE m.source = 'justwatch' AND ui.rating IS NOT NULL
    """).fetchall()

    node_ratings: dict[str, list[float]] = defaultdict(list)
    matched = 0
    for title, rating in jw_rows:
        nodes = JUSTWATCH_GENRES.get(title.lower().strip())
        if not nodes:
            continue
        matched += 1
        for node in nodes:
            node_ratings[node].append(float(rating) / len(nodes))

    print(f"  JustWatch: {matched}/{len(jw_rows)} rated titles genre-mapped")
    return {node: len(r) * (sum(r) / len(r)) for node, r in node_ratings.items()}


# Hardcoded genre assignments for 26 Audible titles (audiobooks)
AUDIBLE_GENRES: dict[str, list[str]] = {
    "death's end":                    ["SCI_FI"],
    "the dark forest":                ["SCI_FI"],
    "norse mythology":                ["FANTASY_COMEDY"],
    "the colour of magic":            ["FANTASY_COMEDY"],
    "red dwarf":                      ["SCI_FI", "FANTASY_COMEDY"],
    "inspired":                       ["DRAMA"],
    "dark age":                       ["SCI_FI", "ACTION_ADV"],
    "iron gold":                      ["SCI_FI", "ACTION_ADV"],
    "the creative act":               ["ARTHOUSE"],
    "the dispossessed":               ["SCI_FI"],
    "the martian":                    ["SCI_FI"],
    "heaven's river":                 ["SCI_FI"],
    "dodger":                         ["FANTASY_COMEDY", "HISTORY"],
    "endymion":                       ["SCI_FI"],
    "night watch":                    ["FANTASY_COMEDY"],
    "wintersmith":                    ["FANTASY_COMEDY"],
    "thud!":                          ["FANTASY_COMEDY"],
    "how long 'til black future month?": ["SCI_FI", "FANTASY_COMEDY"],
    "brain rules for baby":           ["DRAMA"],
    "the shepherd's crown":           ["FANTASY_COMEDY"],
    "raising steam":                  ["FANTASY_COMEDY"],
    "warming the stone child":        ["FANTASY_COMEDY"],
    "oryx and crake":                 ["SCI_FI", "DRAMA"],
    "crucial conversations":          ["DRAMA"],
    "stranger in a strange land":     ["SCI_FI"],
    "i shall wear midnight":          ["FANTASY_COMEDY"],
}
AUDIBLE_WEIGHT = 0.15  # per-book contribution to book_raw (comparable to fingerprint scale)


def build_audible(con: sqlite3.Connection) -> dict[str, float]:
    """Add audiobook genre contributions to book_raw."""
    titles = [r[0] for r in con.execute(
        "SELECT title FROM media_items WHERE source='audible'"
    ).fetchall()]

    node_raw: dict[str, float] = defaultdict(float)
    matched = 0
    for title in titles:
        nodes = AUDIBLE_GENRES.get(title.lower().strip())
        if nodes:
            matched += 1
            for node in nodes:
                node_raw[node] += AUDIBLE_WEIGHT / len(nodes)

    print(f"  Audible: {matched}/{len(titles)} titles genre-mapped")
    return dict(node_raw)


def build_books(con: sqlite3.Connection) -> dict[str, float]:
    """Use taste_profile.genre_fingerprint (books) mapped to taxonomy."""
    row = con.execute(
        "SELECT genre_fingerprint FROM taste_profile ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if not row or not row[0]:
        return {}
    try:
        fp = json.loads(row[0])
    except Exception:
        return {}

    book_raw: dict[str, float] = defaultdict(float)
    for genre, score in fp.items():
        node = BOOK_GENRE_MAP.get(genre)
        if node:
            book_raw[node] += float(score)
    return dict(book_raw)


def main():
    if not MB_CACHE.exists():
        print("ERROR: mb_genres.json not found — run enrich_music_genres.py first")
        return

    mb_cache = json.loads(MB_CACHE.read_text())
    con = sqlite3.connect(DB_PATH)

    print("Building music scores...")
    music_raw, temporal = build_music(con, mb_cache)

    print("Building film scores (IMDb ratings)...")
    film_raw = build_film(con)

    print("Building Netflix viewing scores...")
    netflix_raw = build_netflix(con)

    print("Building JustWatch scores...")
    justwatch_raw = build_justwatch(con)

    print("Building book scores (Goodreads)...")
    book_raw = build_books(con)

    print("Building Audible scores...")
    audible_raw = build_audible(con)

    con.close()

    # Merge film sources (all go into film_raw — same blue medium layer)
    for node, v in netflix_raw.items():
        film_raw[node] = film_raw.get(node, 0.0) + v
    for node, v in justwatch_raw.items():
        film_raw[node] = film_raw.get(node, 0.0) + v

    # Merge book sources (Audible into book_raw — same purple medium layer)
    for node, v in audible_raw.items():
        book_raw[node] = book_raw.get(node, 0.0) + v

    # Assemble nodes
    nodes = []
    for nid in NODE_IDS:
        mr = music_raw.get(nid, 0.0)
        fr = film_raw.get(nid, 0.0)
        br = book_raw.get(nid, 0.0)
        t  = temporal.get(nid, {})
        nodes.append({
            "id":         nid,
            "music_raw":  round(mr, 2),
            "film_raw":   round(fr, 2),
            "book_raw":   round(br, 4),
            "temporal":   {k: round(v, 4) for k, v in sorted(t.items())},
        })

    OUT_PATH.write_text(json.dumps({"nodes": nodes}, indent=2))
    print(f"\nWrote {OUT_PATH}")

    # Sanity checks
    print("\n=== SANITY CHECK ===")
    for n in nodes:
        total = n["music_raw"] + n["film_raw"] + n["book_raw"]
        dom = "music" if n["music_raw"] == max(n["music_raw"], n["film_raw"], n["book_raw"]) \
              else ("film" if n["film_raw"] > n["book_raw"] else "book")
        print(f"{n['id']:18s}  music={n['music_raw']:7.1f}h  film={n['film_raw']:7.1f}  book={n['book_raw']:.3f}  → dominant={dom}")


if __name__ == "__main__":
    main()
