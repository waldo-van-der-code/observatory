"""OBS-053: what the Oracle is told about Waldo's library, read fresh for every question.

Plain text only. server.py escapes it as one block, so titles can never act as instructions.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from datetime import date

import oracle_actions
from oracle_actions import norm

MENTION_CAP = 15
MAX_TITLE_WORDS = 12
RECENT_CAP = 30
GROUPS = [("film", "FILMS"), ("tv_show", "TV SHOWS"), ("book", "BOOKS AND AUDIOBOOKS"),
          ("comic", "COMICS"), ("podcast", "PODCASTS")]
SOURCE_LABELS = {"imdb": "IMDb", "goodreads": "Goodreads", "netflix": "Netflix", "justwatch_liked": "JustWatch",
                 "justwatch_seen": "JustWatch", "oracle": "chat", "manual": "manual entry",
                 "pocket_casts": "Pocket Casts", "audible": "Audible"}
# A title made only of these could be ordinary speech ("cheer her up"); one-word titles count too.
COMMON_WORDS = frozenset("a about after all an and are at be before but can come could day did do for from get go "
                         "good have he her here him his home how i if in is it know life like love make man me my "
                         "need new night no not of old on one or out over see she should so that the there think "
                         "this time to two up us want was we what when where who why will with world would you "
                         "your".split())


def _inferred(signal: dict) -> str | None:
    return oracle_actions.INFERRED_RATINGS.get((signal["source"], signal["rating"]))


def _wanted_only(signal: dict) -> bool:
    return signal["interaction"] in ("want", "watchlist") or signal["shelf"] in ("to-watch", "to-read")


def load_works(conn: sqlite3.Connection) -> list[dict]:
    """One entry per work (my_ratings' work key). Episodes are left out: they carry a copied show score."""
    works: dict[str, dict] = {}
    for row in conn.execute("""
        SELECT COALESCE(m.work_key, m.id) AS wk, m.media_type, m.title, m.year, m.author, u.interaction, u.rating,
               u.date_completed, u.date_added, u.source, u.shelf
        FROM media_items m JOIN user_interactions u ON u.media_id=m.id
        WHERE m.media_type <> 'tv_episode' ORDER BY u.id"""):
        if not norm(row["title"]):
            continue
        work = works.setdefault(row["wk"], {
            "group": "film" if row["media_type"] == "movie" else row["media_type"], "key": norm(row["title"]),
            "title": " ".join(row["title"].split()), "year": row["year"], "author": row["author"], "signals": [],
            "rating": None, "signal": None, "rated_at": None, "conflict": 0, "export_rating": None,
            "rating_source": None})
        work["year"] = work["year"] or row["year"]
        work["author"] = work["author"] or row["author"]
        work["signals"].append(dict(row))
    for r in conn.execute("SELECT * FROM my_ratings"):
        if r["work_key"] in works:
            works[r["work_key"]].update(rating=r["rating"], signal=r["signal"], rated_at=r["rated_at"],
                                        conflict=r["conflict"], export_rating=r["export_rating"],
                                        rating_source=r["rating_source"])
    return list(works.values())


def _in_library(work: dict) -> bool:
    return work["rating"] is not None or work["signal"] is not None or not all(_wanted_only(s) for s in work["signals"])


def _library_line(work: dict) -> str:
    verdict = ", ".join(([f"{work['rating'] * 2:g}"] if work["rating"] is not None else []) +
                        ([work["signal"]] if work["signal"] else []))
    if verdict and work["conflict"] and work["export_rating"] is not None:
        verdict += f" (export says {work['export_rating'] * 2:g})"
    if work["group"] in ("book", "comic") and work["author"]:
        name = f"{work['title']} by {work['author']}"
    else:
        name = f"{work['title']} ({work['year']})" if work["year"] else work["title"]
    return f"{name} | {verdict or 'seen'}"


def _full_line(work: dict) -> str:
    facts = []
    if work["rating"] is not None:
        source = {"imdb": "IMDb", "goodreads": "Goodreads", "app": "his own rating"}.get(work["rating_source"], "rating")
        when = f" on {work['rated_at'][:10]}" if work["rated_at"] else ""
        facts.append(f"{source} {work['rating'] * 2:g}/10{when}")
        if work["conflict"] and work["export_rating"] is not None:
            facts.append(f"export says {work['export_rating'] * 2:g}/10")
    for signal in work["signals"]:
        if signal["rating"] is not None and _inferred(signal):
            facts.append(f"{SOURCE_LABELS.get(signal['source'], signal['source'])} {_inferred(signal)}")
    if any(_wanted_only(s) for s in work["signals"]):
        facts.append("on his watchlist")
    if work["rating"] is None and work["signal"] is None and not all(_wanted_only(s) for s in work["signals"]):
        facts.append("seen, no score recorded")
    year = f"{work['year']}, " if work["year"] else ""
    return f"{work['title']} ({year}{work['group']}): {'; '.join(dict.fromkeys(facts))}"


def _mentions(works: list[dict], message: str) -> str:
    index = defaultdict(list)
    for work in works:
        index[work["key"]].append(work)
    words = norm(message).split()
    spans = [(at, at + size) for at in range(len(words)) for size in range(1, min(MAX_TITLE_WORDS, len(words) - at) + 1)
             if " ".join(words[at:at + size]) in index]
    # Overlaps both stay ("the one piece film"); only a title wholly inside a longer one goes ("the dark knight").
    found = dict.fromkeys(" ".join(words[a:b]) for a, b in spans
                          if not any((x, y) != (a, b) and x <= a and b <= y for x, y in spans))
    if not found:
        return "none: no titles recognised"

    def is_possible(phrase: str) -> bool:
        parts = phrase.split()
        return len(parts) == 1 or all(p in COMMON_WORDS for p in parts)

    lines = [_full_line(w) for p in found if not is_possible(p) for w in index[p]]
    lines += [f"possible match: {_full_line(w)}" for p in found if is_possible(p) for w in index[p]]
    shown = "\n".join(lines[:MENTION_CAP])
    return shown + (f"\n{len(lines) - MENTION_CAP} more not shown" if len(lines) > MENTION_CAP else "")


def _recent(works: list[dict]) -> str:
    today = date.today().isoformat()
    # A like or thumb is something he did; a podcast subscription is not a verdict.
    dated = sorted((w for w in works if (w["rating"] is not None or w["signal"] not in (None, "subscribed"))
                    and w["rated_at"] and w["rated_at"][:10] <= today),
                   key=lambda w: w["rated_at"], reverse=True)
    return "\n".join(f"{w['rated_at'][:10]}: {_library_line(w)}" for w in dated[:RECENT_CAP]) or "none"


def _library(works: list[dict]) -> str:
    lines = []
    for group, heading in GROUPS:
        seen = sorted((w for w in works if w["group"] == group and _in_library(w)), key=lambda w: w["key"])
        if seen:
            lines.append(f"[{heading}]")
            lines += [_library_line(w) for w in seen]
    return "\n".join(lines)


def library_data(conn: sqlite3.Connection, message: str) -> str:
    works = load_works(conn)
    return (f"TITLES POSSIBLY MENTIONED IN HIS LATEST MESSAGE:\n{_mentions(works, message)}\n\n"
            f"RECENTLY RATED (newest first, by recorded date):\n{_recent(works)}\n\n"
            f"FULL LIBRARY (everything he has seen or rated; after the | is his score out of ten or what is known "
            f"instead):\n{_library(works)}")
