#!/usr/bin/env python3
"""Ratings Waldo set in the app or chat (OBS-054). Imports never touch this table.

Every rating write goes through set_rating(). user_interactions keeps carrying the current value so
existing readers stay right, and each importer calls reapply() in its own transaction, so the import
can delete and re-insert its rows without losing an in-app rating.
"""

from __future__ import annotations

import csv
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

# Numbers the importers made up for a like, a thumb or a subscription; Waldo never gave them (OBS-053).
INFERRED_RATINGS = {("justwatch_liked", 4.5): "liked", ("netflix", 4.0): "thumbs up",
                    ("netflix", 1.5): "thumbs down", ("pocket_casts", 3.0): "subscribed"}
# A real rating replacing one of those must stop looking like it, so the row's source changes too.
RERATE_SQL = "rating=?, source=CASE WHEN " + " OR ".join(
    f"(source='{source}' AND rating={value})" for source, value in INFERRED_RATINGS) + " THEN 'oracle' ELSE source END"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ph(seq) -> str:
    return ",".join("?" * len(seq))


def init_table(conn: sqlite3.Connection) -> None:
    """Safe inside a caller's transaction: creates the table and never commits."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS app_ratings (
            media_id      TEXT PRIMARY KEY,
            rating        REAL NOT NULL,
            rated_at      TEXT NOT NULL,
            origin        TEXT NOT NULL,
            import_rating REAL
        )""")


def state(conn: sqlite3.Connection, ids: list[str]) -> list[dict]:
    init_table(conn)
    return [dict(r) for r in conn.execute(
        f"SELECT * FROM app_ratings WHERE media_id IN ({_ph(ids)}) ORDER BY media_id", ids)] if ids else []


def _record(conn: sqlite3.Connection, media_id: str, rating: float, rated_at: str, origin: str) -> None:
    conn.execute(
        "INSERT INTO app_ratings (media_id, rating, rated_at, origin) VALUES (?,?,?,?) "
        "ON CONFLICT(media_id) DO UPDATE SET rating=excluded.rating, rated_at=excluded.rated_at, origin=excluded.origin",
        (media_id, rating, rated_at, origin))


def set_rating(conn: sqlite3.Connection, ids: list[str], rating: float, origin: str,
               insert_source: str = "oracle", completed: bool = False) -> None:
    """The one rating write, in the caller's transaction. ids are all imports of one work."""
    import my_ratings
    init_table(conn)
    now = _now()
    rated = [r[0] for r in conn.execute(
        f"SELECT DISTINCT media_id FROM user_interactions WHERE media_id IN ({_ph(ids)}) AND rating IS NOT NULL", ids)]
    if rated:
        conn.execute(f"UPDATE user_interactions SET {RERATE_SQL} WHERE media_id IN ({_ph(ids)}) AND rating IS NOT NULL",
                     [rating, *ids])
    else:
        conn.execute("INSERT INTO user_interactions (media_id, interaction, rating, date_added, date_completed, source) "
                     "VALUES (?,?,?,?,?,?)", (ids[0], "rated", rating, now, now if completed else None, insert_source))
    for media_id in rated or ids[:1]:
        _record(conn, media_id, rating, now, origin)
    my_ratings.assign_work_keys(conn)


def reapply(conn: sqlite3.Connection) -> int:
    """Put in-app ratings back after an import, in the importer's transaction. Returns rows corrected."""
    init_table(conn)
    corrected = 0
    for app in conn.execute("SELECT media_id, rating, rated_at FROM app_ratings").fetchall():
        media_id, rating = app[0], app[1]
        current = conn.execute("SELECT rating FROM user_interactions WHERE media_id=? AND rating IS NOT NULL ORDER BY id",
                               (media_id,)).fetchall()
        if not current:
            conn.execute("INSERT INTO user_interactions (media_id, interaction, rating, date_added, source) VALUES (?,?,?,?,?)",
                         (media_id, "rated", rating, app[2], "oracle"))
            corrected += 1
            continue
        differing = [r[0] for r in current if r[0] != rating]
        if differing:
            conn.execute("UPDATE app_ratings SET import_rating=? WHERE media_id=?", (differing[-1], media_id))
        conn.execute(f"UPDATE user_interactions SET {RERATE_SQL} WHERE media_id=? AND rating IS NOT NULL",
                     (rating, media_id))
        # An import re-adds a like or thumb that was already converted; keep one row per source
        conn.execute("""DELETE FROM user_interactions WHERE media_id=? AND rating IS NOT NULL AND id NOT IN
                        (SELECT min(id) FROM user_interactions WHERE media_id=? AND rating IS NOT NULL GROUP BY source)""",
                     (media_id, media_id))
        corrected += 1
    import my_ratings
    my_ratings.assign_work_keys(conn)
    return corrected


def backfill(conn: sqlite3.Connection) -> int:
    """Record applied chat ratings from before this table existed, and give their snapshots this table.

    Runs at startup; an action whose snapshot already covers app_ratings is skipped. A rating that was
    changed again later is left out and shows up in differences() instead.
    """
    init_table(conn)
    conn.execute("BEGIN IMMEDIATE")
    added = 0
    try:
        for row in conn.execute("SELECT id, action, updated_at, before_state, after_state FROM oracle_actions "
                                "WHERE status='applied' AND before_state IS NOT NULL AND after_state IS NOT NULL ORDER BY id").fetchall():
            before, after = json.loads(row["before_state"]), json.loads(row["after_state"])
            if "app_ratings" in after:
                continue
            ids = before["item_ids"]
            before["app_ratings"] = state(conn, ids)
            action = json.loads(row["action"])
            if action.get("action") == "rate":
                rating = action["rating"]
                for media_id in sorted({i["media_id"] for i in after["interactions"] if i["rating"] == rating}):
                    current = {r[0] for r in conn.execute(
                        "SELECT rating FROM user_interactions WHERE media_id=? AND rating IS NOT NULL", (media_id,))}
                    if current == {rating}:
                        _record(conn, media_id, rating, row["updated_at"], "chat")
                        added += 1
            after["app_ratings"] = state(conn, ids)
            conn.execute("UPDATE oracle_actions SET before_state=?, after_state=? WHERE id=?",
                         (json.dumps(before, ensure_ascii=False), json.dumps(after, ensure_ascii=False), row["id"]))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return added


def differences(conn: sqlite3.Connection, imdb_csv: Path, goodreads_csv: Path) -> list[dict]:
    """Rated rows with no in-app record whose value no export explains, for Waldo to judge."""
    init_table(conn)
    exports: dict[str, float | None] = {}
    if imdb_csv.exists():
        with imdb_csv.open(newline="", encoding="utf-8-sig") as f:
            exports.update({f"imdb:{r['Const'].strip()}": int(r["Your Rating"]) / 2 for r in csv.DictReader(f)})
    if goodreads_csv.exists():
        with goodreads_csv.open(newline="", encoding="utf-8-sig") as f:
            exports.update({f"gr:{r['Book Id'].strip()}": int(r["My Rating"]) or None for r in csv.DictReader(f)})
    out = []
    for r in conn.execute("""
            SELECT ui.media_id, ui.rating, ui.source, ui.date_added, m.title, m.year, m.media_type
            FROM user_interactions ui JOIN media_items m ON m.id=ui.media_id
            WHERE ui.rating IS NOT NULL AND m.media_type<>'tv_episode'
              AND ui.media_id NOT IN (SELECT media_id FROM app_ratings)
            ORDER BY m.title"""):
        if (r["source"], r["rating"]) in INFERRED_RATINGS:
            continue
        export = exports.get(r["media_id"])
        if export != r["rating"]:
            out.append({**dict(r), "export": export})
    return out


def adopt(conn: sqlite3.Connection, ids: list[str]) -> None:
    """Keep a listed rating as in-app, after Waldo chose that. In the caller's transaction."""
    init_table(conn)
    for media_id in ids:
        rows = conn.execute("SELECT rating, date_added FROM user_interactions WHERE media_id=? AND rating IS NOT NULL",
                            (media_id,)).fetchall()
        values = {r[0] for r in rows}
        if len(values) != 1:
            raise ValueError(f"{media_id}: expected one rating value, found {sorted(values)}")
        dates = [r[1] for r in rows if r[1]]
        _record(conn, media_id, values.pop(), max(dates) if dates else _now(), "adopted")


def main() -> None:
    from db import get_conn
    raw = Path(__file__).parent.parent / "data" / "raw"
    conn = get_conn()
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "differences":
        print(json.dumps(differences(conn, raw / "imdb_ratings.csv", raw / "goodreads_import.csv"), ensure_ascii=False, indent=1))
    elif command == "adopt" and sys.argv[2:]:
        adopt(conn, sys.argv[2:])
        conn.commit()
        print(f"adopted {len(sys.argv) - 2}")
    elif command == "set" and len(sys.argv) == 4:
        set_rating(conn, [sys.argv[2]], float(sys.argv[3]), "adopted")
        conn.commit()
        print(f"set {sys.argv[2]} to {sys.argv[3]}")
    else:
        sys.exit("usage: app_ratings.py differences | adopt <media_id> ... | set <media_id> <0.5 to 5>")


if __name__ == "__main__":
    main()
