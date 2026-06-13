#!/usr/bin/env python3
"""Shared database setup for the entertainment dashboard."""

import json
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "processed" / "entertainment.db"


def get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
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

        CREATE TABLE IF NOT EXISTS tiktok_videos (
            video_id                   TEXT PRIMARY KEY,
            url                        TEXT NOT NULL,
            title                      TEXT,
            description                TEXT,
            hashtags                   TEXT,
            categories                 TEXT,
            enrichment_status          TEXT CHECK (
                enrichment_status IS NULL OR
                enrichment_status IN ('pending', 'success', 'failed', 'skipped')
            ),
            enrichment_error           TEXT,
            enrichment_attempts        INTEGER DEFAULT 0,
            last_enrichment_attempt_at TEXT,
            raw_metadata_json          TEXT,
            enriched_at                TEXT
        );

        CREATE TABLE IF NOT EXISTS tiktok_interactions (
            source_key       TEXT PRIMARY KEY,
            video_id         TEXT NOT NULL,
            raw_url          TEXT NOT NULL,
            interaction_type TEXT NOT NULL CHECK (interaction_type IN ('watched', 'liked', 'favorited')),
            rating           INTEGER NOT NULL CHECK (rating IN (2, 4, 5)),
            interaction_date TEXT NOT NULL,
            source_list      TEXT,
            source_index     INTEGER
        );

        CREATE TABLE IF NOT EXISTS tiktok_unparsed_urls (
            source_key       TEXT PRIMARY KEY,
            raw_url          TEXT NOT NULL,
            interaction_type TEXT,
            interaction_date TEXT,
            source_list      TEXT,
            source_index     INTEGER,
            reason           TEXT,
            created_at       TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_tiktok_int_video_id ON tiktok_interactions(video_id);
        CREATE INDEX IF NOT EXISTS idx_tiktok_int_type     ON tiktok_interactions(interaction_type);
        CREATE INDEX IF NOT EXISTS idx_tiktok_int_date     ON tiktok_interactions(interaction_date);
        CREATE INDEX IF NOT EXISTS idx_tiktok_vid_status   ON tiktok_videos(enrichment_status);

        CREATE TABLE IF NOT EXISTS youtube_videos (
            video_id     TEXT PRIMARY KEY,
            title        TEXT,
            channel      TEXT,
            duration_sec INTEGER,
            url          TEXT
        );

        CREATE TABLE IF NOT EXISTS youtube_watch_events (
            event_id     TEXT PRIMARY KEY,
            video_id     TEXT NOT NULL,
            watched_at   TEXT NOT NULL,
            source       TEXT,
            source_index INTEGER,
            FOREIGN KEY(video_id) REFERENCES youtube_videos(video_id)
        );

        CREATE TABLE IF NOT EXISTS youtube_video_enrichment (
            video_id         TEXT PRIMARY KEY,
            ambient_class    TEXT,
            ambient_reason   TEXT,
            ambient_source   TEXT,
            topics           TEXT,
            enrichment_model TEXT,
            prompt_version   TEXT,
            enriched_at      TEXT,
            FOREIGN KEY(video_id) REFERENCES youtube_videos(video_id)
        );

        CREATE TABLE IF NOT EXISTS youtube_chapters (
            chapter_id    TEXT PRIMARY KEY,
            start_date    TEXT,
            end_date      TEXT,
            name          TEXT,
            summary       TEXT,
            evidence_json TEXT
        );

        CREATE TABLE IF NOT EXISTS youtube_chapter_evidence (
            chapter_id TEXT,
            video_id   TEXT,
            weight     REAL,
            reason     TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_yt_events_video ON youtube_watch_events(video_id);
        CREATE INDEX IF NOT EXISTS idx_yt_events_date  ON youtube_watch_events(watched_at);
        CREATE INDEX IF NOT EXISTS idx_yt_enrich_class ON youtube_video_enrichment(ambient_class);
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
