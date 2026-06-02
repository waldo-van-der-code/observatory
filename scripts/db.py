#!/Users/waldo.vanderhaeghen/Library/Scripts/watcher-env/bin/python3
"""Shared database setup for the entertainment dashboard."""

import json
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "processed" / "entertainment.db"


def get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS media_items (
            id          TEXT PRIMARY KEY,
            media_type  TEXT NOT NULL,
            title       TEXT NOT NULL,
            author      TEXT,
            director    TEXT,
            cast_leads  TEXT,
            year        INTEGER,
            genres      TEXT,
            series_name TEXT,
            series_pos  INTEGER,
            page_count  INTEGER,
            runtime_min INTEGER,
            source      TEXT,
            source_id   TEXT,
            cover_url   TEXT,
            created_at  TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS user_interactions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            media_id        TEXT REFERENCES media_items(id),
            interaction     TEXT NOT NULL,
            rating          REAL,
            date_completed  TEXT,
            date_added      TEXT,
            shelf           TEXT,
            source          TEXT
        );

        CREATE TABLE IF NOT EXISTS taste_profile (
            id                      INTEGER PRIMARY KEY,
            generated_at            TEXT,
            genre_fingerprint       TEXT,
            film_genre_fingerprint  TEXT,
            top_themes              TEXT,
            rating_calibration      TEXT,
            taste_clusters          TEXT,
            dislikes_pattern        TEXT,
            top_authors             TEXT,
            top_directors           TEXT,
            raw_response            TEXT
        );

        CREATE TABLE IF NOT EXISTS recommendations (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            generated_at        TEXT,
            media_type          TEXT,
            title               TEXT,
            author_or_director  TEXT,
            reason              TEXT,
            potential_issue     TEXT,
            confidence          REAL,
            status              TEXT DEFAULT 'pending'
        );

        CREATE TABLE IF NOT EXISTS imdb_xref (
            tmdb_id     TEXT PRIMARY KEY,
            imdb_id     TEXT
        );
    """)
    conn.commit()


def get_or_create_item(conn: sqlite3.Connection, item: dict) -> str:
    """Upsert a media item from external search metadata; return its DB id.

    item keys: source, source_id, media_type, title, author, director,
               year, genres (list), description, cover_url, imdb_id (optional)
    """
    # If we have an imdb_id, check whether it already exists (ingested from IMDb CSV)
    imdb_id = item.get("imdb_id")
    if imdb_id:
        row = conn.execute(
            "SELECT id FROM media_items WHERE id=? OR source_id=?",
            (imdb_id, imdb_id),
        ).fetchone()
        if row:
            return row["id"]

    # Use the id from the search result if provided; otherwise build it
    db_id = item.get("id") or f"{item['source']}:{item['source_id']}"

    genres_json = json.dumps(item.get("genres") or [])
    conn.execute(
        """INSERT INTO media_items
               (id, media_type, title, author, director, year, genres, cover_url, source, source_id)
           VALUES (?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(id) DO UPDATE SET
               title=excluded.title, author=excluded.author, director=excluded.director,
               year=excluded.year, genres=excluded.genres, cover_url=excluded.cover_url""",
        (
            db_id,
            item["media_type"],
            item["title"],
            item.get("author"),
            item.get("director"),
            item.get("year"),
            genres_json,
            item.get("cover_url"),
            item["source"],
            item["source_id"],
        ),
    )
    conn.commit()
    return db_id


def get_watchlist(conn: sqlite3.Connection) -> list[dict]:
    """Return all items on the to-watch or to-read shelf."""
    rows = conn.execute("""
        SELECT m.id, m.title, m.media_type, m.author, m.director, m.year,
               m.genres, m.cover_url, m.source, m.source_id,
               ui.shelf, ui.rating, ui.date_added
        FROM media_items m
        JOIN user_interactions ui ON ui.media_id = m.id
        WHERE ui.shelf IN ('to-watch', 'to-read')
          AND m.source IN ('tmdb', 'openlibrary')
        ORDER BY ui.date_added DESC
    """).fetchall()
    result = []
    for r in rows:
        result.append({
            "id": r["id"],
            "title": r["title"],
            "media_type": r["media_type"],
            "author": r["author"],
            "director": r["director"],
            "year": r["year"],
            "genres": json.loads(r["genres"] or "[]"),
            "cover_url": r["cover_url"],
            "shelf": r["shelf"],
            "rating": r["rating"],
            "date_added": r["date_added"],
        })
    return result
