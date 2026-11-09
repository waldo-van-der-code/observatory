"""OBS-054 step 1: ratings set in the app or chat survive a re-import, with undo. Offline, temp DB."""

from __future__ import annotations

import csv
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]
failures = 0
checks = 0


def check(label, condition, info=""):
    global failures, checks
    checks += 1
    print(f"{'PASS' if condition else 'FAIL'} OBS-054: {label}" + (f" ({info})" if not condition and info else ""))
    failures += not condition


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def imdb_row(const, title, rating, year=2000, kind="Movie"):
    return {"Const": const, "Your Rating": rating, "Date Rated": "2026-03-08", "Title": title, "Year": year,
            "Runtime (mins)": 100, "Title Type": kind, "Genres": "Drama", "Directors": "Someone"}


def goodreads_row(book_id, title, rating):
    return {"Book Id": book_id, "Title": title, "Author": "An Author", "My Rating": rating, "Exclusive Shelf": "read",
            "Original Publication Year": 2010, "Year Published": 2010, "Date Read": "2024/01/02",
            "Date Added": "2024/01/01", "Number of Pages": 300}


with tempfile.TemporaryDirectory(prefix="obs-054-eval-") as folder:
    tmp = Path(folder)
    os.environ["OBS_DB_PATH"] = str(tmp / "test.db")
    os.environ["OBS_CLAUDE_TOKEN_FILE"] = str(tmp / "no-token")

    from fastapi.testclient import TestClient
    import server
    import oracle_actions as actions
    import ingest_films
    import ingest_books
    import ingest_netflix
    import ingest_justwatch
    from db import get_conn

    try:
        import app_ratings
    except ImportError:
        app_ratings = None

    ingest_films.RATINGS_CSV = tmp / "imdb.csv"
    ingest_films.WATCHLIST_CSV = tmp / "no-watchlist.csv"
    ingest_books.GOODREADS_CSV = tmp / "goodreads.csv"
    ingest_netflix.VIEWING_CSV = tmp / "no-viewing.csv"
    ingest_netflix.RATINGS_CSV = tmp / "netflix.csv"
    ingest_justwatch.SEEN_CSV = tmp / "no-seen.csv"
    ingest_justwatch.LIKED_CSV = tmp / "liked.csv"

    netflix_rows = [{"Profile Name": "wally", "Title Name": "Thumb Show", "Thumbs Value": "3", "Event Utc Ts": "2026-01-01 10:00:00"}]
    liked_rows = [{"title": "Liked Film", "original_title": "Liked Film", "year": 2015, "type": "movie"}]

    def import_all(heat=7, control=6, book=4):
        write_csv(ingest_films.RATINGS_CSV, [imdb_row("tt1", "Heat", heat, 1995), imdb_row("tt2", "Control", control, 2007)])
        write_csv(ingest_books.GOODREADS_CSV, [goodreads_row("11", "A Book", book)])
        write_csv(ingest_netflix.RATINGS_CSV, netflix_rows)
        write_csv(ingest_justwatch.LIKED_CSV, liked_rows)
        conn = get_conn()
        ingest_films.ingest_ratings(conn)
        ingest_books.ingest_goodreads(conn)
        ingest_netflix.ingest_ratings(conn)
        ingest_justwatch.ingest_liked(conn)
        conn.close()

    def ratings(media_id):
        conn = get_conn()
        rows = conn.execute("SELECT rating, source FROM user_interactions WHERE media_id=? AND rating IS NOT NULL ORDER BY id",
                            (media_id,)).fetchall()
        conn.close()
        return [(r["rating"], r["source"]) for r in rows]

    def app_row(media_id):
        conn = get_conn()
        try:
            row = conn.execute("SELECT * FROM app_ratings WHERE media_id=?", (media_id,)).fetchone()
        except Exception:
            row = None
        conn.close()
        return dict(row) if row else None

    def chat(action):
        """Apply a rating the way the reviewed chat queue does, returning the action id."""
        action = {"year": None, "user_quote": "as asked", **action}
        conn = get_conn()
        target, why = actions.resolve(conn, action)
        assert target, why
        cur = conn.execute(
            "INSERT INTO oracle_actions (created_at, updated_at, user_message, action, target, status) VALUES (?,?,?,?,?,?)",
            ("2026-11-09T10:00:00Z", "2026-11-09T10:00:00Z", "as asked", json.dumps(action), json.dumps(target), "reviewing"))
        row = dict(conn.execute("SELECT * FROM oracle_actions WHERE id=?", (cur.lastrowid,)).fetchone())
        conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        why = actions._apply_resolved(conn, row, "approved")
        assert why is None, why
        conn.commit()
        conn.close()
        return row["id"]

    with TestClient(server.app, raise_server_exceptions=False) as client:
        import_all()

        # One write path, real timestamps
        result = client.post("/api/rate", json={"title": "Heat", "year": 1995, "media_type": "film", "rating": 4.5})
        check("/api/rate saves", result.status_code == 200, result.text)
        row = app_row("imdb:tt1")
        check("/api/rate lands in app_ratings", bool(row) and row["rating"] == 4.5 and row["origin"] == "rate", row)
        check("the app rating has a real timestamp",
              bool(row) and row["rated_at"][:10] == datetime.now(timezone.utc).strftime("%Y-%m-%d"), row)

        client.post("/api/rate", json={"title": "A Book", "year": 2010, "media_type": "book", "rating": 5.0})
        client.post("/api/rate", json={"title": "Thumb Show", "media_type": "film", "rating": 3.0})
        client.post("/api/rate", json={"title": "Liked Film", "year": 2015, "media_type": "film", "rating": 2.5})

        result = client.post("/api/interactions", json={"item_id": "imdb:tt2", "interaction_type": "rating", "value": "2.5"})
        check("/api/interactions saves", result.status_code == 200, result.text)
        row = app_row("imdb:tt2")
        check("/api/interactions lands in app_ratings",
              bool(row) and row["rating"] == 2.5 and row["origin"] == "interactions", row)

        # The core promise
        import_all()
        check("re-import keeps a newer in-app rating on IMDb", ratings("imdb:tt1") == [(4.5, "imdb")], ratings("imdb:tt1"))
        check("re-import keeps a rating from /api/interactions", ratings("imdb:tt2") == [(2.5, "imdb")], ratings("imdb:tt2"))
        check("re-import keeps a newer in-app rating on Goodreads", ratings("gr:11") == [(5.0, "goodreads")], ratings("gr:11"))
        check("re-import keeps an in-app rating over a Netflix thumb, in one row",
              ratings("netflix:thumb-show") == [(3.0, "oracle")], ratings("netflix:thumb-show"))
        check("re-import keeps an in-app rating over a JustWatch like, in one row",
              ratings("jw:liked_film:2015") == [(2.5, "oracle")], ratings("jw:liked_film:2015"))
        check("a second re-import adds nothing", (import_all() or ratings("netflix:thumb-show")) == [(3.0, "oracle")],
              ratings("netflix:thumb-show"))
        row = app_row("imdb:tt1")
        check("the export's own value stays visible next to the in-app one", bool(row) and row.get("import_rating") == 3.5, row)

        write_csv(ingest_films.RATINGS_CSV, [imdb_row("tt1", "Heat", 7, 1995), imdb_row("tt2", "Control", 6, 2007),
                                             imdb_row("tt3", "New Film", 9, 2024)])
        conn = get_conn()
        ingest_films.ingest_ratings(conn)
        conn.close()
        check("an export rating without an in-app one still imports", ratings("imdb:tt3") == [(4.5, "imdb")], ratings("imdb:tt3"))

        # Undo across the new table
        before = app_row("imdb:tt3")
        action_id = chat({"action": "rate", "title": "New Film", "year": 2024, "media_type": "film", "rating": 1.0})
        row = app_row("imdb:tt3")
        check("a chat rating lands in app_ratings", bool(row) and row["rating"] == 1.0 and row["origin"] == "chat", row)
        conn = get_conn()
        ok, why = actions.undo(conn, action_id)
        conn.close()
        check("undo succeeds", ok, why)
        check("undo restores the rating", ratings("imdb:tt3") == [(4.5, "imdb")], ratings("imdb:tt3"))
        check("undo removes the app rating it added", app_row("imdb:tt3") == before, app_row("imdb:tt3"))

        action_id = chat({"action": "rate", "title": "Heat", "year": 1995, "media_type": "film", "rating": 1.5})
        check("a second in-app rating replaces the first", app_row("imdb:tt1")["rating"] == 1.5, app_row("imdb:tt1"))
        conn = get_conn()
        ok, why = actions.undo(conn, action_id)
        conn.close()
        restored = app_row("imdb:tt1")
        check("undo brings back the earlier app rating", ok and restored["rating"] == 4.5 and restored["origin"] == "rate", (why, restored))

        action_id = chat({"action": "rate", "title": "Fresh Unknown", "year": 2020, "media_type": "film", "rating": 4.0})
        conn = get_conn()
        new_id = json.loads(conn.execute("SELECT before_state FROM oracle_actions WHERE id=?", (action_id,)).fetchone()[0])["created_item"]
        conn.close()
        check("a chat rating on a new title lands in app_ratings", bool(app_row(new_id)), new_id)
        conn = get_conn()
        ok, why = actions.undo(conn, action_id)
        gone = conn.execute("SELECT 1 FROM media_items WHERE id=?", (new_id,)).fetchone() is None
        conn.close()
        check("undo of a new title removes item and app rating", ok and gone and app_row(new_id) is None, why)

        action_id = chat({"action": "rate", "title": "Control", "year": 2007, "media_type": "film", "rating": 3.5})
        conn = get_conn()
        conn.execute("UPDATE app_ratings SET rated_at='2030-01-01T00:00:00Z' WHERE media_id='imdb:tt2'")
        conn.commit()
        ok, why = actions.undo(conn, action_id)
        conn.close()
        check("undo is refused when only the app rating changed since", not ok and "changed again" in why, why)

        # Backfill from earlier chat actions
        conn = get_conn()
        conn.executemany("INSERT INTO media_items (id,media_type,title,year,source,source_id) VALUES (?,?,?,?,?,?)", [
            ("old:a", "film", "Old Chat", 2001, "imdb", "a"), ("old:b", "film", "Later Changed", 2002, "imdb", "b"),
            ("old:c", "film", "Was Undone", 2003, "imdb", "c"), ("old:d", "film", "Old Seen", 2004, "imdb", "d"),
        ])
        conn.executemany("INSERT INTO user_interactions (media_id,interaction,rating,source) VALUES (?,?,?,?)", [
            ("old:a", "rated", 4.0, "imdb"), ("old:b", "rated", 2.0, "imdb"), ("old:c", "rated", 3.0, "imdb"),
        ])

        def old_action(kind, title, rating, ids, status, stamp, after_rating):
            interactions = lambda r: [{"id": 1, "media_id": ids[0], "interaction": "rated", "rating": r, "date_completed": None,
                                       "date_added": None, "shelf": None, "source": "imdb"}]
            before = {"item_ids": ids, "pick_ids": [], "created_item": None, "interactions": interactions(1.0), "picks": []}
            after = {"interactions": interactions(after_rating), "picks": []}
            action = {"action": kind, "title": title, "media_type": "film", "year": 2001, "user_quote": "x"}
            if rating is not None:
                action["rating"] = rating
            return conn.execute(
                "INSERT INTO oracle_actions (created_at, updated_at, user_message, action, target, status, before_state, after_state) VALUES (?,?,?,?,?,?,?,?)",
                (stamp, stamp, "x", json.dumps(action), json.dumps({"item_ids": ids}), status, json.dumps(before), json.dumps(after))).lastrowid

        real_id = conn.execute("SELECT id FROM user_interactions WHERE media_id='old:a'").fetchone()[0]
        old_a = old_action("rate", "Old Chat", 4.0, ["old:a"], "applied", "2026-11-01T08:00:00Z", 4.0)
        old_action("rate", "Later Changed", 4.5, ["old:b"], "applied", "2026-11-02T08:00:00Z", 4.5)
        old_action("rate", "Was Undone", 5.0, ["old:c"], "undone", "2026-11-03T08:00:00Z", 5.0)
        old_action("mark_seen", "Old Seen", None, ["old:d"], "applied", "2026-11-04T08:00:00Z", 1.0)
        conn.commit()

        added = app_ratings.backfill(conn) if app_ratings else -1
        row = app_row("old:a")
        check("backfill records an applied chat rating with its own time",
              bool(row) and row["rating"] == 4.0 and row["rated_at"] == "2026-11-01T08:00:00Z" and row["origin"] == "chat", row)
        check("backfill skips a rating changed again later", app_row("old:b") is None, app_row("old:b"))
        check("backfill skips an undone action", app_row("old:c") is None, app_row("old:c"))
        check("backfill adds nothing for a non-rating action", app_row("old:d") is None, app_row("old:d"))
        check("backfill counted one rating", added == 1, added)
        check("backfill is idempotent", app_ratings is not None and app_ratings.backfill(conn) == 0)

        # Regression OBS-054: one applied row without snapshots must not stop the server from starting
        conn.execute("INSERT INTO oracle_actions (created_at, updated_at, user_message, action, target, status) VALUES (?,?,?,?,?,?)",
                     ("2026-11-05T08:00:00Z", "2026-11-05T08:00:00Z", "x", json.dumps({"action": "rate", "rating": 3.0}), "{}", "applied"))
        conn.commit()
        try:
            crashed = None
            app_ratings.backfill(conn)
        except Exception as e:
            crashed = repr(e)
        check("backfill survives an applied row without snapshots", crashed is None, crashed)

        # Undo still works on an action from before the new table existed
        for column in ("before_state", "after_state"):
            snapshot = json.loads(conn.execute(f"SELECT {column} FROM oracle_actions WHERE id=?", (old_a,)).fetchone()[0])
            snapshot["interactions"][0]["id"] = real_id
            conn.execute(f"UPDATE oracle_actions SET {column}=? WHERE id=?", (json.dumps(snapshot), old_a))
        conn.commit()
        ok, why = actions.undo(conn, old_a)
        check("undo works on a backfilled action", ok and app_row("old:a") is None, why)
        conn.close()

        # Unrecorded differences are listed, never guessed
        conn = get_conn()
        conn.executemany("INSERT INTO media_items (id,media_type,title,year,source,source_id) VALUES (?,?,?,?,?,?)", [
            ("imdb:tt9", "film", "Changed Silently", 1999, "imdb", "tt9"), ("imdb:tt8", "film", "Same As Export", 1998, "imdb", "tt8"),
            ("pod:x", "podcast", "A Podcast", None, "manual", "x"), ("old:e", "tv_episode", "An Episode", 2000, "tmdb", "e"),
            ("imdb:tt7", "film", "No Source Row", 1997, "imdb", "tt7"),
        ])
        conn.executemany("INSERT INTO user_interactions (media_id,interaction,rating,source) VALUES (?,?,?,?)", [
            ("imdb:tt9", "rated", 5.0, "imdb"), ("imdb:tt8", "rated", 2.0, "imdb"), ("pod:x", "completed", 4.0, "manual"),
            ("old:e", "rated", 4.0, "tmdb"), ("imdb:tt7", "rated", 5.0, None),
        ])
        conn.commit()
        write_csv(ingest_films.RATINGS_CSV, [imdb_row("tt1", "Heat", 7, 1995), imdb_row("tt2", "Control", 6, 2007), imdb_row("tt3", "New Film", 9, 2024),
                                             imdb_row("tt9", "Changed Silently", 6, 1999), imdb_row("tt8", "Same As Export", 4, 1998),
                                             imdb_row("tt7", "No Source Row", 8, 1997)])
        found = {d["media_id"]: d for d in app_ratings.differences(conn, ingest_films.RATINGS_CSV, ingest_books.GOODREADS_CSV)} if app_ratings else {}
        check("a silent change is listed", found.get("imdb:tt9", {}).get("export") == 3.0, found.get("imdb:tt9"))
        check("a value matching the export is not listed", "imdb:tt8" not in found, found.get("imdb:tt8"))
        check("a rating no export knows is listed", found.get("pod:x", {}).get("export") is None and "pod:x" in found, found.get("pod:x"))
        check("episode rows are not listed", "old:e" not in found)
        check("a sourceless rating is compared with the export for its id", found.get("imdb:tt7", {}).get("export") == 4.0, found.get("imdb:tt7"))
        check("a rating already recorded in app_ratings is not listed", "imdb:tt1" not in found, found.get("imdb:tt1"))

        if app_ratings:
            app_ratings.adopt(conn, ["imdb:tt9"])
            conn.commit()
        row = app_row("imdb:tt9")
        check("a difference Waldo keeps is recorded and marked as adopted", bool(row) and row["rating"] == 5.0 and row["origin"] == "adopted", row)
        conn.close()
        write_csv(ingest_films.RATINGS_CSV, [imdb_row("tt9", "Changed Silently", 6, 1999)])
        conn = get_conn()
        ingest_films.ingest_ratings(conn)
        conn.close()
        check("an adopted rating survives the next import", ratings("imdb:tt9") == [(5.0, "imdb")], ratings("imdb:tt9"))

print(f"\n{checks - failures}/{checks} passed")
sys.exit(1 if failures else 0)
