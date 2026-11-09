#!/usr/bin/env python3
"""One trustworthy rating per work (OBS-054 step 3a): work keys and the my_ratings view.

assign_work_keys() gives every non-episode media row a work_key so all imports of one work
share one key ('film|the matrix|1999'; media_type 'movie' counts as 'film'). init() installs
the view: one row per work with the best explicit score (an in-app rating, then IMDb, then
Goodreads, then any other explicit row), a signal for a like or thumb (rating NULL then, so
averages never see a made-up number), the conflict flag and the member ids. Never commits:
safe inside a caller's transaction.
"""

from __future__ import annotations

import sqlite3

import app_ratings
from db import norm

VIEW_NAME = "my_ratings"


def _group(media_type: str) -> str:
    return "film" if media_type == "movie" else media_type


def _inferred_sql() -> str:
    """The INFERRED_RATINGS pairs, built from app_ratings, as one condition on ui.source/ui.rating."""
    return " OR ".join(f"(ui.source='{source}' AND ui.rating={value:g})"
                       for source, value in app_ratings.INFERRED_RATINGS)


def _dated_sql() -> str:
    """When a row was rated. date_added is only that for ratings made here: on imports it is a shelf date."""
    return "COALESCE(ui.date_completed, CASE WHEN ui.source IN ('oracle','manual') THEN ui.date_added END)"


def _source_prio(alias: str = "m.source") -> str:
    """Best import source, lower wins: IMDb first, then Goodreads, later imports after that."""
    from oracle_actions import SOURCE_PRIORITY
    return f"CASE {alias} " + " ".join(f"WHEN '{source}' THEN {n}" for n, source in enumerate(SOURCE_PRIORITY)) + \
        " ELSE 99 END"


def _view_sql() -> str:
    return f"""
CREATE VIEW {VIEW_NAME} AS
WITH member AS (
    SELECT m.id AS member_id,
           COALESCE(m.work_key, m.id) AS work_key,
           CASE WHEN m.media_type = 'movie' THEN 'film' ELSE m.media_type END AS media_type,
           m.title, m.year, m.source
    FROM media_items m
    WHERE m.media_type <> 'tv_episode'
),
best AS (
    SELECT work_key, media_type, title, year, member_id,
           ROW_NUMBER() OVER (PARTITION BY work_key ORDER BY {_source_prio('member.source')}, member_id) AS rn
    FROM member
),
members AS (
    SELECT work_key, json_group_array(member_id) AS member_ids FROM member GROUP BY work_key
),
works AS (
    SELECT b.work_key, b.media_type, b.title, b.year, b.work_key AS key_in_works, c.member_ids
    FROM best b JOIN members c ON c.work_key = b.work_key
    WHERE b.rn = 1
),
explicit AS (
    SELECT COALESCE(m.work_key, m.id) AS work_key, 0 AS tier, 'app' AS rating_source,
           ar.rating AS rating, ar.rated_at AS rated, ar.import_rating
    FROM media_items m JOIN app_ratings ar ON ar.media_id = m.id
    WHERE m.media_type <> 'tv_episode'
    UNION ALL
    SELECT COALESCE(m.work_key, m.id),
           CASE ui.source WHEN 'imdb' THEN 1 WHEN 'goodreads' THEN 2 ELSE 3 END,
           CASE ui.source WHEN 'imdb' THEN 'imdb' WHEN 'goodreads' THEN 'goodreads' ELSE 'other' END,
           ui.rating, {_dated_sql()}, NULL
    FROM media_items m JOIN user_interactions ui ON ui.media_id = m.id
    WHERE m.media_type <> 'tv_episode' AND ui.rating IS NOT NULL AND NOT ({_inferred_sql()})
),
ranked AS (
    SELECT work_key, tier, rating_source, rating, rated, import_rating,
           ROW_NUMBER() OVER (PARTITION BY work_key
                              ORDER BY tier, rated DESC, import_rating IS NOT NULL DESC) AS rn
    FROM explicit
),
conf AS (
    SELECT work_key, COUNT(DISTINCT val) > 1 AS conflict
    FROM (SELECT work_key, rating AS val FROM explicit
          UNION ALL
          SELECT work_key, import_rating AS val FROM explicit WHERE import_rating IS NOT NULL)
    GROUP BY work_key
),
winner AS (
    SELECT work_key, rating,
           CASE WHEN rating IS NOT NULL THEN rating_source END AS rating_source,
           rated AS rated_at
    FROM ranked WHERE rn = 1
),
loser AS (
    SELECT work_key, rating AS val,
           ROW_NUMBER() OVER (PARTITION BY work_key ORDER BY rn) AS lrn
    FROM ranked
    WHERE rating IS NOT NULL
      AND rating <> (SELECT w.rating FROM ranked w WHERE ranked.work_key = w.work_key AND w.rn = 1)
),
export AS (
    SELECT c.work_key AS key_in_export,
           CASE WHEN c.conflict THEN COALESCE(
                (SELECT import_rating FROM ranked r WHERE r.work_key = c.work_key AND r.import_rating IS NOT NULL
                 ORDER BY r.rn LIMIT 1),
                (SELECT l.val FROM loser l WHERE l.work_key = c.work_key AND l.lrn = 1)) END AS export_rating
    FROM conf c
),
signal AS (
    SELECT COALESCE(m.work_key, m.id) AS work_key,
           REPLACE(GROUP_CONCAT(DISTINCT CASE {"".join(f"WHEN ui.source='{source}' AND ui.rating={value:g} THEN '{label}' "
                             for (source, value), label in app_ratings.INFERRED_RATINGS.items())} END), ',', ' / ') AS signal,
           MAX({_dated_sql()}) AS signal_at
    FROM media_items m JOIN user_interactions ui ON ui.media_id = m.id AND ui.rating IS NOT NULL
    WHERE m.media_type <> 'tv_episode' AND ({_inferred_sql()})
    GROUP BY work_key
)
SELECT w.key_in_works AS work_key, w.media_type, w.title, w.year,
       wn.rating, wn.rating_source, sgn.signal, COALESCE(wn.rated_at, sgn.signal_at) AS rated_at,
       COALESCE(conf.conflict, 0) AS conflict, exp.export_rating, w.member_ids
FROM works w
LEFT JOIN winner wn ON wn.work_key = w.key_in_works
LEFT JOIN signal sgn ON sgn.work_key = w.key_in_works
LEFT JOIN conf ON conf.work_key = w.key_in_works
LEFT JOIN export exp ON exp.key_in_export = w.key_in_works
WHERE COALESCE(wn.rating, sgn.signal) IS NOT NULL
"""


def _ensure_work_key(conn: sqlite3.Connection) -> None:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(media_items)")}
    if "work_key" not in cols:
        conn.execute("ALTER TABLE media_items ADD COLUMN work_key TEXT")


def _title_key(title: str) -> str:
    """A title made only of symbols normalises to nothing, so it keeps its own text."""
    return norm(title) or title.strip().lower()


def _last_names(author: str | None) -> set[str]:
    return {norm(part).split()[-1] for part in (author or "").split(",") if norm(part)}


def _author_marks(rows: list) -> dict[str, str]:
    """Books sharing a title: when the authors differ, each row gets a mark that keeps the works apart."""
    by_title: dict[tuple, list] = {}
    for r in rows:
        if r["media_type"] in ("book", "comic") and _last_names(r["author"]):
            by_title.setdefault((r["media_type"], _title_key(r["title"])), []).append(r)
    marks: dict[str, str] = {}
    for same_title in by_title.values():
        authors: list[set[str]] = []
        for r in same_title:
            names = _last_names(r["author"])
            known = next((a for a in authors if a & names), None)
            if known is None:
                authors.append(names)
            else:
                known |= names
        if len(authors) > 1:
            for r in same_title:
                marks[r["id"]] = min(next(a for a in authors if a & _last_names(r["author"])))
    return marks


def assign_work_keys(conn: sqlite3.Connection) -> None:
    """Give every non-episode media row its work key, updating only rows whose key changed."""
    _ensure_work_key(conn)
    rows = conn.execute("SELECT id, media_type, title, author, year, work_key FROM media_items "
                        "WHERE media_type <> 'tv_episode'").fetchall()
    marks = _author_marks(rows)
    years: dict[tuple, set] = {}
    for r in rows:
        years.setdefault((_group(r["media_type"]), _title_key(r["title"]), marks.get(r["id"], "")), set()).add(r["year"])
    updates = []
    for r in rows:
        group, title, mark = _group(r["media_type"]), _title_key(r["title"]), marks.get(r["id"], "")
        possible = {y for y in years[(group, title, mark)] if y is not None}
        year = r["year"] if r["year"] is not None else (next(iter(possible)) if len(possible) == 1 else "")
        key = f"{group}|{title}|{year}" + (f"|{mark}" if mark else "")
        if key != r["work_key"]:
            updates.append((key, r["id"]))
    if updates:
        conn.executemany("UPDATE media_items SET work_key=? WHERE id=?", updates)
    conn.execute("UPDATE media_items SET work_key=NULL WHERE media_type='tv_episode' AND work_key IS NOT NULL")


def _install_view(conn: sqlite3.Connection) -> None:
    """Replace the view only when its definition changed, in one step, so a reader never finds it missing."""
    sql = _view_sql().strip()
    current = conn.execute("SELECT sql FROM sqlite_master WHERE type='view' AND name=?", (VIEW_NAME,)).fetchone()
    if current and current[0].strip() == sql:
        return
    own_transaction = not conn.in_transaction
    if own_transaction:
        conn.execute("BEGIN IMMEDIATE")
    conn.execute(f"DROP VIEW IF EXISTS {VIEW_NAME}")
    conn.execute(sql)
    if own_transaction:
        conn.commit()


def init(conn: sqlite3.Connection) -> None:
    """Add work_key, install the view, assign keys. Never commits a caller's transaction."""
    _ensure_work_key(conn)
    _install_view(conn)
    assign_work_keys(conn)
