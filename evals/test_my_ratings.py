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
        conn.execute("DELETE FROM user_interactions WHERE media_id='jw:love,_actually:2003'")  # keeps the average below as it was

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

    # ── OBS-054 step 3c: dashboard and Taste Map read the view ────────────────
    import re
    import sqlite3
    import build_brain
    import build_dashboard

    c3 = sqlite3.connect(Path(folder) / "step3c.db")
    c3.row_factory = sqlite3.Row
    init_db(c3)
    app_ratings.init_table(c3)
    check("step 3c fixture starts without the view",
          c3.execute("SELECT 1 FROM sqlite_master WHERE name='my_ratings'").fetchone() is None)

    def film(item_id, title, year, source, genres='["Drama"]'):
        c3.execute("INSERT INTO media_items (id,media_type,title,director,year,source,source_id,genres) "
                   "VALUES (?,?,?,?,?,?,?,?)", (item_id, "film", title, "Dir Step3c", year, source, item_id, genres))

    def mark(media_id, rating, source):
        c3.execute("INSERT INTO user_interactions (media_id,interaction,rating,date_added,date_completed,source) "
                   "VALUES (?,?,?,?,?,?)", (media_id, "rated", rating, "2026-03-01", "2026-03-01", source))

    film("s1", "Dup Film", 2001, "imdb")
    film("s2", "Dup Film", 2001, "netflix")
    mark("s1", 4.0, "imdb")
    mark("s2", 4.0, "netflix")
    film("s3", "Like Only", 2002, "justwatch")
    mark("s3", 4.5, "justwatch_liked")
    film("s4", "App Replace", 2003, "imdb")
    mark("s4", 3.0, "imdb")
    c3.commit()
    my_ratings.init(c3)
    app_ratings.set_rating(c3, ["s4"], 5.0, "chat")
    c3.execute("DROP VIEW my_ratings")
    c3.commit()

    page = build_dashboard.render(c3)
    check("dashboard rebuilds on a database without the view", "<html" in page.lower())
    check("a work with an IMDb row and a Netflix thumb counts once, the like adds nothing",
          "2 rated · avg 9.0/10" in page, re.findall(r"\d+ rated · avg [^<]*", page))
    check("director table counts works, not interactions",
          re.search(r"Dir Step3c</span></td><td>2</td><td>9.0/10", page) is not None,
          re.findall(r"Dir Step3c</span></td><td>\d+</td><td>[^<]*", page))
    check("a JustWatch like shows as the word, never a number",
          re.search(r"Like Only</td><td>liked</td>", page) is not None,
          re.findall(r"Like Only</td><td>[^<]*", page))

    top = build_brain._get_top_items(c3)
    entries = [i for items in top.values() for i in items]
    dup = [i for i in entries if i["title"] == "Dup Film"]
    check("Taste Map gives the merged work one entry with its rating",
          len(dup) == 1 and dup[0]["rating"] == 4.0, dup)
    check("Taste Map leaves a like-only work out", not [i for i in entries if i["title"] == "Like Only"])
    check("Taste Map top list uses the in-app rating over the import",
          [i["rating"] for i in entries if i["title"] == "App Replace"] == [5.0], entries)
    c3.close()

    # ── Regression OBS-054 step 3 review: findings before deploy ──────────────
    def statements(call):
        seen = []
        conn.set_trace_callback(seen.append)
        try:
            call()
        finally:
            conn.set_trace_callback(None)
        return [s.split()[0].upper() for s in seen]

    def reimport(media_id, value, source):
        """What an importer does: replace its own row with the export's value, then reapply."""
        conn.execute("DELETE FROM user_interactions WHERE media_id=? AND source=?", (media_id, source))
        rated(media_id, value, source)
        try:
            app_ratings.reapply(conn, source)
        except TypeError as e:
            check("reapply knows which export just ran", False, repr(e))
            app_ratings.reapply(conn)

    def import_rating(media_id):
        return conn.execute("SELECT import_rating FROM app_ratings WHERE media_id=?", (media_id,)).fetchone()[0]

    def book(item_id, title, author, year=2000, source="goodreads"):
        conn.execute("INSERT INTO media_items (id,media_type,title,author,year,source,source_id) VALUES (?,?,?,?,?,?,?)",
                     (item_id, "book", title, author, year, source, item_id))

    WRITES = {"DROP", "CREATE", "ALTER", "UPDATE", "INSERT", "DELETE", "BEGIN", "COMMIT"}
    reset()
    conn.commit()
    version = conn.execute("PRAGMA schema_version").fetchone()[0]
    my_ratings.init(conn)
    conn.commit()
    check("installing an unchanged view does not touch the schema",
          conn.execute("PRAGMA schema_version").fetchone()[0] == version)
    check("the Taste Map writes nothing once the view exists",
          not WRITES & set(statements(lambda: build_brain._get_top_items(conn))))
    conn.execute("DROP VIEW my_ratings")
    conn.execute("CREATE VIEW my_ratings AS SELECT 1 AS old_shape")
    conn.commit()
    order = statements(lambda: my_ratings.init(conn))
    conn.commit()
    check("replacing a changed view is one transaction",
          "BEGIN" in order and "DROP" in order and order.index("BEGIN") < order.index("DROP")
          and "COMMIT" in order[order.index("DROP"):], order)

    media("rev:thumb", "film", "Thumb Film", 2001, source="netflix")
    rated("rev:thumb", 4.0, "netflix")
    app_ratings.set_rating(conn, ["rev:thumb"], 5.0, "chat")
    reimport("rev:thumb", 4.0, "netflix")
    got = rows("WHERE title='Thumb Film'")
    check("a re-imported thumb is not an export score",
          import_rating("rev:thumb") is None and got[0]["conflict"] == 0 and got[0]["export_rating"] is None, got)

    media("rev:agree", "film", "Agree Film", 2002)
    rated("rev:agree", 3.0, "imdb")
    app_ratings.set_rating(conn, ["rev:agree"], 5.0, "chat")
    reimport("rev:agree", 3.0, "imdb")
    check("a differing export is kept", import_rating("rev:agree") == 3.0, import_rating("rev:agree"))
    reimport("rev:agree", 3.0, "goodreads")
    check("another export's run leaves it alone", import_rating("rev:agree") == 3.0, import_rating("rev:agree"))
    conn.execute("DELETE FROM user_interactions WHERE media_id='rev:agree' AND source='goodreads'")
    reimport("rev:agree", 5.0, "imdb")
    got = rows("WHERE title='Agree Film'")
    check("an export that now agrees ends the conflict",
          import_rating("rev:agree") is None and got[0]["conflict"] == 0, got)
    for script, source in (("ingest_films.py", "imdb"), ("ingest_books.py", "goodreads")):
        check(f"{script} names its export",
              f'app_ratings.reapply(conn, "{source}")' in (ROOT / "scripts" / script).read_text())

    reset()
    book("rev:b1", "Emma", "Jane Austen", 2003)
    book("rev:b2", "Emma", "Meg Cabot", 2003)
    rated("rev:b1", 4.0, "goodreads")
    rated("rev:b2", 2.0, "goodreads")
    book("rev:b3", "Dune", "Frank Herbert", 2005)
    book("rev:b4", "Dune", "Herbert, Frank", 2005, source="audible")
    rated("rev:b3", 5.0, "goodreads")
    media("rev:s1", "film", "$", 1971)
    media("rev:s2", "film", "%", 1971)
    rated("rev:s1", 4.0, "imdb")
    rated("rev:s2", 2.0, "imdb")
    my_ratings.assign_work_keys(conn)
    check("same title and year by different authors stay two works", len(rows("WHERE title='Emma'")) == 2, rows("WHERE title='Emma'"))
    check("one book written two ways stays one work", len(rows("WHERE title='Dune'")) == 1, rows("WHERE title='Dune'"))
    check("titles of only symbols stay separate works", len(rows("WHERE media_type='film'")) == 2, rows("WHERE media_type='film'"))

    reset()
    media("rev:gr", "book", "Shelf Date", 2000, source="goodreads")
    rated("rev:gr", 4.0, "goodreads", "2026-08-08")
    media("rev:or", "film", "Chat Date", 2000, source="oracle")
    rated("rev:or", 4.0, "oracle", "2026-08-09")
    media("rev:like", "film", "Liked Late", 2000, source="justwatch")
    conn.execute("INSERT INTO user_interactions (media_id,interaction,rating,date_added,date_completed,source) VALUES (?,?,?,?,?,?)",
                 ("rev:like", "rated", 4.5, "2026-08-10", "2026-08-10", "justwatch_liked"))
    media("rev:both", "film", "Mixed Signals", 2000, source="netflix")
    rated("rev:both", 4.0, "netflix")
    rated("rev:both", 1.5, "netflix")
    media("rev:pod", "podcast", "Pod Review", None, source="pocket_casts")
    conn.execute("INSERT INTO user_interactions (media_id,interaction,rating,source) VALUES (?,?,?,?)",
                 ("rev:pod", "completed", 3.0, "pocket_casts"))
    for item_id, stored in (("rev:se1", 4.0), ("rev:se2", 3.0)):
        conn.execute("INSERT INTO media_items (id,media_type,title,author,year,source,source_id,series_name,series_pos) VALUES (?,?,?,?,?,?,?,?,?)",
                     (item_id, "book", item_id, "Serial Author", 2000, "goodreads", item_id, "Review Series", 1))
        conn.execute("INSERT INTO user_interactions (media_id,interaction,rating,shelf,source) VALUES (?,?,?,?,?)",
                     (item_id, "rated", stored, "read", "goodreads"))
    my_ratings.assign_work_keys(conn)
    conn.commit()
    check("a Goodreads shelf date is not a rating date", rows("WHERE title='Shelf Date'")[0]["rated_at"] is None, rows("WHERE title='Shelf Date'"))
    check("a chat rating keeps its date", rows("WHERE title='Chat Date'")[0]["rated_at"] == "2026-08-09", rows("WHERE title='Chat Date'"))
    check("a like carries its date", rows("WHERE title='Liked Late'")[0]["rated_at"] == "2026-08-10", rows("WHERE title='Liked Late'"))
    import oracle_lookup
    check("likes stay in the Oracle's recent list", "Liked Late" in oracle_lookup._recent(oracle_lookup.load_works(conn)))
    mixed = rows("WHERE title='Mixed Signals'")
    check("contradictory signals both show",
          bool(mixed) and "thumbs up" in mixed[0]["signal"] and "thumbs down" in mixed[0]["signal"], mixed)
    page = build_dashboard.render(conn)
    check("a subscribed podcast shows the word, not a question mark",
          re.search(r"Pod Review</span>\s*<span[^>]*>subscribed", page) is not None or
          re.search(r"Pod Review[\s\S]{0,300}?subscribed", page) is not None,
          re.findall(r"Pod Review[\s\S]{0,200}", page)[:1])
    check("a series averages its rated works", re.search(r"Review Series[\s\S]{0,400}?7\.0/10", page) is not None,
          re.findall(r"Review Series[\s\S]{0,300}", page)[:1])

conn.close()
print(f"\n{checks - failures}/{checks} passed")
sys.exit(1 if failures else 0)
