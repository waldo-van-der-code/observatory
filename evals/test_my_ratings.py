"""OBS-054 step 3a: the my_ratings view, one row per work with one trustworthy score. Offline, temp DB."""

from __future__ import annotations

import json
import os
import sys
import tempfile
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


with tempfile.TemporaryDirectory(prefix="obs-054-eval-") as folder:
    os.environ["OBS_DB_PATH"] = str(Path(folder) / "test.db")

    from db import get_conn, init_db
    import app_ratings
    import oracle_actions

    try:
        import my_ratings
    except ImportError as e:
        my_ratings = None
        check("my_ratings module imports", False, f"ImportError: {e}")

    conn = get_conn()
    init_db(conn)
    app_ratings.init_table(conn)
    if my_ratings:
        my_ratings.init(conn)

    def media(item_id, media_type, title, year=2000, source="imdb"):
        conn.execute("INSERT INTO media_items (id,media_type,title,year,source,source_id) VALUES (?,?,?,?,?,?)",
                     (item_id, media_type, title, year, source, item_id))

    def rated(media_id, rating, source, date="2026-02-01"):
        conn.execute("INSERT INTO user_interactions (media_id,interaction,rating,date_added,source) VALUES (?,?,?,?,?)",
                     (media_id, "rated", rating, date, source))

    def rows(where=""):
        try:
            return [dict(r) for r in conn.execute("SELECT * FROM my_ratings" + (f" {where}" if where else ""))]
        except Exception as e:
            check("my_ratings view reads", False, repr(e))
            return []

    def reset():
        for table in ("app_ratings", "user_interactions", "media_items"):
            conn.execute(f"DELETE FROM {table}")
        conn.commit()

    if my_ratings:
        reset()
        # Three imports of one work: an explicit IMDb score, a Netflix thumb and a JustWatch like
        media("imdb:mm1", "film", "The Matrix", 1999)
        media("netflix:mm2", "film", "the matrix", None, source="netflix")
        media("jw:mm3", "film", "The  Matrix", None, source="justwatch")
        rated("imdb:mm1", 3.5, "imdb", "2026-01-02")
        rated("netflix:mm2", 4.0, "netflix", "2026-05-05")
        rated("jw:mm3", 4.5, "justwatch_liked", "2026-06-06")
        my_ratings.assign_work_keys(conn)
        got = rows()
        check("three imports give one row", len(got) == 1, got)
        check("the IMDb score wins, the thumb stays only a signal",
              got and got[0]["rating"] == 3.5 and got[0]["rating_source"] == "imdb", got)
        check("the like/thumb signal is visible", bool(got and got[0]["signal"]), got)
        check("the row keeps the dated title and lists every member id",
              bool(got) and got[0]["title"] == "The Matrix" and got[0]["year"] == 1999
              and sorted(json.loads(got[0]["member_ids"])) == ["imdb:mm1", "jw:mm3", "netflix:mm2"]
              and got[0]["conflict"] == 0, got)
        reset()

        # Only a like: the row exists with rating NULL, no invented number
        media("jw:l1", "film", "Solo Film", 2019)
        rated("jw:l1", 4.5, "justwatch_liked", "2026-06-06")
        my_ratings.assign_work_keys(conn)
        got = rows()
        check("only a like: one row with rating NULL and signal 'liked'",
              len(got) == 1 and got[0]["rating"] is None and got[0]["signal"] == "liked", got)
        check("signal only means no conflict either",
              bool(got) and got[0]["conflict"] == 0 and got[0]["export_rating"] is None, got)
        reset()

        # An in-app rating beats the IMDb row; the export's own value surfaces next to it
        media("imdb:h1", "film", "Heat", 1995)
        rated("imdb:h1", 3.5, "imdb", "2026-01-01")
        app_ratings.set_rating(conn, ["imdb:h1"], 4.0, "chat")
        got = rows()
        check("the in-app rating wins with source 'app'",
              len(got) == 1 and got[0]["rating"] == 4.0 and got[0]["rating_source"] == "app", got)
        conn.execute("UPDATE app_ratings SET import_rating=3.5 WHERE media_id='imdb:h1'")
        conn.commit()
        got = rows()
        check("after the export lands, conflict is 1 and export_rating shows it",
              len(got) == 1 and got[0]["conflict"] == 1 and got[0]["export_rating"] == 3.5
              and got[0]["rating"] == 4.0, got)
        reset()

        # Two explicit sources that disagree, then two that agree
        media("imdb:a1", "film", "Film A", 2001)
        media("gr:a2", "film", "film a", 2001, source="goodreads")
        rated("imdb:a1", 4.0, "imdb", "2026-02-02")
        rated("gr:a2", 2.0, "goodreads", "2026-03-03")
        media("imdb:b1", "film", "Film B", 2002)
        media("gr:b2", "film", "film b", 2002, source="goodreads")
        rated("imdb:b1", 3.0, "imdb", "2026-02-02")
        rated("gr:b2", 3.0, "goodreads", "2026-03-03")
        my_ratings.assign_work_keys(conn)
        got = {r["title"]: r for r in rows()}
        check("disagreeing imports: IMDb wins and the conflict is flagged",
              got.get("Film A", {}).get("rating") == 4.0 and got.get("Film A", {}).get("rating_source") == "imdb"
              and got.get("Film A", {}).get("conflict") == 1 and got.get("Film A", {}).get("export_rating") == 2.0,
              got.get("Film A"))
        check("agreeing imports: no conflict", bool(got) and got.get("Film B", {}).get("conflict") == 0
              and got.get("Film B", {}).get("export_rating") is None, got.get("Film B"))
        reset()

        # Two years stay apart; a yearless row with two possible years stays separate too
        media("imdb:y1", "film", "Old Guard", 2020)
        media("jw:y2", "film", "old guard", 2022, source="justwatch")
        media("netflix:y3", "film", "old guard", None, source="netflix")
        rated("imdb:y1", 3.0, "imdb", "2026-02-02")
        rated("jw:y2", 3.0, "justwatch", "2026-02-02")
        rated("netflix:y3", 4.0, "netflix", "2026-02-02")
        my_ratings.assign_work_keys(conn)
        got = rows()
        keys = sorted(r["work_key"] for r in got)
        check("same title, two years: two rows, the yearless one stays its own row",
              len(got) == 3 and len({k.split("|")[2] for k in keys}) == 3
              and any(r["media_type"] == "film" and r["year"] is None for r in got), keys)
        check("each year row keeps a member id",
              all(len(json.loads(r["member_ids"])) == 1 for r in got), [r["member_ids"] for r in got])
        reset()

        # One title in film and tv_show stays two works
        media("imdb:f1", "film", "Fargo", 1996)
        media("tmdb:s1", "tv_show", "Fargo", 2014, source="tmdb")
        rated("imdb:f1", 4.0, "imdb", "2026-02-02")
        rated("tmdb:s1", 4.0, "imdb", "2026-02-02")
        my_ratings.assign_work_keys(conn)
        got = rows()
        check("film and tv_show stay separate", len(got) == 2
              and sorted(r["media_type"] for r in got) == ["film", "tv_show"], got)
        reset()

        # tv_episode rows never appear, with or without a rating
        media("tmdb:e1", "tv_episode", "An Episode", 2020, source="tmdb")
        media("tmdb:s2", "tv_show", "A Show", 2020, source="tmdb")
        rated("tmdb:e1", 4.0, "imdb", "2026-02-02")
        my_ratings.assign_work_keys(conn)
        episodes = conn.execute("SELECT work_key FROM media_items WHERE media_type='tv_episode'").fetchall()
        got = [r for r in rows() if r["media_type"] == "tv_episode"]
        check("tv_episode rows never appear in the view", not got, got)
        check("episodes keep work_key NULL", all(r["work_key"] is None for r in episodes), episodes)
        reset()

        # 'movie' and 'film' merge when title and year match
        media("imdb:p1", "movie", "Heat", 1995)
        media("jw:p2", "film", "Heat", 1995, source="justwatch")
        rated("imdb:p1", 4.0, "imdb", "2026-02-02")
        my_ratings.assign_work_keys(conn)
        got = rows()
        check("'movie' and 'film' merge into one row as 'film'",
              len(got) == 1 and got[0]["media_type"] == "film" and "imdb:p1" in got[0]["member_ids"]
              and "jw:p2" in got[0]["member_ids"], got)
        reset()

        # A row that has no work_key yet still shows as its own work
        media("manual:l1", "film", "Late Film", 2023, source="manual")
        rated("manual:l1", 3.0, "manual", "2026-02-02")
        got = rows()
        insert_keys = conn.execute("SELECT work_key FROM media_items WHERE id='manual:l1'").fetchall()
        check("a row with NULL work_key still appears on its own",
              len(got) == 1 and got[0]["title"] == "Late Film" and got[0]["work_key"] == "manual:l1"
              and all(r["work_key"] is None for r in insert_keys), got)
        reset()

        # Punctuation and case differences in titles merge
        media("imdb:s1", "film", "Spider-Man", 2002)
        media("jw:s2", "film", "spider man", 2002, source="justwatch")
        rated("imdb:s1", 3.0, "imdb", "2026-02-02")
        my_ratings.assign_work_keys(conn)
        got = rows()
        check("punctuation and case differences merge",
              len(got) == 1 and len(json.loads(got[0]["member_ids"])) == 2, got)

        # Regression OBS-054: a JustWatch id can contain a comma, so the list must not be comma-joined
        media("jw:love,_actually:2003", "film", "Love, Actually", 2003, source="justwatch")
        rated("jw:love,_actually:2003", 4.0, "manual")
        my_ratings.assign_work_keys(conn)
        got = rows("WHERE title='Love, Actually'")
        try:
            ids = json.loads(got[0]["member_ids"])
        except ValueError:
            ids = got[0]["member_ids"]
        check("a member id with a comma stays one id", ids == ["jw:love,_actually:2003"], ids)

        # The average leaves out signal-only works (nothing invented from a like)
        media("imdb:v1", "film", "Scored Film", 2018)
        rated("imdb:v1", 2.0, "imdb", "2026-02-02")
        media("jw:v2", "film", "Liked Film", 2019, source="justwatch")
        rated("jw:v2", 4.5, "justwatch_liked", "2026-02-02")
        my_ratings.assign_work_keys(conn)
        avg = conn.execute("SELECT AVG(rating) FROM my_ratings").fetchone()[0]
        # Rows with a rating here: Spider-Man 3.0 and Scored Film 2.0; the liked film stays rating NULL
        check("average(rating) leaves out signal-only works", avg == (3.0 + 2.0) / 2, avg)

        # init is idempotent, and a later set_rating keys a fresh item
        before = rows()
        my_ratings.init(conn)
        check("init is idempotent", rows() == before,
              (len(before), len(rows())))
        media("manual:n1", "film", "New Thing", 2024, source="manual")
        rated("manual:n1", 3.0, "manual", "2026-02-02")
        got = rows("WHERE media_type='film' AND title='New Thing'")
        check("the fresh item is visible without a key assignment", len(got) == 1, got)
        app_ratings.set_rating(conn, ["manual:n1"], 4.0, "chat")
        got = rows("WHERE media_type='film' AND title='New Thing'")
        stored = conn.execute("SELECT work_key FROM media_items WHERE id='manual:n1'").fetchone()
        check("set_rating on a new item assigns its work_key",
              stored["work_key"] is not None and got and got[0]["rating"] == 4.0
              and got[0]["rating_source"] == "app", (dict(stored), got))

        # work_key is derived from title and year, so undo leaves it alone
        media("jw:u1", "film", "Undo Film", 2015, source="justwatch")
        action = {"action": "rate", "title": "Undo Film", "year": 2015, "media_type": "film", "rating": 4.0}
        b_snap, a_snap = oracle_actions.apply(conn, action, {"item_ids": ["jw:u1"], "pick_ids": []})
        oracle_actions.init_table(conn)
        cur = conn.execute(
            "INSERT INTO oracle_actions (created_at, updated_at, user_message, action, status, before_state, after_state) "
            "VALUES (?,?,?,?,?,?,?)", ("2026-02-02T00:00:00Z", "2026-02-02T00:00:00Z", "Undo Film 4 stars",
                                       json.dumps(action), "applied", json.dumps(b_snap), json.dumps(a_snap)))
        ok, msg = oracle_actions.undo(conn, cur.lastrowid)
        check("undoing a rate takes the work out of the view", ok and not rows("WHERE title='Undo Film'"), msg)

conn.close()
print(f"\n{checks - failures}/{checks} passed")
sys.exit(1 if failures else 0)
