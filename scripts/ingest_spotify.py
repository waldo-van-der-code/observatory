#!/Users/waldo.vanderhaeghen/Library/Scripts/watcher-env/bin/python3
"""Ingest Spotify streaming history + library into entertainment.db."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from db import get_conn, init_db

RAW = Path(__file__).parent.parent / "data" / "raw"


def ingest_streaming(conn) -> int:
    """Streaming_History_Audio_*.json (extended) → spotify_plays table."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS spotify_plays (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ended_at    TEXT,
            artist      TEXT,
            track       TEXT,
            ms_played   INTEGER,
            album       TEXT
        )
    """)
    conn.execute("DELETE FROM spotify_plays")

    total = 0
    for f in sorted(RAW.glob("spotify_streaming_*.json")):
        entries = json.loads(f.read_text(encoding="utf-8"))
        for e in entries:
            if e.get("ms_played", 0) < 30000:  # skip tracks played < 30s
                continue
            # Extended format: track name is in master_metadata_track_name; null = podcast/episode
            track = e.get("trackName") or e.get("master_metadata_track_name")
            if not track:
                continue  # skip podcasts and episodes
            artist = e.get("artistName") or e.get("master_metadata_album_artist_name")
            album = e.get("albumName") or e.get("master_metadata_album_album_name")
            conn.execute(
                "INSERT INTO spotify_plays (ended_at, artist, track, ms_played, album) VALUES (?,?,?,?,?)",
                (e.get("endTime") or e.get("ts"), artist, track, e.get("ms_played"), album),
            )
            total += 1
    conn.commit()
    return total


def ingest_library(conn) -> int:
    """YourLibrary.json → spotify_saved table."""
    lib_file = RAW / "spotify_library.json"
    if not lib_file.exists():
        return 0

    conn.execute("""
        CREATE TABLE IF NOT EXISTS spotify_saved (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            kind    TEXT,   -- 'track' | 'album' | 'artist'
            name    TEXT,
            artist  TEXT,
            album   TEXT
        )
    """)
    conn.execute("DELETE FROM spotify_saved")

    data = json.loads(lib_file.read_text(encoding="utf-8"))
    total = 0

    for track in data.get("tracks", []):
        conn.execute(
            "INSERT INTO spotify_saved (kind, name, artist, album) VALUES (?,?,?,?)",
            ("track", track.get("track"), track.get("artist"), track.get("album")),
        )
        total += 1
    for album in data.get("albums", []):
        conn.execute(
            "INSERT INTO spotify_saved (kind, name, artist) VALUES (?,?,?)",
            ("album", album.get("album"), album.get("artist")),
        )
        total += 1
    for artist in data.get("artists", []):
        conn.execute(
            "INSERT INTO spotify_saved (kind, name) VALUES (?,?)",
            ("artist", artist.get("name")),
        )
        total += 1

    conn.commit()
    return total


def main():
    conn = get_conn()
    init_db(conn)

    plays = ingest_streaming(conn)
    saved = ingest_library(conn)

    print(f"Spotify: {plays} plays ingested, {saved} library items")

    if plays:
        row = conn.execute("""
            SELECT artist, count(*) n, sum(ms_played)/3600000.0 hrs
            FROM spotify_plays GROUP BY artist ORDER BY n DESC LIMIT 5
        """).fetchall()
        print("Top artists:")
        for r in row:
            print(f"  {r[0]}: {r[1]} plays ({r[2]:.1f}h)")


if __name__ == "__main__":
    main()
