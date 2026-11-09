"""OBS-053: what the Oracle is told about Waldo's library, read fresh for every question.

Plain text only. server.py escapes it as one block, so titles can never act as instructions.
"""

from __future__ import annotations

import json
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
    """One entry per work across imports. Episodes are left out: they carry a copied show score."""
    works: dict[tuple, dict] = {}
    for row in conn.execute("""
        SELECT m.media_type, m.title, m.year, m.author, u.interaction, u.rating, u.date_completed, u.date_added,
               u.source, u.shelf
        FROM media_items m JOIN user_interactions u ON u.media_id=m.id
        WHERE m.media_type <> 'tv_episode' ORDER BY u.id"""):
        key = ("film" if row["media_type"] == "movie" else row["media_type"], norm(row["title"]), row["year"])
        if not key[1]:
            continue
        work = works.setdefault(key, {"group": key[0], "key": key[1], "title": " ".join(row["title"].split()),
                                      "year": row["year"],
                                      "author": row["author"], "signals": []})
        work["author"] = work["author"] or row["author"]
        work["signals"].append(dict(row))
    # A row without a year joins the only dated version of that title; with several versions it stays apart.
    years = defaultdict(set)
    for group, key, year in works:
        if year is not None:
            years[group, key].add(year)
    for undated in [k for k in works if k[2] is None and len(years[k[:2]]) == 1]:
        moved, dated = works.pop(undated), works[(*undated[:2], next(iter(years[undated[:2]])))]
        dated["signals"] += moved["signals"]
        dated["author"] = dated["author"] or moved["author"]
    return list(works.values())


def _library_line(work: dict) -> str:
    scores, signals = [], []
    for signal in work["signals"]:
        if signal["rating"] is None:
            continue
        label = _inferred(signal)
        if label:
            signals.append(label)
        else:
            scores.append(f"{signal['rating'] * 2:g}")
    verdict = ", ".join([" or ".join(dict.fromkeys(scores))] * bool(scores) + list(dict.fromkeys(signals)))
    if work["group"] in ("book", "comic") and work["author"]:
        name = f"{work['title']} by {work['author']}"
    else:
        name = f"{work['title']} ({work['year']})" if work["year"] else work["title"]
    return f"{name} | {verdict or 'seen'}"


def _full_line(work: dict) -> str:
    facts = []
    for signal in work["signals"]:
        source = SOURCE_LABELS.get(signal["source"], signal["source"] or "unknown source")
        if signal["rating"] is not None:
            label = _inferred(signal)
            when = f" on {signal['date_completed'][:10]}" if signal["date_completed"] else ""
            facts.append(f"{source} {label}" if label else f"{source} {signal['rating'] * 2:g}/10{when}")
    if any(_wanted_only(s) for s in work["signals"]):
        facts.append("on his watchlist")
    if not any(s["rating"] is not None for s in work["signals"]) and not all(_wanted_only(s) for s in work["signals"]):
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


def _chat_rating_days(conn: sqlite3.Connection) -> dict[tuple, str]:
    """Chat ratings that changed an import keep the import's date, so the action log has the real day."""
    oracle_actions.init_table(conn)
    days = {}
    for action, when in conn.execute("SELECT action, updated_at FROM oracle_actions WHERE status='applied' ORDER BY id"):
        action = json.loads(action)
        if action.get("action") == "rate":
            days[norm(action.get("title", "")), action.get("year")] = when[:10]
    return days


def _recent(works: list[dict], chat_days: dict[tuple, str]) -> str:
    today = date.today().isoformat()
    dated = []
    for work in works:
        days = [(s["date_completed"] or (s["date_added"] if s["source"] in ("oracle", "manual") else None) or "")[:10]
                for s in work["signals"] if s["rating"] is not None and _inferred(s) != "subscribed"]
        days += [chat_days.get((work["key"], year), "") for year in (work["year"], None)]
        days = [d for d in days if d and d <= today]
        if days:
            dated.append((max(days), work))
    dated.sort(key=lambda pair: pair[0], reverse=True)
    return "\n".join(f"{day}: {_library_line(work)}" for day, work in dated[:RECENT_CAP]) or "none"


def _library(works: list[dict]) -> str:
    lines = []
    for group, heading in GROUPS:
        seen = sorted((w for w in works if w["group"] == group
                       and not all(_wanted_only(s) and s["rating"] is None for s in w["signals"])),
                      key=lambda w: w["key"])
        if seen:
            lines.append(f"[{heading}]")
            lines += [_library_line(w) for w in seen]
    return "\n".join(lines)


def library_data(conn: sqlite3.Connection, message: str) -> str:
    works = load_works(conn)
    return (f"TITLES POSSIBLY MENTIONED IN HIS LATEST MESSAGE:\n{_mentions(works, message)}\n\n"
            f"RECENTLY RATED (newest first, by recorded date):\n{_recent(works, _chat_rating_days(conn))}\n\n"
            f"FULL LIBRARY (everything he has seen or rated; after the | is his score out of ten or what is known "
            f"instead):\n{_library(works)}")
