#!/Users/waldo.vanderhaeghen/Library/Scripts/watcher-env/bin/python3
"""Ingest IMDb ratings + watchlist CSVs into entertainment.db."""

import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from db import get_conn, init_db

RAW = Path(__file__).parent.parent / "data" / "raw"
RATINGS_CSV  = RAW / "imdb_ratings.csv"
WATCHLIST_CSV = RAW / "imdb_watchlist.csv"

MEDIA_TYPE_MAP = {
    "Movie":         "film",
    "TV Movie":      "film",
    "TV Series":     "tv_show",
    "TV Mini Series":"tv_show",
    "TV Episode":    "tv_show",
    "Short":         "film",
    "Video":         "film",
}


def parse_genres(genres_str: str) -> str:
    """Comma-separated IMDb genres → JSON array."""
    if not genres_str:
        return "[]"
    genres = [g.strip() for g in genres_str.split(",") if g.strip()]
    return json.dumps(genres)


def upsert_item(conn, item_id: str, title: str, media_type: str, year: int | None,
                genres: str, runtime: int | None, director: str | None,
                source_id: str, imdb_rating: float | None) -> bool:
    cur = conn.execute("SELECT id FROM media_items WHERE id=?", (item_id,))
    if cur.fetchone():
        conn.execute(
            "UPDATE media_items SET title=?, media_type=?, year=?, genres=?, "
            "runtime_min=?, director=? WHERE id=?",
            (title, media_type, year, genres, runtime, director, item_id),
        )
        return False
    conn.execute(
        "INSERT INTO media_items (id, media_type, title, year, genres, runtime_min, "
        "director, source, source_id) VALUES (?,?,?,?,?,?,?,?,?)",
        (item_id, media_type, title, year, genres, runtime, director, "imdb", source_id),
    )
    return True


def ingest_ratings(conn) -> tuple[int, int]:
    if not RATINGS_CSV.exists():
        print("imdb_ratings.csv not found — skipping")
        return 0, 0
    inserted = updated = 0
    with open(RATINGS_CSV, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            const  = row["Const"].strip()
            title  = row["Title"].strip()
            rating = int(row["Your Rating"]) / 2  # 1-10 → 0.5-5.0
            date   = row.get("Date Rated", "").strip() or None
            year_s = row.get("Year", "").strip()
            year   = int(year_s) if year_s.isdigit() else None
            rt_s   = row.get("Runtime (mins)", "").strip()
            runtime = int(rt_s) if rt_s.isdigit() else None
            media_type = MEDIA_TYPE_MAP.get(row.get("Title Type", "Movie"), "film")
            genres = parse_genres(row.get("Genres", ""))
            director = row.get("Directors", "").strip() or None
            item_id = f"imdb:{const}"

            is_new = upsert_item(conn, item_id, title, media_type, year,
                                 genres, runtime, director, const, None)
            if is_new:
                inserted += 1
            else:
                updated += 1

            # Remove existing imdb interaction and re-insert (idempotent)
            conn.execute(
                "DELETE FROM user_interactions WHERE media_id=? AND source='imdb'",
                (item_id,),
            )
            conn.execute(
                "INSERT INTO user_interactions "
                "(media_id, interaction, rating, date_completed, source) VALUES (?,?,?,?,?)",
                (item_id, "rated", rating, date, "imdb"),
            )
    conn.commit()
    return inserted, updated


def ingest_watchlist(conn) -> tuple[int, int]:
    if not WATCHLIST_CSV.exists():
        print("imdb_watchlist.csv not found — skipping")
        return 0, 0
    inserted = updated = 0
    with open(WATCHLIST_CSV, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            const  = row["Const"].strip()
            title  = row["Title"].strip()
            year_s = row.get("Year", "").strip()
            year   = int(year_s) if year_s.isdigit() else None
            rt_s   = row.get("Runtime (mins)", "").strip()
            runtime = int(rt_s) if rt_s.isdigit() else None
            media_type = MEDIA_TYPE_MAP.get(row.get("Title Type", "Movie"), "film")
            genres = parse_genres(row.get("Genres", ""))
            director = row.get("Directors", "").strip() or None
            item_id = f"imdb:{const}"

            is_new = upsert_item(conn, item_id, title, media_type, year,
                                 genres, runtime, director, const, None)
            if is_new:
                inserted += 1
            else:
                updated += 1

            # Only add watchlist interaction if item not already rated
            existing = conn.execute(
                "SELECT id FROM user_interactions WHERE media_id=? AND source='imdb'",
                (item_id,),
            ).fetchone()
            if not existing:
                date_added = row.get("Created", "").strip()[:10] or None
                conn.execute(
                    "INSERT INTO user_interactions "
                    "(media_id, interaction, date_added, source) VALUES (?,?,?,?)",
                    (item_id, "want", date_added, "imdb"),
                )
    conn.commit()
    return inserted, updated


def main():
    conn = get_conn()
    init_db(conn)

    ins, upd = ingest_ratings(conn)
    print(f"IMDb ratings: {ins} inserted, {upd} updated")

    ins2, upd2 = ingest_watchlist(conn)
    print(f"IMDb watchlist: {ins2} inserted, {upd2} updated")

    # Verification
    row = conn.execute(
        "SELECT count(*) n, avg(rating) avg_r FROM user_interactions "
        "WHERE source='imdb' AND rating IS NOT NULL"
    ).fetchone()
    print(f"Verification: {row['n']} rated films/shows, mean {row['avg_r']:.2f}/5 ({row['avg_r']*2:.2f}/10)")

    types = conn.execute(
        "SELECT media_type, count(*) n FROM media_items WHERE source='imdb' GROUP BY media_type"
    ).fetchall()
    for t in types:
        print(f"  {t['media_type']}: {t['n']}")


if __name__ == "__main__":
    main()
