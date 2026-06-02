#!/Users/waldo.vanderhaeghen/Library/Scripts/watcher-env/bin/python3
"""Ingest Audible finished books CSV into entertainment.db.

For books already in DB (from Goodreads), marks them as also listened.
For books not in DB, inserts them as new audiobook items.
"""

import csv
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from db import get_conn, init_db

AUDIBLE_CSV = Path("/Users/waldo.vanderhaeghen/Documents/AI-projects-personal/Fun!/books/audible_finished.csv")

SERIES_MAP = {
    "Red Rising": ("Red Rising Saga", 1),
    "Golden Son": ("Red Rising Saga", 2),
    "Morning Star": ("Red Rising Saga", 3),
    "Iron Gold": ("Red Rising Saga", 4),
    "Dark Age": ("Red Rising Saga", 5),
    "Hyperion": ("Hyperion Cantos", 1),
    "The Fall of Hyperion": ("Hyperion Cantos", 2),
    "Endymion": ("Hyperion Cantos", 3),
    "We Are Legion (We Are Bob)": ("Bobiverse", 1),
    "For We Are Many": ("Bobiverse", 2),
    "All These Worlds": ("Bobiverse", 3),
    "Heaven's River": ("Bobiverse", 4),
    "All Systems Red": ("The Murderbot Diaries", 1),
    "Storm Front": ("The Dresden Files", 1),
    "Fool Moon": ("The Dresden Files", 2),
    "Grave Peril": ("The Dresden Files", 3),
    "Summer Knight": ("The Dresden Files", 4),
    "The Three-Body Problem": ("Remembrance of Earth's Past", 1),
    "The Dark Forest": ("Remembrance of Earth's Past", 2),
    "Death's End": ("Remembrance of Earth's Past", 3),
    "The Will of the Many": ("Hierarchy", 1),
    "The Wee Free Men": ("Discworld", 30),
    "A Hat Full of Sky": ("Discworld", 32),
    "Wintersmith": ("Discworld", 35),
    "I Shall Wear Midnight": ("Discworld", 38),
    "The Shepherd's Crown": ("Discworld", 41),
    "Night Watch": ("Discworld", 29),
    "Thud!": ("Discworld", 34),
    "Making Money": ("Discworld", 36),
    "Raising Steam": ("Discworld", 40),
}


def slug(title: str) -> str:
    return re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')


def find_in_db(conn, title: str) -> str | None:
    """Return media_items.id if title exists (case-insensitive), else None."""
    row = conn.execute(
        "SELECT id FROM media_items WHERE lower(title)=lower(?) AND media_type='book'",
        (title.strip(),),
    ).fetchone()
    if row:
        return row["id"]
    # Try without subtitle (everything after ':')
    short = title.split(":")[0].strip()
    if short != title:
        row = conn.execute(
            "SELECT id FROM media_items WHERE lower(title) LIKE lower(?||'%') AND media_type='book'",
            (short,),
        ).fetchone()
        if row:
            return row["id"]
    return None


def main():
    conn = get_conn()
    init_db(conn)

    # Remove the old 4-book stub entries
    old_ids = [r["id"] for r in conn.execute(
        "SELECT id FROM media_items WHERE source='audible'"
    ).fetchall()]
    for oid in old_ids:
        conn.execute("DELETE FROM user_interactions WHERE media_id=?", (oid,))
        conn.execute("DELETE FROM media_items WHERE id=?", (oid,))
    conn.commit()

    matched = new_items = already_noted = 0

    with open(AUDIBLE_CSV, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            title  = row["title"].strip()
            author = row["author"].strip() if row.get("author") else None
            if not title:
                continue

            existing_id = find_in_db(conn, title)
            if existing_id:
                # Already in DB from Goodreads — add audible tag if not already there
                ex = conn.execute(
                    "SELECT id FROM user_interactions WHERE media_id=? AND source='audible'",
                    (existing_id,),
                ).fetchone()
                if not ex:
                    conn.execute(
                        "INSERT INTO user_interactions (media_id, interaction, source) VALUES (?,?,?)",
                        (existing_id, "listened", "audible"),
                    )
                    matched += 1
                else:
                    already_noted += 1
            else:
                # New book — insert
                item_id = f"au:{slug(title)}"
                series_name, series_pos = SERIES_MAP.get(title, (None, None))
                conn.execute(
                    "INSERT OR IGNORE INTO media_items "
                    "(id, media_type, title, author, series_name, series_pos, source) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (item_id, "book", title, author, series_name, series_pos, "audible"),
                )
                conn.execute(
                    "INSERT INTO user_interactions (media_id, interaction, source) VALUES (?,?,?)",
                    (item_id, "completed", "audible"),
                )
                new_items += 1

    conn.commit()
    total = conn.execute("SELECT count(*) FROM media_items WHERE media_type='book'").fetchone()[0]
    print(f"Audible: {matched} matched to existing books, {new_items} new, {already_noted} already noted")
    print(f"Total books in DB: {total}")


if __name__ == "__main__":
    main()
