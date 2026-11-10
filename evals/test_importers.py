"""OBS-054 step 2: importer fixes run before new exports arrive. Offline, temp DB."""

from __future__ import annotations

import csv
import gc
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


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def imdb_row(const, title, rating, year, kind="Movie"):
    return {"Const": const, "Your Rating": rating, "Date Rated": "2026-03-08", "Title": title, "Year": year,
            "Runtime (mins)": 100, "Title Type": kind, "Genres": "Drama", "Directors": "Someone"}


def jw_row(title, year, mtype="movie"):
    return {"title": title, "original_title": title, "year": year, "type": mtype}


def seed(conn, id_, mtype, title, year, source="imdb", source_id=None, author=None):
    conn.execute(
        "INSERT INTO media_items (id, media_type, title, author, year, source, source_id) VALUES (?,?,?,?,?,?,?)",
        (id_, mtype, title, author, year, source, source_id or id_))


def seen_rows(conn, media_id):
    return conn.execute(
        "SELECT count(*) FROM user_interactions WHERE media_id=? AND source='justwatch_seen'", (media_id,)).fetchone()[0]


def media_type(conn, media_id):
    row = conn.execute("SELECT media_type FROM media_items WHERE id=?", (media_id,)).fetchone()
    return row["media_type"] if row else None


with tempfile.TemporaryDirectory(prefix="obs-054-eval-") as folder:
    tmp = Path(folder)
    os.environ["OBS_DB_PATH"] = str(tmp / "test.db")

    from db import get_conn, init_db
    import ingest_films
    import ingest_justwatch
    import ingest_audible
    import app_ratings

    ingest_films.RATINGS_CSV = tmp / "imdb.csv"
    ingest_films.WATCHLIST_CSV = tmp / "no-watchlist.csv"
    ingest_justwatch.SEEN_CSV = tmp / "jw_seen.csv"
    ingest_justwatch.LIKED_CSV = tmp / "jw_liked.csv"
    ingest_audible.AUDIBLE_CSV = tmp / "audible.csv"

    conn = get_conn()
    init_db(conn)

    # ---------- Fix A: IMDb TV Episode media type ----------
    conn.execute("INSERT INTO media_items (id, media_type, title, year, source, source_id) VALUES "
                 "('imdb:ttEp2', 'tv_show', 'Old Episode', 2015, 'imdb', 'ttEp2')")
    write_csv(ingest_films.RATINGS_CSV, [
        imdb_row("ttEp1", "Pilot Episode", 7, 2015, "TV Episode"),
        imdb_row("ttEp2", "Old Episode", 8, 2015, "TV Episode"),
        imdb_row("ttS1", "Pilot Series", 7, 2015, "TV Series"),
        imdb_row("ttM1", "Pilot Film", 7, 2015, "Movie"),
    ])
    ingest_films.ingest_ratings(conn)
    check("a fresh TV Episode row imports as tv_episode", media_type(conn, "imdb:ttEp1") == "tv_episode",
          media_type(conn, "imdb:ttEp1"))
    check("an existing tv_show row is reclassified on re-import", media_type(conn, "imdb:ttEp2") == "tv_episode",
          media_type(conn, "imdb:ttEp2"))
    check("TV Series stays tv_show", media_type(conn, "imdb:ttS1") == "tv_show", media_type(conn, "imdb:ttS1"))
    check("Movie stays film", media_type(conn, "imdb:ttM1") == "film", media_type(conn, "imdb:ttM1"))

    # ---------- Fix B: JustWatch matching ----------
    # Candidates for the seen matching checks
    seed(conn, "imdb:dv1", "film", "Double Vision", 2010)
    seed(conn, "imdb:tcf", "film", "Type Clash", 2010)
    seed(conn, "imdb:ny1", "film", "Neighbor Year", 2011)
    seed(conn, "imdb:p1", "film", "Remake Saga", 1999)
    seed(conn, "imdb:p2", "film", "Remake Saga", 2017)
    seed(conn, "imdb:o1", "film", "Undated Solo", 2001)
    seed(conn, "imdb:m1999", "film", "Migration Film", 1999)
    seed(conn, "imdb:m2005", "film", "Migration Film", 2005)
    # The old wrong attachment an earlier import created (title-only fallback)
    conn.execute("INSERT INTO user_interactions (media_id, interaction, shelf, source) "
                 "VALUES ('imdb:m1999', 'completed', 'seen', 'justwatch_seen')")
    conn.commit()

    write_csv(ingest_justwatch.SEEN_CSV, [
        jw_row("Double Vision", "2020"),        # year far off -> must not attach to 2010
        jw_row("Type Clash", "2010", "show"),   # tv row -> must not attach to the film
        jw_row("Neighbor Year", "2012"),        # year off by 1, only candidate -> attaches to imdb:ny1
        jw_row("Remake Saga", ""),              # no JustWatch year, two candidates -> new item
        jw_row("Undated Solo", ""),             # no JustWatch year, one candidate -> attaches to imdb:o1
        jw_row("Migration Film", "2005"),       # exact year wins over the 1999 candidate with the old row
    ])
    ingest_justwatch.ingest_seen(conn)

    check("same title, year far off, creates a new item",
          media_type(conn, "jw:double_vision:2020") == "film", media_type(conn, "jw:double_vision:2020"))
    check("same title, year far off, does not attach", seen_rows(conn, "imdb:dv1") == 0, seen_rows(conn, "imdb:dv1"))
    check("film and tv_show do not attach", seen_rows(conn, "imdb:tcf") == 0, seen_rows(conn, "imdb:tcf"))
    check("year off by one attaches when it is the only candidate", seen_rows(conn, "imdb:ny1") == 1, seen_rows(conn, "imdb:ny1"))
    check("two candidates with no JustWatch year creates a new item",
          media_type(conn, "jw:remake_saga:") == "film", media_type(conn, "jw:remake_saga:"))
    check("one candidate with no JustWatch year attaches", seen_rows(conn, "imdb:o1") == 1, seen_rows(conn, "imdb:o1"))
    check("an old wrong attachment is gone after re-import", seen_rows(conn, "imdb:m1999") == 0, seen_rows(conn, "imdb:m1999"))
    check("the old wrong attachment now sits on the right work", seen_rows(conn, "imdb:m2005") == 1, seen_rows(conn, "imdb:m2005"))

    # A like re-rated in the app keeps the app rating through the rebuild
    write_csv(ingest_justwatch.LIKED_CSV, [jw_row("Prized Thing", "2015")])
    ingest_justwatch.ingest_liked(conn)
    app_ratings.set_rating(conn, ["jw:prized_thing:2015"], 2.5, "rate")
    conn.commit()
    ingest_justwatch.ingest_liked(conn)
    survived = conn.execute("SELECT rating, source FROM user_interactions WHERE media_id='jw:prized_thing:2015' "
                            "AND rating IS NOT NULL ORDER BY id").fetchall()
    check("a like re-rated in the app keeps the app rating after re-import",
          [(r["rating"], r["source"]) for r in survived] == [(2.5, "oracle")],
          [(r["rating"], r["source"]) for r in survived])
    app_row = conn.execute("SELECT rating FROM app_ratings WHERE media_id='jw:prized_thing:2015'").fetchone()
    check("the app rating row is still recorded", bool(app_row) and app_row["rating"] == 2.5, dict(app_row) if app_row else None)

    # Regression OBS-054: a like rated equal to its imported value must not count twice
    write_csv(ingest_justwatch.LIKED_CSV, [jw_row("Twin Value", "2016")])
    ingest_justwatch.ingest_liked(conn)
    app_ratings.set_rating(conn, ["jw:twin_value:2016"], 4.5, "rate")
    conn.commit()
    ingest_justwatch.ingest_liked(conn)
    twin = lambda: [(r["rating"], r["source"]) for r in conn.execute(
        "SELECT rating, source FROM user_interactions WHERE media_id='jw:twin_value:2016' AND rating IS NOT NULL ORDER BY id")]
    check("a like valued equal to the app rating stays one oracle row", twin() == [(4.5, "oracle")], twin())
    ingest_justwatch.ingest_liked(conn)
    check("another re-import of the equal valued like changes nothing", twin() == [(4.5, "oracle")], twin())

    # ---------- Fix C: Audible author-aware matching ----------
    seed(conn, "gr:1", "book", "Dune Messiah", None, author="Frank Herbert")
    seed(conn, "gr:2", "book", "Hyperion", None, author="Dan Simmons")
    seed(conn, "gr:3", "book", "Null Book", None, author=None)
    seed(conn, "gr:4", "book", "The Will of Many: Book One", None, author="James Islington")

    def find(title, author):
        return ingest_audible.find_in_db(conn, title, author)

    check("same title, different author, gives a new item", find("Hyperion", "Islington, James") is None,
          find("Hyperion", "Islington, James"))
    check("same title, same author, matches", find("Dune Messiah", "Frank Herbert") == "gr:1",
          find("Dune Messiah", "Frank Herbert"))
    check("same title, DB author NULL, matches", find("Null Book", "Dan Simmons") == "gr:3", find("Null Book", "Dan Simmons"))
    check("prefix title, different author, does not match",
          find("The Will of Many: Part One", "James Herbert") is None, find("The Will of Many: Part One", "James Herbert"))
    check("prefix title, same author, matches (multi-author form)",
          find("The Will of Many: Part One", "Islington, James Herbert") == "gr:4",
          find("The Will of Many: Part One", "Islington, James Herbert"))
    check("exact title with the author missing is accepted", find("Dune Messiah", None) == "gr:1",
          find("Dune Messiah", None))
    check("prefix title with the author missing is refused", find("The Will of Many: Part One", None) is None,
          find("The Will of Many: Part One", None))

    # Regression OBS-054: two books with one title, the first with another author, must still find the second
    seed(conn, "gr:sameA", "book", "Same Title", None, author="Ann Other")
    seed(conn, "gr:sameB", "book", "Same Title", None, author="Bob First")
    check("two books with one title match the agreeing author",
          find("Same Title", "Bob First") == "gr:sameB", find("Same Title", "Bob First"))

    # Regression OBS-054: a missing Audible CSV must not delete the books already imported
    conn.execute("INSERT INTO media_items (id, media_type, title, source, source_id) VALUES ('au:kept', 'book', 'Kept Book', 'audible', 'kept')")
    conn.execute("INSERT INTO user_interactions (media_id, interaction, source) VALUES ('au:kept', 'completed', 'audible')")
    conn.commit()
    try:
        ingest_audible.main()
    except FileNotFoundError:
        pass
    check("a missing Audible CSV keeps existing Audible books",
          conn.execute("SELECT 1 FROM media_items WHERE id='au:kept'").fetchone() is not None)

    # Regression OBS-054: a CSV that fails mid-run must not delete the books the early cleanup removed
    conn.execute("INSERT INTO media_items (id, media_type, title, source, source_id) VALUES ('au:stays', 'book', 'Stays Book', 'audible', 'stays')")
    conn.execute("INSERT INTO user_interactions (media_id, interaction, source) VALUES ('au:stays', 'completed', 'audible')")
    conn.commit()
    ingest_audible.AUDIBLE_CSV.write_text("book,auth\nWrong Header Book,Someone\n", encoding="utf-8")
    try:
        ingest_audible.main()
    except Exception:
        pass
    gc.collect()  # drop main()'s failed connection so its open transaction rolls back
    check("a broken Audible CSV keeps existing Audible books",
          conn.execute("SELECT 1 FROM media_items WHERE id='au:stays'").fetchone() is not None)

    # Regression OBS-054: an au: item with a chat added seen row survives a normal run that does not list it
    conn.execute("INSERT INTO media_items (id, media_type, title, source, source_id) VALUES ('au:chatted', 'book', 'Chatted Book', 'audible', 'chatted')")
    conn.executemany("INSERT INTO user_interactions (media_id, interaction, shelf, source) VALUES (?,?,?,?)", [
        ("au:chatted", "seen", "seen", "oracle"),
        ("au:chatted", "completed", None, "audible"),
    ])
    conn.commit()
    write_csv(ingest_audible.AUDIBLE_CSV, [{"title": "Listened Book", "author": "An Author"}])
    ingest_audible.main()
    check("a chat added seen row keeps its au: item through a normal run",
          conn.execute("SELECT 1 FROM media_items WHERE id='au:chatted'").fetchone() is not None)
    check("the chat added seen row itself survives",
          conn.execute("SELECT 1 FROM user_interactions WHERE media_id='au:chatted' AND source='oracle'").fetchone() is not None)

    conn.close()

# Regression OBS-056: the 2026-11 Netflix export drops the word "Season", which split a show with a colon in its name
import ingest_netflix

for raw, expected in [
    ("Cyberpunk: Edgerunners:  1: My Moon My Man (Episode 10)", ("Cyberpunk: Edgerunners", "tv_show")),
    ("Cyberpunk: Edgerunners: Season 1: My Moon My Man (Episode 10)", ("Cyberpunk: Edgerunners", "tv_show")),
    ("Cyberpunk: Edgerunners: Cyberpunk: Edgerunners 2: 0+2=1 (Episode 3)", ("Cyberpunk: Edgerunners", "tv_show")),
    ("Sword Art Online:  1: The World of Swords (Episode 1)", ("Sword Art Online", "tv_show")),
    ("Our Planet:  1: One Planet", ("Our Planet", "tv_show")),
    ("Blade Runner 2049", ("Blade Runner 2049", "film")),
    ("Mission: Impossible", ("Mission: Impossible", "film")),
]:
    got = ingest_netflix.extract_show_or_movie(raw)
    check(f"Netflix title parses: {raw}", got == expected, f"got {got}")

print(f"\n{checks - failures}/{checks} passed")
sys.exit(1 if failures else 0)
