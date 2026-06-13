"""
Phase 1: Enrich top-300 Spotify artists with MusicBrainz genre tags.
Outputs: data/cache/mb_genres.json  (artist -> [tags])
         data/cache/mb_unmatched.txt  (tags not in taxonomy — review these)
"""
import sqlite3, json, time, re, sys
from pathlib import Path
from collections import Counter

try:
    import musicbrainzngs as mb
    from rapidfuzz import fuzz
except ImportError:
    sys.exit("Run: pip install musicbrainzngs rapidfuzz")

ROOT = Path(__file__).parent.parent
DB_PATH    = ROOT / "data/processed/entertainment.db"
CACHE_PATH = ROOT / "data/cache/mb_genres.json"
UNMATCH_PATH = ROOT / "data/cache/mb_unmatched.txt"

# ---------- taxonomy mapping ----------
MUSIC_TAG_TAXONOMY = {
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

    # INDIE_WORLD
    "indie rock": "INDIE_WORLD", "indie pop": "INDIE_WORLD",
    "indie folk": "INDIE_WORLD", "alternative rock": "INDIE_WORLD",
    "alternative": "INDIE_WORLD", "art rock": "INDIE_WORLD",
    "post-rock": "INDIE_WORLD", "post rock": "INDIE_WORLD",
    "rock": "INDIE_WORLD", "classic rock": "INDIE_WORLD",
    "blues rock": "INDIE_WORLD", "hard rock": "INDIE_WORLD",
    "psychedelic rock": "INDIE_WORLD", "psychedelia": "INDIE_WORLD",
    "neo-psychedelia": "INDIE_WORLD", "prog rock": "INDIE_WORLD",
    "progressive rock": "INDIE_WORLD", "new wave": "INDIE_WORLD",
    "post-punk": "INDIE_WORLD", "punk": "INDIE_WORLD",
    "punk rock": "INDIE_WORLD", "glam rock": "INDIE_WORLD",
    "world music": "INDIE_WORLD", "afrobeat": "INDIE_WORLD",
    "afrobeats": "INDIE_WORLD", "latin": "INDIE_WORLD",
    "reggae": "INDIE_WORLD", "ska": "INDIE_WORLD",
    "pop": "INDIE_WORLD", "cabaret": "INDIE_WORLD",
    "krautrock": "INDIE_WORLD", "comedy": "INDIE_WORLD",
    "soft rock": "INDIE_WORLD", "adult contemporary": "INDIE_WORLD",
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

NOISE_ARTISTS = {
    "sleep-o-phant", "jason stephenson", "richards kindermusikleder",
    "kalle klang", "max richter sleep", "white noise", "rain sounds",
    "nature sounds", "relaxing white noise",
}

def fetch_mb_tags(artist_name: str) -> list[str]:
    """Return list of MB tag names for artist, empty list if no confident match."""
    try:
        result = mb.search_artists(artist=artist_name, limit=5)
    except Exception as e:
        print(f"  MB error for {artist_name!r}: {e}")
        return []

    for artist in result.get("artist-list", []):
        mb_score = int(artist.get("ext:score", 0))
        mb_name = artist.get("name", "")
        ratio = fuzz.ratio(artist_name.lower(), mb_name.lower())
        if mb_score >= 80 and ratio >= 75:
            tags = artist.get("tag-list", [])
            return [t["name"].lower() for t in tags if int(t.get("count", 0)) > 0]
    return []

def main():
    mb.set_useragent("observatory-taste-map", "1.0", "https://github.com/waldo-van-der-code/observatory")

    # Load cache
    cache: dict = {}
    if CACHE_PATH.exists():
        cache = json.loads(CACHE_PATH.read_text())
    print(f"Cache has {len(cache)} entries")

    # Top 300 artists
    con = sqlite3.connect(DB_PATH)
    rows = con.execute("""
        SELECT artist, SUM(ms_played) as total
        FROM spotify_plays
        WHERE artist IS NOT NULL
        GROUP BY artist
        ORDER BY total DESC
        LIMIT 300
    """).fetchall()
    con.close()

    artists = [(r[0], r[1]) for r in rows
               if r[0].lower() not in NOISE_ARTISTS]

    unmatched_tags: Counter = Counter()
    newly_fetched = 0

    for i, (artist, ms) in enumerate(artists):
        if artist in cache:
            continue
        tags = fetch_mb_tags(artist)
        cache[artist] = tags
        newly_fetched += 1
        print(f"[{i+1}/{len(artists)}] {artist}: {tags[:5]}")
        time.sleep(1.1)  # MB rate limit

    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2))
    print(f"\nFetched {newly_fetched} new artists. Cache saved.")

    # Tag frequency analysis
    all_tags: Counter = Counter()
    matched_tags: Counter = Counter()
    for artist, tags in cache.items():
        if artist.lower() in NOISE_ARTISTS:
            continue
        for tag in tags:
            all_tags[tag] += 1
            if tag in MUSIC_TAG_TAXONOMY:
                matched_tags[tag] += 1
            else:
                unmatched_tags[tag] += 1

    print(f"\n=== TAG ANALYSIS ===")
    print(f"Unique tags seen: {len(all_tags)}")
    print(f"Matched to taxonomy: {len(matched_tags)} unique tags")
    print(f"Unmatched: {len(unmatched_tags)} unique tags")

    top_unmatched = unmatched_tags.most_common(40)
    print(f"\nTop unmatched tags (add to MUSIC_TAG_TAXONOMY if ≥5 occurrences):")
    for tag, count in top_unmatched:
        if count >= 2:
            print(f"  {count:3d}x  {tag!r}")

    UNMATCH_PATH.write_text("\n".join(f"{c}\t{t}" for t, c in top_unmatched))
    print(f"\nUnmatched tags written to {UNMATCH_PATH}")

if __name__ == "__main__":
    main()
