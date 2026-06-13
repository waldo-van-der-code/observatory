#!/usr/bin/env python3
"""Ingest Goodreads CSV + Audible JSON stub into entertainment.db."""

import csv
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from db import get_conn, init_db

RAW = Path(__file__).parent.parent / "data" / "raw"
GOODREADS_CSV = RAW / "goodreads_import.csv"
AUDIBLE_JSON  = RAW / "audible_extra.json"

SERIES_RE = re.compile(r'\(([^,;#()]+),\s*#(\d+(?:\.\d+)?)')


def parse_series(title: str) -> tuple[str | None, float | None]:
    m = SERIES_RE.search(title)
    if m:
        return m.group(1).strip(), float(m.group(2))
    return None, None


def clean_isbn(raw: str) -> str | None:
    """Strip Excel-safe =""..."""" quoting."""
    s = raw.strip().lstrip('=').strip('"')
    return s if s else None


def ingest_goodreads(conn) -> tuple[int, int]:
    inserted = updated = 0
    with open(GOODREADS_CSV, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            book_id   = row["Book Id"].strip()
            title_raw = row["Title"].strip()
            rating    = int(row["My Rating"]) or None
            shelf     = row["Exclusive Shelf"].strip()
            year_pub  = row["Original Publication Year"].strip() or row["Year Published"].strip()
            year      = int(year_pub) if year_pub.isdigit() else None
            date_read = row["Date Read"].strip().replace("/", "-") or None
            date_add  = row["Date Added"].strip().replace("/", "-") or None
            pages_raw = row["Number of Pages"].strip()
            pages     = int(pages_raw) if pages_raw.isdigit() else None

            series_name, series_pos = parse_series(title_raw)
            # Strip series annotation from title for cleaner display
            title_clean = re.sub(r'\s*\([^)]+\)\s*$', '', title_raw).strip() or title_raw

            item_id = f"gr:{book_id}"
            cur = conn.execute(
                "SELECT id FROM media_items WHERE id = ?", (item_id,)
            )
            if cur.fetchone():
                conn.execute(
                    "UPDATE media_items SET title=?, author=?, year=?, page_count=?, "
                    "series_name=?, series_pos=? WHERE id=?",
                    (title_clean, row["Author"].strip(), year, pages,
                     series_name, series_pos, item_id),
                )
                updated += 1
            else:
                conn.execute(
                    "INSERT INTO media_items "
                    "(id, media_type, title, author, year, page_count, series_name, series_pos, source, source_id) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (item_id, "book", title_clean, row["Author"].strip(), year, pages,
                     series_name, series_pos, "goodreads", book_id),
                )
                inserted += 1

            interaction = {
                "read": "completed",
                "to-read": "want",
                "currently-reading": "reading",
            }.get(shelf, "completed")

            conn.execute(
                "DELETE FROM user_interactions WHERE media_id=? AND source='goodreads'",
                (item_id,),
            )
            conn.execute(
                "INSERT INTO user_interactions "
                "(media_id, interaction, rating, date_completed, date_added, shelf, source) "
                "VALUES (?,?,?,?,?,?,?)",
                (item_id, interaction, rating, date_read, date_add, shelf, "goodreads"),
            )

    conn.commit()
    return inserted, updated


def ingest_audible(conn) -> int:
    if not AUDIBLE_JSON.exists():
        print("audible_extra.json not found — skipping")
        return 0
    inserted = 0
    entries = json.loads(AUDIBLE_JSON.read_text())
    for e in entries:
        slug = re.sub(r'[^a-z0-9]+', '-', e["title"].lower()).strip('-')
        item_id = f"au:{slug}"
        cur = conn.execute("SELECT id FROM media_items WHERE id=?", (item_id,))
        if not cur.fetchone():
            conn.execute(
                "INSERT INTO media_items "
                "(id, media_type, title, author, year, series_name, series_pos, source) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (item_id, e.get("media_type", "audiobook"), e["title"],
                 e.get("author"), e.get("year"), e.get("series_name"), e.get("series_pos"),
                 "audible"),
            )
            conn.execute(
                "INSERT INTO user_interactions (media_id, interaction, source) VALUES (?,?,?)",
                (item_id, "completed", "audible"),
            )
            inserted += 1
    conn.commit()
    return inserted


def main():
    conn = get_conn()
    init_db(conn)

    gr_ins, gr_upd = ingest_goodreads(conn)
    print(f"Goodreads: {gr_ins} inserted, {gr_upd} updated")

    au_ins = ingest_audible(conn)
    print(f"Audible: {au_ins} inserted")

    row = conn.execute(
        "SELECT count(*) n, avg(rating) avg_r FROM user_interactions WHERE source='goodreads' AND rating IS NOT NULL"
    ).fetchone()
    print(f"Verification: {row['n']} rated books, mean rating {row['avg_r']:.2f}")

    total = conn.execute("SELECT count(*) FROM media_items").fetchone()[0]
    print(f"Total media_items: {total}")


if __name__ == "__main__":
    main()
