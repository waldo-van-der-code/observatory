#!/usr/bin/env python3
"""Build entertainment dashboard HTML from entertainment.db."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from db import get_conn, init_db

OUT = Path(__file__).parent.parent / "dashboard.html"
DISMISSED = Path(__file__).parent.parent / "data" / "cache" / "dismissed_recs.json"


def load_dismissed() -> set[int]:
    if DISMISSED.exists():
        return set(json.loads(DISMISSED.read_text()))
    return set()


def svg_bar_chart(data: dict[str, float], color: str = "#1a4fa0",
                  bar_h: int = 20, gap: int = 6, onclick: str = "") -> str:
    if not data:
        return "<p class='dim'>No data yet.</p>"
    items = sorted(data.items(), key=lambda x: x[1], reverse=True)[:12]
    max_val = max(v for _, v in items) or 1
    rows = []
    for label, val in items:
        pct_width = round(val / max_val * 100, 1)
        pct = f"{val:.0%}" if val <= 1 else f"{val:.1f}"
        safe = label.replace("'", "\\'")
        click_attr = f' onclick="{onclick.format(safe=safe)}" style="cursor:pointer"' if onclick else ""
        rows.append(
            f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:{gap}px">'
            f'<div style="width:160px;font-size:12px;text-align:right;color:var(--text-dim);white-space:nowrap;'
            f'overflow:hidden;text-overflow:ellipsis;flex-shrink:0"{click_attr}>{label}</div>'
            f'<div style="flex:1;height:{bar_h}px;background:rgba(26,22,18,0.1);border-radius:2px;overflow:hidden">'
            f'<div style="width:{pct_width}%;height:100%;background:{color};border-radius:2px"></div></div>'
            f'<div style="font-size:12px;font-weight:600;color:var(--text);width:44px;flex-shrink:0;text-align:right">{pct}</div>'
            f'</div>'
        )
    return "\n".join(rows)


def svg_rating_histogram(ratings: list[float], color: str = "#1a4fa0") -> str:
    if not ratings:
        return "<p class='dim'>No ratings yet.</p>"
    buckets = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    for r in ratings:
        b = min(5, max(1, round(r)))
        buckets[b] += 1
    max_v = max(buckets.values()) or 1
    bars = []
    for star, count in sorted(buckets.items()):
        h = max(4, int(count / max_v * 80))
        bars.append(
            f'<div style="display:flex;flex-direction:column;align-items:center;gap:4px">'
            f'<div style="font-size:11px;color:var(--text-dim);font-weight:600">{count}</div>'
            f'<div style="width:32px;height:{h}px;background:{color};border-radius:2px 2px 0 0"></div>'
            f'<div style="font-size:12px;color:var(--gold)">{"★"*star}</div>'
            f'</div>'
        )
    return f'<div style="display:flex;align-items:flex-end;gap:8px;height:120px;padding-top:16px">{"".join(bars)}</div>'


def render(conn) -> str:
    # ── Data pulls ────────────────────────────────────────────────────────────
    dismissed = load_dismissed()

    stats = conn.execute("""
        SELECT
          sum(case when m.media_type='book' then 1 end) books,
          (SELECT count(DISTINCT media_id) FROM user_interactions WHERE source='audible') audiobooks,
          sum(case when m.media_type in ('film','movie') then 1 end) films,
          sum(case when m.media_type='tv_show' then 1 end) shows,
          sum(case when m.media_type in ('film','movie','tv_show')
                    and ui.rating is not null then 1 end) films_rated
        FROM media_items m JOIN user_interactions ui ON ui.media_id=m.id
        WHERE ui.interaction IN ('completed','rated')
    """).fetchone()

    book_ratings = [r["rating"] for r in conn.execute(
        "SELECT rating FROM user_interactions WHERE rating IS NOT NULL AND source='goodreads'"
    ).fetchall()]

    profile_row = conn.execute("SELECT * FROM taste_profile ORDER BY id DESC LIMIT 1").fetchone()
    profile = {}
    if profile_row:
        profile = {
            "genre_fingerprint": json.loads(profile_row["genre_fingerprint"] or "{}"),
            "film_genre_fingerprint": json.loads(profile_row["film_genre_fingerprint"] or "{}"),
            "top_themes": json.loads(profile_row["top_themes"] or "[]"),
            "rating_calibration": json.loads(profile_row["rating_calibration"] or "{}"),
            "taste_clusters": json.loads(profile_row["taste_clusters"] or "[]"),
            "dislikes_pattern": json.loads(profile_row["dislikes_pattern"] or "[]"),
            "top_authors": json.loads(profile_row["top_authors"] or "[]"),
            "top_directors": json.loads(profile_row["top_directors"] or "[]"),
        }

    # Titles already rated or consumed — exclude from recommendations
    consumed_titles = {
        row["title"].lower() for row in conn.execute(
            "SELECT DISTINCT m.title FROM media_items m "
            "JOIN user_interactions ui ON ui.media_id=m.id "
            "WHERE ui.rating IS NOT NULL OR ui.interaction IN ('completed','read')"
        ).fetchall()
    }
    recs_raw = [dict(r) for r in conn.execute(
        "SELECT * FROM recommendations WHERE status='pending' ORDER BY confidence DESC"
    ).fetchall() if r["id"] not in dismissed and r["title"].lower() not in consumed_titles]
    # Enrich with year from media_items where available
    for r in recs_raw:
        row = conn.execute(
            "SELECT year FROM media_items WHERE lower(title)=lower(?) LIMIT 1", (r["title"],)
        ).fetchone()
        r["year"] = row["year"] if row and row["year"] else None
    # Deduplicate by title (sorted DESC by confidence already — keep first hit)
    _seen_rec_titles: set[str] = set()
    recs = []
    for r in recs_raw:
        _key = r["title"].lower()
        if _key not in _seen_rec_titles:
            _seen_rec_titles.add(_key)
            recs.append(r)

    series_data = conn.execute("""
        SELECT series_name, count(*) read_count, min(series_pos) first_pos, max(series_pos) last_pos,
               avg(rating) avg_rating
        FROM media_items m JOIN user_interactions ui ON ui.media_id=m.id
        WHERE series_name IS NOT NULL AND ui.shelf='read'
        GROUP BY series_name HAVING count(*) >= 2
        ORDER BY read_count DESC
    """).fetchall()

    top_authors = conn.execute("""
        SELECT author, count(*) n, avg(rating) avg_r
        FROM media_items m JOIN user_interactions ui ON ui.media_id=m.id
        WHERE ui.rating IS NOT NULL AND author IS NOT NULL AND ui.source='goodreads'
        GROUP BY author HAVING count(*) >= 2
        ORDER BY avg_r DESC, n DESC LIMIT 8
    """).fetchall()

    to_read_raw = conn.execute("""
        SELECT m.title, m.author, m.series_name, m.series_pos, ui.date_added
        FROM media_items m JOIN user_interactions ui ON ui.media_id=m.id
        WHERE ui.shelf='to-read'
        ORDER BY m.series_name NULLS LAST, m.series_pos NULLS LAST, m.title
    """).fetchall()
    _seen_to_read: set[str] = set()
    to_read = []
    for _b in to_read_raw:
        if _b["title"].lower() not in _seen_to_read:
            _seen_to_read.add(_b["title"].lower())
            to_read.append(_b)

    generated = profile_row["generated_at"][:10] if profile_row else "—"
    profile_summary = ""
    if profile_row:
        raw = json.loads(profile_row["raw_response"] or "{}")
        profile_summary = raw.get("profile_summary", "")

    film_ratings = [r["rating"] for r in conn.execute(
        "SELECT rating FROM user_interactions WHERE rating IS NOT NULL "
        "AND source IN ('imdb','justwatch_liked')"
    ).fetchall()]

    # ── Films & series KPIs ───────────────────────────────────────────────────
    film_series_counts = conn.execute("""
        SELECT m.media_type, count(*) cnt
        FROM media_items m JOIN user_interactions ui ON ui.media_id=m.id
        WHERE m.media_type IN ('film','movie','tv_show') AND ui.interaction='completed'
        GROUP BY m.media_type
    """).fetchall()
    n_films  = sum(r["cnt"] for r in film_series_counts if r["media_type"] in ("film","movie"))
    n_series = sum(r["cnt"] for r in film_series_counts if r["media_type"] == "tv_show")

    films_by_year = conn.execute("""
        SELECT substr(ui.date_completed,1,4) yr, count(*) cnt
        FROM user_interactions ui JOIN media_items m ON m.id=ui.media_id
        WHERE m.media_type IN ('film','movie') AND ui.interaction='completed'
          AND ui.date_completed IS NOT NULL AND substr(ui.date_completed,1,4) >= '2015'
        GROUP BY yr ORDER BY yr
    """).fetchall()

    series_by_year = conn.execute("""
        SELECT substr(ui.date_completed,1,4) yr, count(*) cnt
        FROM user_interactions ui JOIN media_items m ON m.id=ui.media_id
        WHERE m.media_type='tv_show' AND ui.interaction='completed'
          AND ui.date_completed IS NOT NULL AND substr(ui.date_completed,1,4) >= '2015'
        GROUP BY yr ORDER BY yr
    """).fetchall()

    films_by_decade = conn.execute("""
        SELECT (m.year/10)*10 decade, count(*) cnt
        FROM media_items m JOIN user_interactions ui ON ui.media_id=m.id
        WHERE m.media_type IN ('film','movie') AND m.year IS NOT NULL
          AND ui.interaction='completed'
        GROUP BY decade ORDER BY decade
    """).fetchall()

    # User rating distribution for films (1–5 stars)
    film_user_rating_dist = conn.execute("""
        SELECT round(ui.rating) stars, count(*) cnt
        FROM user_interactions ui JOIN media_items m ON m.id=ui.media_id
        WHERE m.media_type IN ('film','movie') AND ui.rating IS NOT NULL
        GROUP BY stars ORDER BY stars
    """).fetchall()

    # ── Books KPIs ────────────────────────────────────────────────────────────
    book_series_counts = conn.execute("""
        SELECT CASE WHEN series_name IS NOT NULL THEN 'series' ELSE 'standalone' END kind,
               count(*) cnt
        FROM media_items m JOIN user_interactions ui ON ui.media_id=m.id
        WHERE m.media_type='book' AND ui.shelf='read'
        GROUP BY kind
    """).fetchall()

    book_page_buckets = conn.execute("""
        SELECT CASE
          WHEN page_count IS NULL THEN 'Unknown'
          WHEN page_count < 200   THEN '< 200p'
          WHEN page_count < 350   THEN '200–350p'
          WHEN page_count < 500   THEN '350–500p'
          ELSE '500p +'
        END bucket,
        count(*) cnt
        FROM media_items m JOIN user_interactions ui ON ui.media_id=m.id
        WHERE m.media_type='book' AND ui.shelf='read'
        GROUP BY bucket
        ORDER BY min(coalesce(page_count, 0))
    """).fetchall()

    book_by_decade = conn.execute("""
        SELECT (m.year/10)*10 decade, count(*) cnt
        FROM media_items m JOIN user_interactions ui ON ui.media_id=m.id
        WHERE m.media_type='book' AND m.year IS NOT NULL AND ui.shelf='read'
        GROUP BY decade ORDER BY decade
    """).fetchall()

    book_avg_pages = conn.execute("""
        SELECT round(avg(page_count)) avg_p, max(page_count) max_p
        FROM media_items m JOIN user_interactions ui ON ui.media_id=m.id
        WHERE m.media_type='book' AND page_count IS NOT NULL AND ui.shelf='read'
    """).fetchone()

    # ── Podcasts ──────────────────────────────────────────────────────────────
    podcasts = conn.execute("""
        SELECT m.title, ui.rating
        FROM media_items m JOIN user_interactions ui ON ui.media_id=m.id
        WHERE m.media_type='podcast' AND ui.interaction='completed'
        ORDER BY ui.rating DESC NULLS LAST, m.title
    """).fetchall()

    # ── Comics ───────────────────────────────────────────────────────────────
    comic_total = conn.execute(
        "SELECT count(*) FROM media_items WHERE media_type='comic'"
    ).fetchone()[0]

    comic_series = conn.execute("""
        SELECT m.series_name,
               count(*) album_count,
               min(m.year) year_from,
               max(m.year) year_to,
               (SELECT m2.author FROM media_items m2
                WHERE m2.series_name=m.series_name AND m2.media_type='comic'
                ORDER BY m2.series_pos ASC LIMIT 1) AS author
        FROM media_items m
        WHERE m.media_type='comic' AND m.series_name IS NOT NULL
        GROUP BY m.series_name
        ORDER BY album_count DESC
    """).fetchall()

    comic_standalone = conn.execute("""
        SELECT title, author, year, genres
        FROM media_items
        WHERE media_type='comic' AND series_name IS NULL
        ORDER BY title
    """).fetchall()

    # ── Films & Series (all sources) ──────────────────────────────────────────
    recent_shows = conn.execute("""
        SELECT m.title, m.source, ui.date_completed
        FROM media_items m JOIN user_interactions ui ON ui.media_id=m.id
        WHERE m.media_type='tv_show' AND ui.interaction='completed'
        ORDER BY ui.date_completed DESC LIMIT 20
    """).fetchall()
    recent_films = conn.execute("""
        SELECT m.title, m.source, ui.date_completed
        FROM media_items m JOIN user_interactions ui ON ui.media_id=m.id
        WHERE m.media_type IN ('film','movie') AND ui.interaction='completed'
        ORDER BY ui.date_completed DESC LIMIT 20
    """).fetchall()
    all_counts = conn.execute("""
        SELECT
          sum(case when m.media_type='tv_show' then 1 end) shows,
          sum(case when m.media_type IN ('film','movie') then 1 end) films
        FROM media_items m JOIN user_interactions ui ON ui.media_id=m.id
        WHERE ui.interaction='completed'
    """).fetchone()
    recent_rated = conn.execute("""
        SELECT m.title, m.media_type, ui.rating
        FROM media_items m JOIN user_interactions ui ON ui.media_id=m.id
        WHERE m.media_type IN ('film','movie','tv_show') AND ui.interaction='rated'
        ORDER BY ui.date_completed DESC LIMIT 20
    """).fetchall()

    # ── Spotify ───────────────────────────────────────────────────────────────
    spotify_exists = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='spotify_plays'"
    ).fetchone()
    spotify_stats = {"total_plays": 0, "total_hours": 0.0, "total_artists": 0}
    spotify_top_artists = []
    spotify_by_year = []
    if spotify_exists:
        row = conn.execute(
            "SELECT count(*) n, sum(ms_played)/3600000.0 hrs, count(distinct artist) artists "
            "FROM spotify_plays WHERE artist IS NOT NULL"
        ).fetchone()
        if row and row["n"]:
            spotify_stats = {"total_plays": row["n"], "total_hours": row["hrs"] or 0.0,
                             "total_artists": row["artists"] or 0}
        spotify_top_artists = conn.execute("""
            SELECT artist, count(*) plays, sum(ms_played)/3600000.0 hrs
            FROM spotify_plays WHERE artist IS NOT NULL
            GROUP BY artist ORDER BY plays DESC LIMIT 12
        """).fetchall()
        spotify_by_year = conn.execute("""
            SELECT substr(ended_at, 1, 4) yr, count(*) plays, sum(ms_played)/3600000.0 hrs
            FROM spotify_plays WHERE ended_at IS NOT NULL
            GROUP BY yr ORDER BY yr
        """).fetchall()

    # ── TikTok ────────────────────────────────────────────────────────────────
    _MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
    def _fmt_month(ym: str) -> str:
        try:
            yr, mo = ym.split('-')
            return f"{_MONTHS[int(mo)-1]} '{yr[2:]}"
        except Exception:
            return ym

    tiktok_tables_exist = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='tiktok_interactions'"
    ).fetchone()
    tiktok_stats = {"watched": 0, "liked": 0, "favorited": 0}
    tiktok_monthly = []
    tiktok_hours = []
    tiktok_enrichment = {"success": 0, "pending": 0, "failed": 0}
    tiktok_top_hashtags: list[tuple[str, int]] = []
    tiktok_category_comparison: list[tuple[str, int, int]] = []
    consumption_modes: list[tuple[str, int]] = []

    if tiktok_tables_exist:
        for row in conn.execute(
            "SELECT interaction_type, COUNT(*) c FROM tiktok_interactions GROUP BY interaction_type"
        ).fetchall():
            if row["interaction_type"] in tiktok_stats:
                tiktok_stats[row["interaction_type"]] = row["c"]

        tiktok_monthly = conn.execute("""
            SELECT strftime('%Y-%m', interaction_date) month, COUNT(*) cnt
            FROM tiktok_interactions WHERE interaction_type='watched'
              AND interaction_date IS NOT NULL AND interaction_date != ''
            GROUP BY month ORDER BY month
        """).fetchall()

        tiktok_hours = conn.execute("""
            SELECT CAST(strftime('%H', interaction_date) AS INTEGER) hr, COUNT(*) cnt
            FROM tiktok_interactions WHERE interaction_type='watched'
              AND interaction_date IS NOT NULL AND interaction_date != ''
            GROUP BY hr ORDER BY hr
        """).fetchall()

        for row in conn.execute("""
            SELECT enrichment_status, COUNT(*) c FROM tiktok_videos
            WHERE enrichment_status IS NOT NULL
            GROUP BY enrichment_status
        """).fetchall():
            if row["enrichment_status"] in tiktok_enrichment:
                tiktok_enrichment[row["enrichment_status"]] = row["c"]

        # Top hashtags: parse from enriched videos' hashtags JSON array
        import json as _json
        _tag_counts: dict[str, int] = {}
        for row in conn.execute("""
            SELECT hashtags FROM tiktok_videos
            WHERE enrichment_status = 'success' AND hashtags IS NOT NULL AND hashtags != '[]'
        """).fetchall():
            try:
                tags = _json.loads(row["hashtags"])
                for t in tags:
                    t_lower = t.lower().strip()
                    if t_lower and t_lower not in ("fyp", "foryou", "foryoupage", "viral", "trending"):
                        _tag_counts[t_lower] = _tag_counts.get(t_lower, 0) + 1
            except Exception:
                pass
        tiktok_top_hashtags = sorted(_tag_counts.items(), key=lambda x: -x[1])[:20]

        # Cross-platform category comparison (TikTok liked+fav vs YouTube foreground)
        _tk_cat: dict[str, int] = {}
        for row in conn.execute("""
            SELECT tv.categories FROM tiktok_videos tv
            JOIN tiktok_interactions ti ON ti.video_id = tv.video_id
            WHERE tv.enrichment_status = 'success'
              AND ti.interaction_type IN ('liked', 'favorited')
              AND tv.categories IS NOT NULL AND tv.categories != '[]'
        """).fetchall():
            try:
                for c in _json.loads(row["categories"]):
                    _tk_cat[c] = _tk_cat.get(c, 0) + 1
            except Exception:
                pass

        _yt_cat: dict[str, int] = {}
        for row in conn.execute("""
            SELECT e.yt_categories FROM youtube_video_enrichment e
            WHERE e.ambient_class = 'foreground'
              AND e.yt_categories IS NOT NULL AND e.yt_categories != '[]'
        """).fetchall():
            try:
                for c in _json.loads(row["yt_categories"]):
                    _yt_cat[c] = _yt_cat.get(c, 0) + 1
            except Exception:
                pass

        # Union of all categories, sorted by combined signal
        _all_cats = sorted(
            set(_tk_cat) | set(_yt_cat),
            key=lambda c: -(_tk_cat.get(c, 0) + _yt_cat.get(c, 0))
        )[:12]
        tiktok_category_comparison = [(c, _tk_cat.get(c, 0), _yt_cat.get(c, 0)) for c in _all_cats]

        # Day-level consumption mode summary (Spotify + YouTube + TikTok)
        _day_rows = conn.execute("""
            SELECT date(watched_at) d, COUNT(*) yt_cnt FROM youtube_watch_events
            WHERE watched_at IS NOT NULL GROUP BY d
        """).fetchall()
        _yt_by_day = {r["d"]: r["yt_cnt"] for r in _day_rows}

        _sp_rows = conn.execute("""
            SELECT date(ended_at) d, COUNT(*) sp_cnt FROM spotify_plays
            WHERE ended_at IS NOT NULL GROUP BY d
        """).fetchall() if conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='spotify_plays'"
        ).fetchone() else []
        _sp_by_day = {r["d"]: r["sp_cnt"] for r in _sp_rows}

        _tk_rows = conn.execute("""
            SELECT date(interaction_date) d, COUNT(*) tk_cnt
            FROM tiktok_interactions WHERE interaction_type='watched'
              AND interaction_date IS NOT NULL GROUP BY d
        """).fetchall()
        _tk_by_day = {r["d"]: r["tk_cnt"] for r in _tk_rows}

        _all_days = set(_yt_by_day) | set(_sp_by_day) | set(_tk_by_day)
        _mode_counts = {"TikTok-heavy": 0, "YouTube-heavy": 0, "Music-heavy": 0, "Mixed": 0, "Light": 0}
        for d in _all_days:
            yt = _yt_by_day.get(d, 0)
            sp = _sp_by_day.get(d, 0)
            tk = _tk_by_day.get(d, 0)
            if tk > 200 and yt < 3:
                _mode_counts["TikTok-heavy"] += 1
            elif yt >= 5 and tk < 50:
                _mode_counts["YouTube-heavy"] += 1
            elif sp > 30 and yt < 3 and tk < 50:
                _mode_counts["Music-heavy"] += 1
            elif tk > 50 or yt >= 2 or sp > 10:
                _mode_counts["Mixed"] += 1
            else:
                _mode_counts["Light"] += 1
        consumption_modes = sorted(_mode_counts.items(), key=lambda x: -x[1])

    if not tiktok_tables_exist:
        tiktok_category_comparison = []
        consumption_modes = []

    # ── YouTube ───────────────────────────────────────────────────────────────
    yt_tables_exist = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='youtube_videos'"
    ).fetchone()
    yt_total = 0
    yt_class_split = {}
    yt_top_channels = []
    yt_monthly = []
    yt_yearly = []
    yt_chapters = []
    yt_ring_rows = []
    yt_spotify_context = {}

    if yt_tables_exist:
        yt_total = conn.execute(
            "SELECT COUNT(*) n FROM youtube_watch_events"
        ).fetchone()["n"]

        for row in conn.execute("""
            SELECT e.ambient_class, COUNT(*) cnt,
                   SUM(v.duration_sec) / 3600.0 hours
            FROM youtube_videos v
            JOIN youtube_video_enrichment e USING(video_id)
            GROUP BY e.ambient_class ORDER BY cnt DESC
        """).fetchall():
            yt_class_split[row["ambient_class"] or "unknown"] = {
                "cnt": row["cnt"], "hours": round(row["hours"] or 0, 1)
            }

        yt_top_channels = conn.execute("""
            SELECT v.channel,
                   COUNT(DISTINCT v.video_id) videos,
                   SUM(CASE WHEN v.duration_sec / 60.0 > 90
                            THEN 90.0 ELSE v.duration_sec / 60.0 END) capped_min
            FROM youtube_videos v
            JOIN youtube_video_enrichment e USING(video_id)
            WHERE e.ambient_class = 'foreground'
            GROUP BY v.channel
            ORDER BY capped_min DESC LIMIT 12
        """).fetchall()

        yt_monthly = conn.execute("""
            SELECT strftime('%Y-%m', w.watched_at) month, COUNT(*) cnt
            FROM youtube_watch_events w
            JOIN youtube_video_enrichment e USING(video_id)
            WHERE e.ambient_class = 'foreground'
              AND w.watched_at IS NOT NULL
            GROUP BY month ORDER BY month
        """).fetchall()

        yt_yearly = conn.execute("""
            SELECT strftime('%Y', w.watched_at) yr, COUNT(*) cnt,
                   SUM(CASE WHEN v.duration_sec / 60.0 > 90
                            THEN 90.0 ELSE v.duration_sec / 60.0 END) capped_min
            FROM youtube_watch_events w
            JOIN youtube_videos v USING(video_id)
            JOIN youtube_video_enrichment e USING(video_id)
            WHERE e.ambient_class = 'foreground'
              AND w.watched_at NOT LIKE '1-%'
            GROUP BY yr ORDER BY yr
        """).fetchall()

        yt_chapters = conn.execute(
            "SELECT name, summary, start_date, end_date FROM youtube_chapters ORDER BY start_date"
        ).fetchall()

        # Tree ring data: all events with date, duration, ambient_class, primary topic
        yt_ring_rows = conn.execute("""
            SELECT v.duration_sec, e.ambient_class, e.topics,
                   substr(w.watched_at, 1, 4) yr
            FROM youtube_videos v
            JOIN youtube_video_enrichment e USING(video_id)
            JOIN youtube_watch_events w USING(video_id)
            WHERE w.watched_at NOT LIKE '1-%'
            ORDER BY w.watched_at
        """).fetchall()

        # Cross-platform: Spotify minutes on YouTube-active vs non-YouTube days
        _sp_exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='spotify_plays'"
        ).fetchone()
        yt_spotify_context = {}
        if _sp_exists:
            _yt_days = {r[0] for r in conn.execute(
                "SELECT DISTINCT substr(watched_at,1,10) FROM youtube_watch_events "
                "WHERE watched_at NOT LIKE '1-%' AND video_id IN "
                "(SELECT video_id FROM youtube_video_enrichment WHERE ambient_class='foreground')"
            ).fetchall()}
            _sp_day_min = {r[0]: r[1] for r in conn.execute(
                "SELECT substr(ended_at,1,10) d, SUM(ms_played)/60000.0 min "
                "FROM spotify_plays WHERE ended_at IS NOT NULL GROUP BY d"
            ).fetchall()}
            _yt_sp = [_sp_day_min[d] for d in _yt_days if d in _sp_day_min]
            _no_yt_sp = [m for d, m in _sp_day_min.items() if d not in _yt_days]
            yt_spotify_context = {
                "avg_on_yt_days":    round(sum(_yt_sp) / len(_yt_sp), 1)    if _yt_sp    else 0,
                "avg_off_yt_days":   round(sum(_no_yt_sp) / len(_no_yt_sp), 1) if _no_yt_sp else 0,
                "yt_days_with_sp":   sum(1 for d in _yt_days if d in _sp_day_min),
                "total_yt_days":     len(_yt_days),
            }

    # Load curiosity trails from cache (computed in-session)
    import os as _os
    _trails_path = Path(__file__).parent.parent / "data" / "cache" / "youtube_curiosity_trails.json"
    yt_trails = []
    if _trails_path.exists():
        try:
            _all_trails = json.loads(_trails_path.read_text())
            # Only show topics with meaningful depth (≥ 2 distinct days, ≥ 30min)
            yt_trails = [t for t in _all_trails
                         if t["distinct_days"] >= 2 and t["capped_min"] >= 30][:20]
        except Exception:
            pass

    # Directors queried live from DB (2+ rated films)
    top_directors_by_rating = conn.execute("""
        SELECT m.director, count(*) cnt, avg(ui.rating) avg_r
        FROM media_items m JOIN user_interactions ui ON ui.media_id=m.id
        WHERE m.director IS NOT NULL AND ui.rating IS NOT NULL
          AND m.media_type IN ('film','movie')
        GROUP BY m.director HAVING count(*) >= 2
        ORDER BY avg_r DESC, cnt DESC LIMIT 10
    """).fetchall()
    top_directors_by_count = conn.execute("""
        SELECT m.director, count(*) cnt, avg(ui.rating) avg_r
        FROM media_items m JOIN user_interactions ui ON ui.media_id=m.id
        WHERE m.director IS NOT NULL AND ui.rating IS NOT NULL
          AND m.media_type IN ('film','movie')
        GROUP BY m.director HAVING count(*) >= 4
        ORDER BY cnt DESC, avg_r DESC LIMIT 10
    """).fetchall()
    def _dir_row(d):
        name = d["director"].replace("'", "\\'")
        return (f'<tr><td><span style="cursor:pointer;color:var(--cobalt)" '
                f'onclick="showDirectorDetail(\'{name}\')">{d["director"]}</span></td>'
                f'<td>{d["cnt"]}</td><td>{d["avg_r"]:.1f}★</td></tr>')

    directors_by_rating_html = "".join(_dir_row(d) for d in top_directors_by_rating)
    directors_by_count_html  = "".join(_dir_row(d) for d in top_directors_by_count)

    # ── Genre chart ───────────────────────────────────────────────────────────
    genre_chart = svg_bar_chart(profile.get("genre_fingerprint", {}), color="#1a4fa0")
    film_genre_chart = svg_bar_chart(profile.get("film_genre_fingerprint", {}), color="#c94c1a")
    rating_hist = svg_rating_histogram(book_ratings)
    film_rating_hist = svg_rating_histogram(film_ratings, color="#c94c1a")

    # ── Series tracker ────────────────────────────────────────────────────────
    series_html = ""
    for s in series_data:
        name = s["series_name"]
        n = s["read_count"]
        avg = f'{s["avg_rating"]:.1f}★' if s["avg_rating"] else "—"
        series_html += (
            f'<div class="series-row">'
            f'<span class="series-name">{name}</span>'
            f'<span class="series-count">{n} read · avg {avg}</span>'
            f'</div>'
        )

    # ── Clusters ──────────────────────────────────────────────────────────────
    clusters_html = ""
    for c in profile.get("taste_clusters", []):
        items_str = " · ".join(f'<em>{i}</em>' for i in c.get("items", [])[:5])
        clusters_html += (
            f'<div class="card cluster-card">'
            f'<div class="cluster-name">{c["name"]}</div>'
            f'<div class="cluster-desc">{c["description"]}</div>'
            f'<div class="cluster-items">{items_str}</div>'
            f'</div>'
        )

    # ── Spotify HTML ──────────────────────────────────────────────────────────
    spotify_artists_html = svg_bar_chart(
        {r["artist"]: r["plays"] for r in spotify_top_artists}, color="#0d7e6b",
        onclick="showArtistDetail('{safe}')"
    ) if spotify_top_artists else "<p class='dim'>No Spotify data yet.</p>"

    spotify_year_rows = ""
    for r in spotify_by_year:
        spotify_year_rows += (
            f'<tr><td>{r["yr"]}</td>'
            f'<td>{r["plays"]:,}</td>'
            f'<td>{r["hrs"]:.0f}h</td></tr>'
        )
    spotify_total_plays = f'{spotify_stats["total_plays"]:,}'
    spotify_total_hours = f'{spotify_stats["total_hours"]:.0f}'
    spotify_total_artists = f'{spotify_stats["total_artists"]:,}'

    # ── Music deep-dive data ──────────────────────────────────────────────────
    top_tracks = []
    top_albums = []
    artist_sprint = {}  # yr -> list of (artist, cnt)
    if spotify_exists:
        top_tracks = conn.execute("""
            SELECT track, artist, count(*) plays
            FROM spotify_plays
            WHERE artist IS NOT NULL AND track IS NOT NULL
              AND artist != 'sleep-o-phant'
            GROUP BY track, artist ORDER BY plays DESC LIMIT 10
        """).fetchall()
        top_albums = conn.execute("""
            SELECT album, artist, count(*) plays
            FROM spotify_plays
            WHERE album IS NOT NULL AND artist != 'sleep-o-phant'
            GROUP BY album ORDER BY plays DESC LIMIT 10
        """).fetchall()
        sprint_rows = conn.execute("""
            WITH ranked AS (
              SELECT substr(ended_at,1,4) yr, artist, count(*) cnt,
                     row_number() OVER (PARTITION BY substr(ended_at,1,4) ORDER BY count(*) DESC) rn
              FROM spotify_plays
              WHERE artist IS NOT NULL AND artist != 'sleep-o-phant'
                AND substr(ended_at,1,4) BETWEEN '2018' AND '2026'
              GROUP BY yr, artist
            )
            SELECT yr, artist, cnt FROM ranked WHERE rn <= 5 ORDER BY yr, rn
        """).fetchall()
        for r in sprint_rows:
            artist_sprint.setdefault(r["yr"], []).append((r["artist"], r["cnt"]))

    # ── Music HTML ────────────────────────────────────────────────────────────
    top_tracks_html = ""
    for i, r in enumerate(top_tracks, 1):
        top_tracks_html += (
            f'<div style="display:flex;align-items:baseline;gap:8px;padding:7px 0;border-bottom:1px solid var(--border)">'
            f'<span style="font-size:11px;font-weight:700;color:var(--text-dim);width:16px;flex-shrink:0">{i}</span>'
            f'<div style="flex:1;min-width:0">'
            f'<div style="font-size:13px;font-weight:600;color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis">{r["track"]}</div>'
            f'<div style="font-size:11px;color:var(--text-dim)">{r["artist"]}</div>'
            f'</div>'
            f'<span style="font-size:12px;font-weight:600;color:var(--accent-music);flex-shrink:0">{r["plays"]:,}</span>'
            f'</div>'
        )

    top_albums_html = ""
    for i, r in enumerate(top_albums, 1):
        top_albums_html += (
            f'<div style="display:flex;align-items:baseline;gap:8px;padding:7px 0;border-bottom:1px solid var(--border)">'
            f'<span style="font-size:11px;font-weight:700;color:var(--text-dim);width:16px;flex-shrink:0">{i}</span>'
            f'<div style="flex:1;min-width:0">'
            f'<div style="font-size:13px;font-weight:600;color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis">{r["album"]}</div>'
            f'<div style="font-size:11px;color:var(--text-dim)">{r["artist"]}</div>'
            f'</div>'
            f'<span style="font-size:12px;font-weight:600;color:var(--accent-music);flex-shrink:0">{r["plays"]:,}</span>'
            f'</div>'
        )

    # Artist sprint: year-by-year top 5 as a ranked table
    sprint_years = sorted(artist_sprint.keys())
    sprint_html = ""
    if sprint_years:
        sprint_html += '<div style="overflow-x:auto"><table style="min-width:500px">'
        sprint_html += '<tr><th style="width:48px">Year</th>'
        for rank in range(1, 6):
            sprint_html += f'<th>#{rank}</th>'
        sprint_html += '</tr>'
        for yr in sprint_years:
            artists = artist_sprint.get(yr, [])
            sprint_html += f'<tr><td style="font-weight:700;color:var(--text)">{yr}</td>'
            for rank in range(5):
                if rank < len(artists):
                    name, cnt = artists[rank]
                    color = "var(--accent-music)" if rank == 0 else "var(--text)"
                    safe_name = name.replace("'", "\\'")
                    sprint_html += f'<td style="color:{color};font-size:12px;cursor:pointer" onclick="showArtistDetail(\'{safe_name}\')">{name}<span style="color:var(--text-dim);font-size:10px;margin-left:4px">{cnt:,}</span></td>'
                else:
                    sprint_html += '<td></td>'
            sprint_html += '</tr>'
        sprint_html += '</table></div>'

    # ── YouTube HTML ──────────────────────────────────────────────────────────
    yt_foreground  = yt_class_split.get("foreground",  {}).get("cnt", 0)
    yt_ambient     = yt_class_split.get("ambient",     {}).get("cnt", 0)
    yt_childcare   = yt_class_split.get("childcare_background", {}).get("cnt", 0)
    yt_social      = yt_class_split.get("social_background",    {}).get("cnt", 0)
    yt_fg_hrs      = yt_class_split.get("foreground",  {}).get("hours", 0)

    yt_channels_html = ""
    if yt_top_channels:
        max_min = max(r["capped_min"] for r in yt_top_channels) or 1
        for r in yt_top_channels:
            w   = round(r["capped_min"] / max_min * 100, 1)
            lbl = f"{round(r['capped_min'])}min · {r['videos']}v"
            yt_channels_html += (
                f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:5px">'
                f'<div style="width:130px;font-size:11px;text-align:right;color:var(--text-dim);'
                f'white-space:nowrap;overflow:hidden;text-overflow:ellipsis;flex-shrink:0">{r["channel"]}</div>'
                f'<div style="flex:1;height:14px;background:rgba(26,22,18,0.1);border-radius:2px;overflow:hidden">'
                f'<div style="width:{w}%;height:100%;background:#cc0000;border-radius:2px"></div></div>'
                f'<div style="font-size:10px;font-weight:600;color:var(--text);'
                f'width:72px;flex-shrink:0;text-align:right">{lbl}</div>'
                f'</div>'
            )
    else:
        yt_channels_html = "<p class='dim'>Run ingest_youtube.py first.</p>"

    yt_monthly_html = ""
    if yt_monthly:
        max_m = max(r["cnt"] for r in yt_monthly) or 1
        for r in yt_monthly:
            w = round(r["cnt"] / max_m * 100, 1)
            yt_monthly_html += (
                f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">'
                f'<div style="width:56px;font-size:10px;text-align:right;color:var(--text-dim);flex-shrink:0">'
                f'{_fmt_month(r["month"])}</div>'
                f'<div style="flex:1;height:14px;background:rgba(26,22,18,0.1);border-radius:2px;overflow:hidden">'
                f'<div style="width:{w}%;height:100%;background:#cc0000;border-radius:2px"></div></div>'
                f'<div style="font-size:10px;font-weight:600;color:var(--text);'
                f'width:28px;flex-shrink:0;text-align:right">{r["cnt"]}</div>'
                f'</div>'
            )
    else:
        yt_monthly_html = "<p class='dim'>No foreground watch data.</p>"

    yt_yearly_html = ""
    if yt_yearly:
        max_y = max(r["capped_min"] for r in yt_yearly) or 1
        for r in yt_yearly:
            w   = round(r["capped_min"] / max_y * 100, 1)
            hrs = round(r["capped_min"] / 60, 1)
            yt_yearly_html += (
                f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:5px">'
                f'<div style="width:36px;font-size:11px;text-align:right;color:var(--text-dim);flex-shrink:0">{r["yr"]}</div>'
                f'<div style="flex:1;height:16px;background:rgba(26,22,18,0.1);border-radius:2px;overflow:hidden">'
                f'<div style="width:{w}%;height:100%;background:#cc0000;border-radius:2px"></div></div>'
                f'<div style="font-size:10px;font-weight:600;color:var(--text);'
                f'width:54px;flex-shrink:0;text-align:right">{hrs}h · {r["cnt"]}v</div>'
                f'</div>'
            )
    else:
        yt_yearly_html = "<p class='dim'>No data.</p>"

    # Curiosity trails
    yt_trails_html = ""
    if yt_trails:
        max_score = max(t["interest_score"] for t in yt_trails) or 1
        for trail in yt_trails:
            w    = round(trail["interest_score"] / max_score * 100, 1)
            hrs  = round(trail["capped_min"] / 60, 1)
            rr   = trail["return_rate"]
            rr_color = "#cc0000" if rr >= 1.5 else ("var(--text)" if rr >= 1.0 else "var(--text-dim)")
            yt_trails_html += (
                f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:5px">'
                f'<div style="width:140px;font-size:11px;text-align:right;color:var(--text-dim);'
                f'white-space:nowrap;overflow:hidden;text-overflow:ellipsis;flex-shrink:0">{trail["topic"]}</div>'
                f'<div style="flex:1;height:14px;background:rgba(26,22,18,0.1);border-radius:2px;overflow:hidden">'
                f'<div style="width:{w}%;height:100%;background:#cc0000;border-radius:2px"></div></div>'
                f'<div style="font-size:10px;font-weight:600;color:var(--text);width:38px;flex-shrink:0;text-align:right">{hrs}h</div>'
                f'<div style="font-size:10px;color:{rr_color};width:30px;flex-shrink:0;text-align:right" title="return rate">{rr}↩</div>'
                f'</div>'
            )
    else:
        yt_trails_html = "<p class='dim'>Run enrichment to generate curiosity trails.</p>"

    # ── Tree Ring Visualization ───────────────────────────────────────────────
    TOPIC_RING_COLORS = {
        'One Piece analysis': '#e8a000', 'anime': '#f39c12',
        'sketch comedy': '#4a90d9',      'SNL': '#4a90d9',       'The Office': '#3a7dc9',
        'entrepreneur TV': '#27ae60',    'startup pitching': '#27ae60',
        'music': '#9b59b6',             'music video': '#8e44ad',
        'electronic music': '#6c3483',  'Berlin club scene': '#5b2c6f',
        'film': '#e74c3c',              'trailer': '#c0392b',
        'documentary': '#d35400',       'history': '#ca6f1e',
        'apartment DIY': '#7f8c8d',     'home maintenance': '#717d7e',
        'magic': '#1abc9c',             'mentalism': '#17a589',
        'board games': '#16a085',       'tabletop': '#148f77',
        'AI tools': '#2c3e50',          'science': '#2980b9',
        'nature': '#28b463',            'comedy': '#5dade2',
        'indie folk': '#a9cce3',        'indie rock': '#7fb3d3',
        'Belgian music': '#e8d5b7',     'self-help': '#f0b27a',
        'internet culture': '#aab7b8',
    }
    AMBIENT_RING_COLORS = {
        'ambient': '#adb5bd',
        'childcare_background': '#dee2e6',
        'social_background': '#c4b5d4',
        'foreground': None,  # handled by topic
    }

    def ring_color(ambient_class, topics_json):
        if ambient_class != 'foreground':
            return AMBIENT_RING_COLORS.get(ambient_class, '#adb5bd')
        try:
            topics = json.loads(topics_json or '[]')
            for t in topics:
                if t in TOPIC_RING_COLORS:
                    return TOPIC_RING_COLORS[t]
        except Exception:
            pass
        return '#5d9cec'

    yt_ring_html = ""
    if yt_ring_rows:
        from collections import defaultdict as _dd
        by_yr = _dd(list)
        for r in yt_ring_rows:
            by_yr[r['yr']].append(r)

        years = sorted(by_yr.keys())
        max_capped = max(
            sum(min(v['duration_sec'] / 60.0, 90) for v in vids)
            for vids in by_yr.values()
        ) or 1

        legend_items = [
            ('#e8a000','One Piece'), ('#f39c12','Anime'), ('#4a90d9','Comedy'),
            ('#27ae60','Entrepreneur'), ('#9b59b6','Music'), ('#e74c3c','Film'),
            ('#d35400','Documentary'), ('#7f8c8d','DIY'), ('#1abc9c','Magic'),
            ('#16a085','Board Games'), ('#2c3e50','AI'), ('#dee2e6','Background'),
            ('#5d9cec','Other'),
        ]
        legend_html = "".join(
            f'<span style="display:inline-flex;align-items:center;gap:3px;margin-right:8px;font-size:10px;color:var(--text-dim)">'
            f'<span style="width:10px;height:10px;background:{c};border-radius:2px;flex-shrink:0"></span>{lbl}</span>'
            for c, lbl in legend_items
        )

        rows_html = ""
        for yr in years:
            vids = by_yr[yr]
            year_capped = sum(min(v['duration_sec'] / 60.0, 90) for v in vids)
            strip_pct = round(year_capped / max_capped * 100, 1)
            segs = ""
            for v in vids:
                capped = min(v['duration_sec'] / 60.0, 90)
                seg_pct = round(capped / year_capped * 100, 2) if year_capped else 0
                col = ring_color(v['ambient_class'], v['topics'])
                _ac = v['ambient_class']
                segs += (
                    f'<div style="width:{seg_pct}%;height:100%;background:{col};'
                    f'flex-shrink:0" title="{_ac}"></div>'
                )
            rows_html += (
                f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">'
                f'<div style="width:32px;font-size:10px;text-align:right;color:var(--text-dim);flex-shrink:0">{yr}</div>'
                f'<div style="width:{strip_pct}%;max-width:calc(100% - 100px);height:18px;'
                f'display:flex;flex-direction:row;overflow:hidden;border-radius:2px;flex-shrink:0">'
                f'{segs}</div>'
                f'<div style="font-size:10px;color:var(--text-dim)">{round(year_capped/60,1)}h · {len(vids)}v</div>'
                f'</div>'
            )

        yt_ring_html = (
            f'<div style="margin-bottom:10px;line-height:1.6">{legend_html}</div>'
            f'{rows_html}'
        )
    else:
        yt_ring_html = "<p class='dim'>Run ingest_youtube.py to generate tree ring.</p>"

    # ── Spotify × YouTube context ─────────────────────────────────────────────
    yt_spotify_html = ""
    if yt_spotify_context:
        avg_yt  = yt_spotify_context["avg_on_yt_days"]
        avg_no  = yt_spotify_context["avg_off_yt_days"]
        yt_days = yt_spotify_context["total_yt_days"]
        both    = yt_spotify_context["yt_days_with_sp"]
        delta   = round(avg_yt - avg_no, 1)
        direction = "less" if delta < 0 else "more"
        yt_spotify_html = (
            f'<div style="margin-bottom:14px">'
            f'<div style="font-size:28px;font-weight:800;color:var(--accent-music);font-family:\'Lora\',serif;line-height:1">'
            f'{abs(delta)}min</div>'
            f'<div style="font-size:12px;color:var(--text-dim);margin-top:4px">'
            f'{direction} Spotify on YouTube days vs non-YouTube days<br>'
            f'({avg_yt}min avg on YouTube days · {avg_no}min avg otherwise)</div>'
            f'</div>'
            f'<div style="font-size:12px;color:var(--text-dim)">'
            f'{both} of {yt_days} YouTube days also had Spotify activity '
            f'({round(both/yt_days*100) if yt_days else 0}%)</div>'
        )

    # Life chapters
    yt_chapters_html = ""
    if yt_chapters:
        for ch in yt_chapters:
            yr_start = ch["start_date"][:4]
            yr_end   = ch["end_date"][:4]
            yr_label = yr_start if yr_start == yr_end else f"{yr_start}–{yr_end}"
            yt_chapters_html += (
                f'<div style="border-left:3px solid #cc0000;padding:10px 14px;margin-bottom:12px">'
                f'<div style="display:flex;align-items:baseline;gap:12px">'
                f'<span style="font-size:11px;font-weight:700;color:#cc0000;'
                f'text-transform:uppercase;letter-spacing:.06em;flex-shrink:0">{yr_label}</span>'
                f'<span style="font-size:14px;font-weight:700;color:var(--text)">{ch["name"]}</span>'
                f'</div>'
                f'<div style="font-size:12px;color:var(--text-dim);margin-top:4px;line-height:1.5">{ch["summary"]}</div>'
                f'</div>'
            )
    else:
        yt_chapters_html = "<p class='dim'>Run enrich_youtube.py to generate life chapters.</p>"

    # ── TikTok HTML ───────────────────────────────────────────────────────────
    tiktok_monthly_html = ""
    if tiktok_monthly:
        max_m = max(r["cnt"] for r in tiktok_monthly) or 1
        for r in tiktok_monthly:
            w = round(r["cnt"] / max_m * 100, 1)
            tiktok_monthly_html += (
                f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">'
                f'<div style="width:56px;font-size:10px;text-align:right;color:var(--text-dim);flex-shrink:0">{_fmt_month(r["month"])}</div>'
                f'<div style="flex:1;height:14px;background:rgba(26,22,18,0.1);border-radius:2px;overflow:hidden">'
                f'<div style="width:{w}%;height:100%;background:#fe2c55;border-radius:2px"></div></div>'
                f'<div style="font-size:10px;font-weight:600;color:var(--text);width:44px;flex-shrink:0;text-align:right">{r["cnt"]:,}</div>'
                f'</div>'
            )
    else:
        tiktok_monthly_html = "<p class='dim'>No watch history data.</p>"

    tiktok_hours_html = ""
    if tiktok_hours:
        hr_map = {r["hr"]: r["cnt"] for r in tiktok_hours}
        max_hr = max(hr_map.values()) or 1
        for hr in range(24):
            cnt = hr_map.get(hr, 0)
            if cnt == 0:
                continue
            w = round(cnt / max_hr * 100, 1)
            hr_label = f"{hr:02d}:00"
            tiktok_hours_html += (
                f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:3px">'
                f'<div style="width:40px;font-size:10px;text-align:right;color:var(--text-dim);flex-shrink:0">{hr_label}</div>'
                f'<div style="flex:1;height:12px;background:rgba(26,22,18,0.1);border-radius:2px;overflow:hidden">'
                f'<div style="width:{w}%;height:100%;background:#25f4ee;border-radius:2px"></div></div>'
                f'<div style="font-size:10px;font-weight:600;color:var(--text);width:44px;flex-shrink:0;text-align:right">{cnt:,}</div>'
                f'</div>'
            )
    else:
        tiktok_hours_html = "<p class='dim'>No data.</p>"

    enrich_success = tiktok_enrichment["success"]
    enrich_pending = tiktok_enrichment["pending"]
    enrich_failed  = tiktok_enrichment["failed"]
    enrich_eligible = enrich_success + enrich_pending + enrich_failed

    if enrich_success > 0:
        _pct_ok  = round(enrich_success / enrich_eligible * 100) if enrich_eligible else 0
        _pct_bad = round(enrich_failed  / enrich_eligible * 100) if enrich_eligible else 0
        _enrich_bar = (
            f'<div class="dim" style="font-size:12px;margin-bottom:8px">'
            f'{enrich_success:,} enriched · {enrich_pending:,} pending · {enrich_failed:,} failed</div>'
            f'<div style="height:8px;background:rgba(26,22,18,0.1);border-radius:2px;overflow:hidden;display:flex;margin-bottom:16px">'
            f'<div style="width:{_pct_ok}%;background:#25f4ee"></div>'
            f'<div style="width:{_pct_bad}%;background:#fe2c55;opacity:.7"></div>'
            f'</div>'
        )
        if tiktok_top_hashtags:
            _max_tag = tiktok_top_hashtags[0][1] or 1
            _tags_html = ""
            for tag, cnt in tiktok_top_hashtags:
                _w = round(cnt / _max_tag * 100, 1)
                _tags_html += (
                    f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:3px">'
                    f'<div style="width:110px;font-size:11px;text-align:right;color:var(--text-dim);flex-shrink:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">#{tag}</div>'
                    f'<div style="flex:1;height:12px;background:rgba(26,22,18,0.1);border-radius:2px;overflow:hidden">'
                    f'<div style="width:{_w}%;height:100%;background:#25f4ee;border-radius:2px"></div></div>'
                    f'<div style="font-size:10px;font-weight:600;color:var(--text);width:32px;flex-shrink:0;text-align:right">{cnt}</div>'
                    f'</div>'
                )
            _hashtags_section = f'<h3 style="font-size:13px;margin:0 0 8px">Top Hashtags</h3>{_tags_html}'
        else:
            _hashtags_section = '<p class="dim" style="font-size:12px">No hashtag data yet — enrichment in progress.</p>'
        tiktok_enrich_html = (
            f'<div class="panel"><h2>Content Enrichment</h2>'
            f'{_enrich_bar}'
            f'{_hashtags_section}'
            f'</div>'
        )
    else:
        tiktok_enrich_html = (
            f'<div class="panel"><h2>Content Enrichment</h2>'
            f'<p class="dim" style="font-size:13px;line-height:1.6">'
            f'{enrich_pending:,} videos eligible (liked + favorited).<br>'
            f'Run <code>python3 scripts/enrich_tiktok.py --limit 20</code> to test, '
            f'then the full run. Hashtag and category analysis will appear here.</p></div>'
        )

    # ── Cross-platform category comparison HTML ───────────────────────────────
    if tiktok_category_comparison:
        _max_tk = max((t for _, t, _ in tiktok_category_comparison), default=1) or 1
        _max_yt = max((y for _, _, y in tiktok_category_comparison), default=1) or 1
        _scale = max(_max_tk, _max_yt)
        _cat_rows_html = ""
        for cat, tk_n, yt_n in tiktok_category_comparison:
            _tw = round(tk_n / _scale * 100, 1)
            _yw = round(yt_n / _scale * 100, 1)
            _cat_rows_html += (
                f'<div style="margin-bottom:6px">'
                f'<div style="font-size:11px;color:var(--text-dim);margin-bottom:2px">{cat}</div>'
                f'<div style="display:flex;gap:4px;align-items:center">'
                f'<div style="width:90px;font-size:10px;text-align:right;color:#fe2c55;flex-shrink:0">TikTok {tk_n}</div>'
                f'<div style="flex:1;height:10px;background:rgba(26,22,18,0.1);border-radius:2px;overflow:hidden">'
                f'<div style="width:{_tw}%;height:100%;background:#fe2c55;opacity:.8;border-radius:2px"></div></div>'
                f'</div>'
                f'<div style="display:flex;gap:4px;align-items:center;margin-top:2px">'
                f'<div style="width:90px;font-size:10px;text-align:right;color:#ff0000;flex-shrink:0">YouTube {yt_n}</div>'
                f'<div style="flex:1;height:10px;background:rgba(26,22,18,0.1);border-radius:2px;overflow:hidden">'
                f'<div style="width:{_yw}%;height:100%;background:#ff0000;opacity:.6;border-radius:2px"></div></div>'
                f'</div>'
                f'</div>'
            )
        tiktok_crossplatform_html = (
            f'<div class="panel"><h2>TikTok × YouTube — Content Interests</h2>'
            f'<div class="dim" style="font-size:11px;margin-bottom:12px">TikTok = liked + favorited · YouTube = intentional watches</div>'
            f'{_cat_rows_html}</div>'
        )
    else:
        tiktok_crossplatform_html = ""

    # ── Consumption modes HTML ────────────────────────────────────────────────
    if consumption_modes:
        _total_days = sum(n for _, n in consumption_modes) or 1
        _mode_html = ""
        _mode_colors = {
            "TikTok-heavy": "#fe2c55",
            "YouTube-heavy": "#ff0000",
            "Music-heavy": "#1db954",
            "Mixed": "#25f4ee",
            "Light": "rgba(100,100,100,0.4)",
        }
        for mode, cnt in consumption_modes:
            _pct = round(cnt / _total_days * 100)
            _col = _mode_colors.get(mode, "#888")
            _mode_html += (
                f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">'
                f'<div style="width:110px;font-size:11px;text-align:right;color:var(--text-dim);flex-shrink:0">{mode}</div>'
                f'<div style="flex:1;height:12px;background:rgba(26,22,18,0.1);border-radius:2px;overflow:hidden">'
                f'<div style="width:{_pct}%;height:100%;background:{_col};border-radius:2px"></div></div>'
                f'<div style="font-size:10px;font-weight:600;width:48px;flex-shrink:0">{cnt:,}d ({_pct}%)</div>'
                f'</div>'
            )
        consumption_modes_html = (
            f'<div class="panel"><h2>Daily Consumption Modes</h2>'
            f'<div class="dim" style="font-size:11px;margin-bottom:10px">Classified by dominant platform signal per day · {_total_days:,} days with activity</div>'
            f'{_mode_html}</div>'
        )
    else:
        consumption_modes_html = ""

    # ── Podcasts HTML ─────────────────────────────────────────────────────────
    HUGE_FAN = {"99% Invisible", "The Moth", "Life in Scents", "Snap Judgment",
                "Serial", "Radiolab", "Love and Radio", "Science Vs",
                "Reply All", "Rough Translation", "Strangers", "Hidden Brain",
                "Dolly Parton's America"}
    podcasts_html = ""
    for p in podcasts:
        stars = "★" * int(p["rating"] or 0) if p["rating"] else "—"
        tag = " · <span style='font-size:11px;font-weight:700;color:var(--teal);text-transform:uppercase;letter-spacing:.06em'>Huge fan</span>" if p["title"] in HUGE_FAN else ""
        podcasts_html += (
            f'<div class="series-row" style="align-items:center">'
            f'<span class="series-name">{p["title"]}{tag}</span>'
            f'<span style="color:var(--gold);font-size:13px">{stars}</span>'
            f'</div>'
        )

    # ── Comics HTML ───────────────────────────────────────────────────────────
    comic_series_html = ""
    for s in comic_series:
        yr_range = f"{s['year_from']}–{s['year_to']}" if s["year_from"] != s["year_to"] else str(s["year_from"] or "")
        author = s["author"] or ""
        comic_series_html += (
            f'<div class="series-row">'
            f'<div>'
            f'<span class="series-name">{s["series_name"]}</span>'
            f'<span class="dim" style="margin-left:8px;font-size:12px">{author}</span>'
            f'</div>'
            f'<span class="series-count">{s["album_count"]} albums · {yr_range}</span>'
            f'</div>'
        )

    comic_standalone_html = ""
    for a in comic_standalone:
        comic_standalone_html += (
            f'<tr><td>{a["title"]}</td>'
            f'<td class="dim">{a["author"] or ""}</td>'
            f'<td class="dim">{a["year"] or ""}</td></tr>'
        )

    # ── Films & Series HTML ───────────────────────────────────────────────────
    def media_row(title: str, date: str, media_type: str = "film") -> str:
        d = date[:7] if date else ""
        safe = title.replace("'", "\\'")
        mt = "tv" if media_type == "tv_show" else ("book" if media_type == "book" else "film")
        return (f'<tr><td><span style="cursor:pointer;color:var(--cobalt)" '
                f'onclick="searchAndShowDetail(\'{safe}\',\'{mt}\')">{title}</span></td>'
                f'<td class="dim">{d}</td></tr>')

    recent_shows_html = "".join(media_row(r["title"], r["date_completed"], "tv_show") for r in recent_shows) \
        or "<tr><td class='dim' colspan='2'>No data</td></tr>"
    recent_films_html = "".join(media_row(r["title"], r["date_completed"], "film") for r in recent_films) \
        or "<tr><td class='dim' colspan='2'>No data</td></tr>"
    recent_rated_html = ""
    for r in recent_rated:
        stars = "👍" if (r["rating"] or 0) >= 3.5 else "👎"
        recent_rated_html += f'<tr><td>{r["title"]}</td><td>{stars}</td></tr>'
    total_shows = all_counts["shows"] or 0
    total_films = all_counts["films"] or 0

    # ── Themes + Dislikes ─────────────────────────────────────────────────────
    cal = profile.get("rating_calibration", {})
    themes_html = "".join(f'<li>{t}</li>' for t in profile.get("top_themes", []))
    dislikes_html = "".join(f'<li>{d}</li>' for d in profile.get("dislikes_pattern", []))

    # ── Recommendations ───────────────────────────────────────────────────────
    def rec_card(r: dict) -> str:
        rid = r["id"]
        conf_pct = int(r.get("confidence", 0) * 100)
        mt = r["media_type"]
        if mt == "tv_show":
            badge, wl_label, api_type = "📺", "Want to watch", "tv"
        elif mt == "film":
            badge, wl_label, api_type = "🎬", "Want to watch", "film"
        elif mt == "music":
            badge, wl_label, api_type = "🎵", "Want to listen", "music"
        elif mt == "podcast":
            badge, wl_label, api_type = "🎙️", "Follow", "podcast"
        elif mt == "comic":
            badge, wl_label, api_type = "🗯️", "Want to read", "book"
        else:
            badge, wl_label, api_type = "📖", "Want to read", "book"
        safe_title = r["title"].replace("'", "\\'").replace('"', '&quot;')
        stars = "".join(
            f'<span class="star" id="s-{rid}-{i}" onclick="rateRec({rid},{i})" '
            f'onmouseenter="hoverStars({rid},{i})" onmouseleave="resetStars({rid})">★</span>'
            for i in range(1, 6)
        )
        return (
            f'<div class="card rec-card" id="rec-{rid}" style="cursor:pointer" data-title="{safe_title}" data-type="{api_type}" onclick="searchAndShowDetail(\'{safe_title}\',\'{api_type}\')">'
            f'<div class="rec-header">'
            f'<span class="rec-badge">{badge}</span>'
            f'<div class="rec-title-block">'
            f'<strong>{r["title"]}</strong><br>'
            f'<span class="dim">{r.get("author_or_director","")}{(" · " + str(r["year"])) if r.get("year") else ""}</span>'
            f'</div>'
            f'<span class="rec-conf">{conf_pct}%</span>'
            f'</div>'
            f'<p class="rec-reason">{r.get("reason","")}</p>'
            f'<p class="rec-friction">⚠️ {r.get("potential_issue","")}</p>'
            f'<div class="rec-actions" onclick="event.stopPropagation()">'
            f'<div class="star-row" id="stars-{rid}">{stars}</div>'
            f'<span class="rated-badge" id="rated-{rid}" style="display:none"></span>'
            f'<button class="action-btn watchlist" id="wl-{rid}" onclick="toggleWatchlist({rid},this)">{wl_label}</button>'
            f''
            f'<button class="action-btn dismiss" onclick="dismiss({rid})">Dismiss</button>'
            f'</div>'
            f'</div>'
        )

    all_recs_html = "".join(rec_card(r) for r in recs) or "<p class='dim'>No recommendations loaded yet.</p>"

    # ── Authors table ─────────────────────────────────────────────────────────
    authors_html = ""
    for a in top_authors:
        avg = f'{a["avg_r"]:.1f}' if a["avg_r"] else "—"
        authors_html += f'<tr><td>{a["author"]}</td><td>{a["n"]}</td><td>{avg}★</td></tr>'

    # ── To-read queue ─────────────────────────────────────────────────────────
    to_read_html = ""
    for b in to_read:
        series = f' <span class="dim">({b["series_name"]} #{int(b["series_pos"]) if b["series_pos"] else "?"})</span>' if b["series_name"] else ""
        to_read_html += f'<tr><td>{b["title"]}{series}</td><td class="dim">{b["author"] or ""}</td></tr>'

    # ── Films KPI HTML ────────────────────────────────────────────────────────
    total_screen = n_films + n_series
    film_pct  = round(n_films  / total_screen * 100) if total_screen else 0
    series_pct = round(n_series / total_screen * 100) if total_screen else 0

    def inline_bar_chart(items, color, fmt=lambda v: str(v)):
        """Horizontal bar chart from list of (label, value) tuples."""
        if not items:
            return "<p class='dim'>No data.</p>"
        max_v = max(v for _, v in items) or 1
        rows = []
        for label, val in items:
            w = round(val / max_v * 100, 1)
            rows.append(
                f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:6px">'
                f'<div style="width:56px;font-size:11px;text-align:right;color:var(--text-dim);flex-shrink:0">{label}</div>'
                f'<div style="flex:1;height:18px;background:rgba(26,22,18,0.1);border-radius:2px;overflow:hidden">'
                f'<div style="width:{w}%;height:100%;background:{color};border-radius:2px"></div></div>'
                f'<div style="font-size:11px;font-weight:600;color:var(--text);width:36px;flex-shrink:0;text-align:right">{fmt(val)}</div>'
                f'</div>'
            )
        return "\n".join(rows)

    # Films watched per year stacked chart (films + series side by side)
    all_years = sorted(set([r["yr"] for r in films_by_year] + [r["yr"] for r in series_by_year]))
    film_yr_map  = {r["yr"]: r["cnt"] for r in films_by_year}
    series_yr_map = {r["yr"]: r["cnt"] for r in series_by_year}
    max_yr_val = max((film_yr_map.get(y,0) + series_yr_map.get(y,0)) for y in all_years) if all_years else 1

    watched_by_year_html = ""
    for yr in all_years:
        fc = film_yr_map.get(yr, 0)
        sc = series_yr_map.get(yr, 0)
        total = fc + sc
        fw = round(fc / max_yr_val * 100, 1)
        sw = round(sc / max_yr_val * 100, 1)
        watched_by_year_html += (
            f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:5px">'
            f'<div style="width:36px;font-size:11px;text-align:right;color:var(--text-dim);flex-shrink:0">{yr}</div>'
            f'<div style="flex:1;height:16px;background:rgba(26,22,18,0.08);border-radius:2px;overflow:hidden;display:flex">'
            f'<div style="width:{fw}%;height:100%;background:var(--accent-film)"></div>'
            f'<div style="width:{sw}%;height:100%;background:var(--accent-book);opacity:0.7"></div>'
            f'</div>'
            f'<div style="font-size:11px;font-weight:600;color:var(--text);width:32px;flex-shrink:0;text-align:right">{total}</div>'
            f'</div>'
        )
    watched_legend = (
        f'<div style="display:flex;gap:16px;margin-top:8px;font-size:11px;color:var(--text-dim)">'
        f'<span><span style="display:inline-block;width:10px;height:10px;background:var(--accent-film);border-radius:1px;margin-right:4px"></span>Films</span>'
        f'<span><span style="display:inline-block;width:10px;height:10px;background:var(--accent-book);opacity:0.7;border-radius:1px;margin-right:4px"></span>Series</span>'
        f'</div>'
    )

    # Films by decade of release
    decade_chart_html = inline_bar_chart(
        [(f"{r['decade']}s", r["cnt"]) for r in films_by_decade],
        color="var(--accent-film)"
    )

    # User rating distribution for films (1-5 stars)
    film_user_stars = {int(r["stars"]): r["cnt"] for r in film_user_rating_dist if r["stars"]}
    max_star_v = max(film_user_stars.values()) if film_user_stars else 1
    user_rating_html = '<div style="display:flex;align-items:flex-end;gap:6px;height:80px;padding-top:12px">'
    for s in range(1, 6):
        cnt = film_user_stars.get(s, 0)
        h = max(2, round(cnt / max_star_v * 64))
        user_rating_html += (
            f'<div style="display:flex;flex-direction:column;align-items:center;gap:3px;flex:1">'
            f'<div style="font-size:10px;color:var(--text-dim);font-weight:600">{cnt}</div>'
            f'<div style="width:100%;height:{h}px;background:var(--accent-film);border-radius:2px 2px 0 0"></div>'
            f'<div style="font-size:10px;color:var(--gold)">{"★"*s}</div>'
            f'</div>'
        )
    user_rating_html += '</div>'

    # ── Books KPI HTML ────────────────────────────────────────────────────────
    n_series_books   = next((r["cnt"] for r in book_series_counts if r["kind"] == "series"), 0)
    n_standalone_books = next((r["cnt"] for r in book_series_counts if r["kind"] == "standalone"), 0)
    n_books_total = n_series_books + n_standalone_books
    series_books_pct     = round(n_series_books     / n_books_total * 100) if n_books_total else 0
    standalone_books_pct = round(n_standalone_books / n_books_total * 100) if n_books_total else 0

    page_bucket_chart = inline_bar_chart(
        [(r["bucket"], r["cnt"]) for r in book_page_buckets],
        color="var(--accent-book)"
    )

    book_decade_chart = inline_bar_chart(
        [(f"{r['decade']}s", r["cnt"]) for r in book_by_decade],
        color="var(--accent-book)"
    )

    avg_pages = int(book_avg_pages["avg_p"]) if book_avg_pages and book_avg_pages["avg_p"] else "—"
    max_pages = int(book_avg_pages["max_p"]) if book_avg_pages and book_avg_pages["max_p"] else "—"

    # ── Render ────────────────────────────────────────────────────────────────
    total_consumed = (stats["books"] or 0) + (stats["audiobooks"] or 0) + (stats["films"] or 0) + (stats["shows"] or 0)
    mean_str = f'{cal.get("mean","—")}'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>My ears, my eyes and me</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2290%22>🎷</text></svg>">
<style>
  :root {{
    /* NASA Visions of the Future — cream + bold editorial */
    --bg: #f2ede4;
    --bg-panel: #faf7f2;
    --bg-card: #f5f0e8;
    --border: rgba(26,22,18,0.12);
    --border-dark: rgba(26,22,18,0.25);
    --text: #1a1612;
    --text-dim: #6b5f57;
    --rust:   #c94c1a;
    --cobalt: #1a4fa0;
    --gold:   #d4920a;
    --teal:   #0d7e6b;
    --crimson:#9b1c2e;
    /* Section accents — one bold per domain */
    --accent-film:     #c94c1a;
    --accent-book:     #1a4fa0;
    --accent-music:    #0d7e6b;
    --accent-patterns: #7e3a8a;
    --accent-recs:     #d4920a;
    --search-h: 68px;
  }}
  *, *::before, *::after {{ box-sizing:border-box; }}
  body {{
    background:var(--bg);
    color:var(--text);
    font-family:'Inter',system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
    margin:0; padding:0;
  }}
  .wrap {{ max-width:1000px; margin:0 auto; padding:0 24px 80px; }}
  .panel {{
    background:var(--bg-panel);
    border:1px solid var(--border);
    border-radius:4px;
    padding:20px;
    margin-bottom:20px;
    box-shadow:0 1px 4px rgba(26,22,18,0.06);
  }}
  .card {{
    background:var(--bg-card);
    border:1px solid var(--border);
    border-radius:3px;
    padding:16px;
    margin-bottom:12px;
  }}
  h1 {{ font-size:28px; font-weight:800; color:var(--text); margin-bottom:4px; font-family:'Lora',Georgia,serif; letter-spacing:-.02em; }}
  h2 {{ font-size:11px; font-weight:700; color:var(--text-dim); margin-bottom:16px; text-transform:uppercase; letter-spacing:.14em; }}
  h3 {{ font-size:14px; font-weight:600; color:var(--text); margin-bottom:8px; }}
  .dim {{ color:var(--text-dim); font-size:13px; }}
  .stat-bar {{ display:flex; gap:24px; margin-bottom:4px; flex-wrap:wrap; }}
  .stat {{ text-align:center; min-width:80px; }}
  .stat-n {{ font-size:28px; font-weight:800; color:var(--cobalt); font-family:'Lora',serif; }}
  .stat-l {{ font-size:11px; color:var(--text-dim); text-transform:uppercase; letter-spacing:.06em; }}
  .tabs {{ display:flex; gap:8px; margin-bottom:16px; flex-wrap:wrap; }}
  .tab {{ padding:8px 16px; border-radius:6px; cursor:pointer; font-size:14px; border:1px solid var(--border); background:var(--bg-card); color:var(--text-dim); min-height:44px; display:flex; align-items:center; }}
  .tab.active {{ background:#1f6feb; color:#fff; border-color:#1f6feb; }}
  .tab-content {{ display:none; }}
  .tab-content.active {{ display:block; }}
  .series-row {{ display:flex; justify-content:space-between; padding:10px 0; border-bottom:1px solid var(--border); }}
  .series-name {{ font-size:14px; color:var(--text); }}
  .series-count {{ font-size:13px; color:var(--text-dim); }}
  .cluster-card {{ margin-bottom:12px; }}
  .cluster-name {{ font-size:15px; font-weight:600; color:var(--accent-film); margin-bottom:6px; }}
  .cluster-desc {{ font-size:13px; color:var(--text-dim); margin-bottom:8px; line-height:1.5; }}
  .cluster-items {{ font-size:12px; color:var(--accent-book); }}
  .rec-card {{ position:relative; }}
  .rec-header {{ display:flex; align-items:flex-start; gap:10px; margin-bottom:8px; }}
  .rec-badge {{ font-size:20px; flex-shrink:0; }}
  .rec-title-block {{ flex:1; }}
  .rec-title-block strong {{ font-size:15px; color:var(--text); }}
  .rec-conf {{ font-size:13px; color:var(--accent-recs); font-weight:600; flex-shrink:0; }}
  .rec-reason {{ font-size:13px; color:var(--text-dim); margin-bottom:6px; line-height:1.5; }}
  .rec-friction {{ font-size:12px; color:#d29922; line-height:1.4; margin-bottom:10px; }}
  .rec-actions {{ display:flex; align-items:center; gap:8px; flex-wrap:wrap; }}
  .star-row {{ display:flex; gap:2px; }}
  .star {{ font-size:18px; cursor:pointer; color:var(--border-light); transition:color .15s; line-height:1; padding:6px 4px; }}
  .star.lit {{ color:var(--accent-film); }}
  .star:hover {{ color:var(--accent-film); }}
  .action-btn {{ font-size:12px; background:none; border:1px solid var(--border-dark); border-radius:2px; padding:7px 13px; cursor:pointer; white-space:nowrap; min-height:34px; display:inline-flex; align-items:center; transition:color .15s, border-color .15s, background .15s; color:var(--text-dim); letter-spacing:.03em; }}
  .action-btn.watchlist {{ color:var(--cobalt); border-color:rgba(26,79,160,0.3); }}
  .action-btn.watchlist:hover {{ border-color:var(--cobalt); background:rgba(26,79,160,0.08); }}
  .action-btn.watchlist.saved {{ color:var(--teal); border-color:rgba(13,126,107,0.4); background:rgba(13,126,107,0.08); }}
  .action-btn.dismiss:hover {{ color:var(--rust); border-color:rgba(201,76,26,0.4); }}
  .action-btn.detail-btn {{ color:var(--text-dim); }}
  .action-btn.detail-btn:hover {{ color:var(--gold); border-color:rgba(212,146,10,0.4); }}
  .rated-badge {{ font-size:12px; color:var(--accent-film); font-weight:600; }}
  table {{ width:100%; border-collapse:collapse; }}
  td, th {{ padding:10px; text-align:left; border-bottom:1px solid var(--border); font-size:13px; }}
  th {{ color:var(--text-dim); font-weight:500; }}
  li {{ margin-bottom:6px; font-size:13px; color:var(--text-dim); line-height:1.5; }}
  .grid-2 {{ display:grid; grid-template-columns:1fr 1fr; gap:20px; }}
  @media(max-width:700px) {{ .grid-2 {{ grid-template-columns:1fr; }} }}
  /* Search bar */
  #search-bar {{ position:sticky; top:0; z-index:100; background:var(--cobalt); border-bottom:3px solid var(--gold); padding:10px 24px; margin:0 -24px 0; }}
  .search-row {{ max-width:1000px; margin:0 auto; display:flex; gap:8px; align-items:center; }}
  #search-input {{ flex:1; background:rgba(255,255,255,0.15); border:2px solid rgba(255,255,255,0.3); border-radius:2px; padding:10px 14px; color:#fff; font-size:14px; outline:none; min-height:44px; transition:border-color .2s; }}
  #search-input:focus {{ border-color:#fff; background:rgba(255,255,255,0.22); }}
  #search-input::placeholder {{ color:rgba(255,255,255,0.55); }}
  #search-type {{ background:rgba(255,255,255,0.12); border:2px solid rgba(255,255,255,0.25); border-radius:2px; padding:10px; color:#fff; font-size:13px; min-height:44px; }}
  #search-btn {{ background:var(--gold); border:none; border-radius:2px; padding:10px 18px; color:var(--text); font-size:13px; cursor:pointer; white-space:nowrap; min-height:44px; font-weight:700; transition:opacity .15s; letter-spacing:.05em; text-transform:uppercase; }}
  #search-btn:hover {{ opacity:.85; }}
  #home-btn {{ display:none; background:none; border:2px solid rgba(255,255,255,0.3); border-radius:2px; padding:10px 14px; color:rgba(255,255,255,0.7); font-size:13px; cursor:pointer; white-space:nowrap; min-height:44px; transition:all .15s; }}
  #home-btn:hover {{ color:#fff; border-color:#fff; }}
  /* Section nav — top measured by JS at runtime */
  #section-nav {{ position:sticky; top:var(--search-h); z-index:99; background:var(--bg); border-bottom:2px solid var(--border-dark); padding:0 24px; margin:0 -24px 24px; overflow-x:auto; scrollbar-width:none; }}
  #section-nav::-webkit-scrollbar {{ display:none; }}
  .snav-inner {{ max-width:1000px; margin:0 auto; display:flex; gap:0; padding:0; }}
  .snav-link {{ padding:10px 16px; font-size:11px; font-weight:700; color:var(--text-dim); text-decoration:none; white-space:nowrap; transition:color .15s, border-bottom .15s; cursor:pointer; border-bottom:3px solid transparent; letter-spacing:.08em; text-transform:uppercase; display:inline-block; }}
  .snav-link:hover {{ color:var(--text); }}
  .snav-link.active {{ color:var(--rust); border-bottom-color:var(--rust); }}
  /* Section anchors need scroll-margin to clear sticky bars */
  #sec-overview, #sec-films, #sec-series, #sec-music-wrap, #sec-books, #sec-podcasts, #sec-comics, #sec-youtube, #sec-tiktok, #sec-patterns, #sec-recs {{
    scroll-margin-top: calc(var(--search-h) + 52px);
  }}
  .result-card {{ display:flex; gap:12px; background:var(--bg-card); border:1px solid var(--border); border-radius:3px; padding:14px; margin-bottom:10px; transition:border-color .15s, box-shadow .15s; }}
  .result-card:hover {{ border-color:var(--cobalt); box-shadow:0 2px 8px rgba(26,22,18,0.1); }}
  .result-cover {{ width:60px; height:88px; object-fit:cover; border-radius:6px; background:var(--bg-panel); flex-shrink:0; }}
  .result-cover-ph {{ width:60px; height:88px; border-radius:6px; background:var(--bg-panel); flex-shrink:0; display:flex; align-items:center; justify-content:center; font-size:22px; }}
  .result-body {{ flex:1; min-width:0; }}
  .result-title {{ font-size:14px; font-weight:600; color:var(--text); margin-bottom:2px; }}
  .result-sub {{ font-size:12px; color:var(--text-dim); margin-bottom:4px; }}
  .result-genres {{ font-size:12px; color:var(--accent-book); margin-bottom:6px; }}
  .result-desc {{ font-size:12px; color:var(--text-dim); line-height:1.4; margin-bottom:8px; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; }}
  .result-actions {{ display:flex; align-items:center; gap:6px; flex-wrap:wrap; }}
  .skeleton {{ background:linear-gradient(90deg,var(--bg-card) 25%,var(--bg-panel) 50%,var(--bg-card) 75%); background-size:200% 100%; animation:shimmer 1.2s infinite; border-radius:4px; }}
  @keyframes shimmer {{ 0%{{background-position:200% 0}} 100%{{background-position:-200% 0}} }}
  .wl-item {{ display:flex; align-items:center; gap:12px; padding:12px 0; border-bottom:1px solid var(--border); cursor:pointer; }}
  .wl-item:hover .wl-title {{ color:var(--accent-book); }}
  .wl-cover {{ width:40px; height:58px; object-fit:cover; border-radius:4px; background:var(--bg-panel); flex-shrink:0; }}
  .wl-cover-ph {{ width:40px; height:58px; border-radius:4px; background:var(--bg-panel); flex-shrink:0; display:flex; align-items:center; justify-content:center; font-size:16px; }}
  .wl-title {{ font-size:13px; font-weight:600; color:var(--text); transition:color .15s; }}
  .wl-badge {{ background:var(--bg); border:1px solid var(--border); border-radius:12px; padding:2px 8px; font-size:11px; color:var(--text-dim); }}
  .filter-pill {{ background:var(--bg-card); border:1px solid var(--border-dark); border-radius:2px; padding:8px 14px; font-size:11px; font-weight:600; letter-spacing:.05em; text-transform:uppercase; color:var(--text-dim); cursor:pointer; white-space:nowrap; min-height:36px; transition:color .15s, border-color .15s, background .15s; }}
  .filter-pill:hover {{ border-color:var(--cobalt); color:var(--cobalt); }}
  .filter-pill.active {{ background:var(--cobalt); border-color:var(--cobalt); color:#fff; }}
  .related-item {{ display:flex; align-items:center; gap:10px; padding:10px 0; border-bottom:1px solid var(--border); }}
  .star-r {{ display:inline-flex; gap:1px; }}
  .star-r span {{ font-size:18px; cursor:pointer; color:var(--border-light); transition:color .15s; padding:6px 4px; }}
  .star-r span.lit {{ color:var(--accent-film); }}
  #detail-overlay {{ position:fixed; inset:0; z-index:200; display:none; }}
  #detail-backdrop {{ position:absolute; inset:0; background:rgba(26,22,18,.5); backdrop-filter:blur(4px); }}
  #detail-panel {{ position:absolute; top:0; right:0; bottom:0; width:min(560px,100vw); background:var(--bg-panel); border-left:3px solid var(--text); overflow-y:auto; display:flex; flex-direction:column; transform:translateX(100%); transition:transform .25s ease; }}
  #detail-overlay.open #detail-panel {{ transform:translateX(0); }}
  #detail-overlay.open {{ display:block; }}
  .detail-backdrop-img {{ width:100%; height:200px; object-fit:cover; background:var(--bg-card); flex-shrink:0; }}
  .detail-body {{ padding:20px; flex:1; }}
  .detail-title {{ font-size:20px; font-weight:700; color:var(--text); margin-bottom:4px; }}
  .detail-meta {{ font-size:13px; color:var(--text-dim); margin-bottom:12px; }}
  .detail-genres {{ display:flex; gap:6px; flex-wrap:wrap; margin-bottom:14px; }}
  .detail-genre-tag {{ background:var(--bg-card); border:1px solid var(--border); border-radius:12px; padding:3px 10px; font-size:12px; color:var(--text-dim); }}
  .detail-section {{ margin-bottom:16px; }}
  .detail-section-label {{ font-size:11px; font-weight:600; color:var(--accent-book); text-transform:uppercase; letter-spacing:.06em; margin-bottom:6px; }}
  .detail-cast {{ display:flex; gap:10px; overflow-x:auto; padding-bottom:4px; }}
  .cast-card {{ text-align:center; flex-shrink:0; width:64px; }}
  .cast-avatar {{ width:56px; height:56px; border-radius:50%; object-fit:cover; background:var(--bg-card); margin:0 auto 4px; display:block; }}
  .cast-name {{ font-size:10px; color:var(--text-dim); line-height:1.2; }}
  .streaming-pills {{ display:flex; gap:6px; flex-wrap:wrap; }}
  .streaming-pill {{ background:var(--bg-card); border:1px solid var(--border); border-radius:6px; padding:5px 10px; font-size:12px; color:var(--text); }}
  .streaming-pill.flatrate {{ border-color:#3fb95055; color:var(--accent-music); }}
  .detail-link {{ display:inline-flex; align-items:center; gap:6px; padding:8px 14px; border:1px solid var(--border); border-radius:8px; font-size:13px; color:var(--accent-book); text-decoration:none; transition:border-color .15s, background .15s; margin-right:8px; margin-bottom:8px; }}
  .detail-link:hover {{ border-color:var(--accent-book); background:#1f6feb11; }}
  .detail-close {{ position:sticky; top:0; z-index:1; background:var(--cobalt); border-bottom:3px solid var(--gold); padding:14px 20px; display:flex; justify-content:space-between; align-items:center; }}
  .detail-close button {{ background:none; border:none; color:rgba(255,255,255,0.7); font-size:22px; cursor:pointer; padding:4px; line-height:1; transition:color .15s; }}
  .detail-close button:hover {{ color:#fff; }}
  #detail-panel-title {{ color:rgba(255,255,255,0.9) !important; }}
  /* Section images */
  .sec-img {{
    width:100%; height:220px; object-fit:cover; border-radius:4px;
    margin-bottom:20px; display:block;
    border:1px solid var(--border-dark);
  }}
  /* Collapsible panels */
  .collapsible {{ position:relative; }}
  .collapsible-body {{ overflow:hidden; transition:max-height .4s ease; }}
  .collapsible.collapsed .collapsible-body {{ max-height:var(--max-h, 420px); }}
  .collapsible.collapsed .collapsible-fade {{
    display:block;
    position:absolute; bottom:40px; left:0; right:0; height:80px;
    background:linear-gradient(to bottom, transparent, var(--bg-panel));
    pointer-events:none;
  }}
  .collapsible-fade {{ display:none; }}
  .collapsible-btn {{
    display:block; width:100%; margin-top:12px; padding:9px 0;
    background:none; border:1px solid var(--border-dark); border-radius:2px;
    font-family:inherit; font-size:11px; font-weight:700; letter-spacing:.08em;
    text-transform:uppercase; color:var(--text-dim); cursor:pointer;
    transition:color .15s, border-color .15s;
  }}
  .collapsible-btn:hover {{ color:var(--cobalt); border-color:var(--cobalt); }}
  /* Section divider headings — NASA travel poster editorial */
  .sec-heading {{
    padding:56px 0 4px; position:relative;
    border-top:3px solid var(--border-dark);
    margin-top:8px;
  }}
  .sec-eyebrow {{
    display:inline-flex; align-items:center; gap:10px;
    font-size:10px; font-weight:700; text-transform:uppercase; letter-spacing:.22em;
    margin-bottom:10px;
  }}
  .sec-eyebrow::before {{
    content:''; display:inline-block; width:32px; height:2px; background:currentColor;
  }}
  .sec-title {{
    font-family:'Lora',Georgia,serif;
    font-size:clamp(40px,7vw,80px);
    font-weight:700;
    letter-spacing:-.03em;
    line-height:1;
    margin-bottom:4px;
    color:var(--text);
  }}
  .sec-title.film   {{ color:var(--rust); }}
  .sec-title.book   {{ color:var(--cobalt); }}
  .sec-title.music  {{ color:var(--teal); }}
  .sec-title.pattern {{
    font-size:clamp(48px,9vw,108px);
    color:var(--accent-patterns);
  }}
  .sec-title.recs   {{ color:var(--gold); }}
  /* Result + rec card hover */
  .rec-card:hover {{ border-color:var(--gold); background:var(--bg); }}
  /* Table */
  td, th {{ padding:10px; text-align:left; border-bottom:1px solid var(--border); font-size:13px; color:var(--text); }}
  th {{ color:var(--text-dim); font-weight:600; font-size:11px; text-transform:uppercase; letter-spacing:.06em; }}
  li {{ margin-bottom:6px; font-size:13px; color:var(--text-dim); line-height:1.55; }}
  /* Cluster */
  .cluster-name {{ font-size:15px; font-weight:700; color:var(--rust); margin-bottom:6px; }}
  .cluster-desc {{ font-size:13px; color:var(--text-dim); margin-bottom:8px; line-height:1.55; }}
  .cluster-items {{ font-size:12px; color:var(--cobalt); }}
  /* Rec confidence */
  .rec-conf {{ font-size:13px; color:var(--teal); font-weight:700; flex-shrink:0; }}
  .rec-reason {{ font-size:13px; color:var(--text-dim); margin-bottom:6px; line-height:1.55; }}
  .rec-friction {{ font-size:12px; color:var(--rust); line-height:1.4; margin-bottom:10px; }}
  /* Star ratings */
  .star {{ font-size:18px; cursor:pointer; color:var(--border-dark); transition:color .15s; line-height:1; padding:6px 4px; }}
  .star.lit {{ color:var(--gold); }}
  .star:hover {{ color:var(--gold); }}
  .star-r span {{ font-size:18px; cursor:pointer; color:var(--border-dark); transition:color .15s; padding:6px 4px; }}
  .star-r span.lit {{ color:var(--gold); }}
  /* Series row */
  .series-name {{ font-size:14px; color:var(--text); font-weight:500; }}
  .series-count {{ font-size:13px; color:var(--text-dim); }}
  /* Stat override — use cobalt for all */
  .stat-n {{ color:var(--cobalt) !important; }}
  /* Taste Map nav link — distinct from anchor links */
  .snav-link.external {{ color:var(--rust); }}
  .snav-link.external:hover {{ color:var(--rust); opacity:.75; }}
  .snav-link.external.active {{ border-bottom-color:var(--rust); }}
  /* Mobile */
  @media(max-width:700px) {{
    body {{ overflow-x:hidden; }}
    .sec-title {{ font-size:clamp(32px,10vw,56px); }}
    .sec-title.pattern {{ font-size:clamp(40px,12vw,72px); }}
    .snav-link {{ min-height:44px; display:inline-flex; align-items:center; padding:8px 12px; }}
    .search-row {{ flex-wrap:wrap; }}
    #search-type {{ display:none; }}
    #search-btn {{ flex:1 0 100%; }}
  }}
</style>
</head>
<body>

<!-- Detail overlay (slide-in panel) -->
<div id="detail-overlay">
  <div id="detail-backdrop" onclick="closeDetail()"></div>
  <div id="detail-panel">
    <div class="detail-close">
      <span id="detail-panel-title" style="font-size:14px;font-weight:600;color:#8b949e;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:400px"></span>
      <button onclick="closeDetail()" aria-label="Close detail">✕</button>
    </div>
    <div id="detail-content"></div>
  </div>
</div>

<div class="wrap">

<!-- Search bar -->
<div id="search-bar">
  <div class="search-row">
    <button id="home-btn" onclick="goHome()" aria-label="Back to dashboard">← Dashboard</button>
    <input id="search-input" type="text" placeholder="Search books, films, series…"
           onkeydown="if(event.key==='Enter')doSearch()" aria-label="Search">
    <select id="search-type" aria-label="Media type">
      <option value="all">All</option>
      <option value="book">📖 Books</option>
      <option value="film">🎬 Films</option>
      <option value="tv">📺 TV</option>
      <option value="music">🎵 Music</option>
      <option value="podcast">🎙️ Podcasts</option>
    </select>
    <button id="search-btn" onclick="doSearch()">Search</button>
  </div>
</div>

<!-- Section nav -->
<div id="section-nav">
  <div class="snav-inner">
    <a class="snav-link" href="#sec-overview">Overview</a>
    <a class="snav-link" href="#sec-films">Films</a>
    <a class="snav-link" href="#sec-series">Series</a>
    <a class="snav-link" href="#sec-music-wrap">Music</a>
    <a class="snav-link" href="#sec-books">Books</a>
    <a class="snav-link" href="#sec-podcasts">Podcasts</a>
    <a class="snav-link" href="#sec-comics">Comics</a>
    <a class="snav-link" href="#sec-youtube">YouTube</a>
    <a class="snav-link" href="#sec-tiktok">TikTok</a>
    <a class="snav-link" href="#sec-patterns">Patterns</a>
    <a class="snav-link" href="#sec-recs">Picks</a>
    <a class="snav-link external" href="/culture/map">Taste Map</a>
  </div>
</div>

<!-- Search results panel -->
<div id="search-panel" style="display:none;margin-bottom:20px">
  <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;flex-wrap:wrap;gap:8px">
    <div id="search-status" class="dim" style="font-size:12px"></div>
    <div id="filter-pills" style="display:none;gap:6px;display:flex">
      <button class="filter-pill active" onclick="filterResults('all',this)">All</button>
      <button class="filter-pill" onclick="filterResults('film',this)">🎬 Films</button>
      <button class="filter-pill" onclick="filterResults('tv_show',this)">📺 Series</button>
      <button class="filter-pill" onclick="filterResults('book',this)">📖 Books</button>
      <button class="filter-pill" onclick="filterResults('music',this)">🎵 Music</button>
      <button class="filter-pill" onclick="filterResults('podcast',this)">🎙️ Podcasts</button>
    </div>
  </div>
  <div id="search-results-list"></div>
</div>

<!-- Related panel -->
<div id="related-panel" style="display:none" class="panel">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
    <h2 style="margin-bottom:0">Related to <span id="related-title"></span></h2>
    <button onclick="document.getElementById('related-panel').style.display='none'" style="background:none;border:none;color:#8b949e;font-size:18px;cursor:pointer;min-width:44px;min-height:44px" aria-label="Close">✕</button>
  </div>
  <div id="related-list"></div>
</div>

<!-- Watchlist panel -->
<div id="watchlist-panel" class="panel" style="display:none">
  <h2>My Watchlist</h2>
  <div id="watchlist-list"></div>
</div>

<div style="margin-bottom:24px">
  <img src="/culture/img/hero-overview.jpg" style="width:100%;height:260px;object-fit:cover;border-radius:4px;margin-bottom:20px;border:1px solid var(--border-dark)" alt="">
  <h1>My ears, my eyes and me</h1>
  <div class="dim">Profile generated {generated} · {total_consumed} items consumed · {len(book_ratings)} ratings</div>
</div>

<!-- Stats bar -->
<div class="panel" id="sec-overview">
  <div class="stat-bar">
    <div class="stat"><div class="stat-n">{stats["books"] or 0}</div><div class="stat-l">Books read</div></div>
    <div class="stat"><div class="stat-n">{stats["audiobooks"] or 0}</div><div class="stat-l">Audiobooks</div></div>
    <div class="stat"><div class="stat-n">{len(to_read)}</div><div class="stat-l">To-read</div></div>
    <div class="stat"><div class="stat-n">{mean_str}</div><div class="stat-l">Mean rating</div></div>
    <div class="stat"><div class="stat-n">{stats["films"] or 0}</div><div class="stat-l">Films seen</div></div>
    <div class="stat"><div class="stat-n">{stats["shows"] or 0}</div><div class="stat-l">Shows seen</div></div>
    <div class="stat"><div class="stat-n">{stats["films_rated"] or 0}</div><div class="stat-l">Rated (film+TV)</div></div>
    <div class="stat"><div class="stat-n" style="color:#c792ea">{comic_total}</div><div class="stat-l">Comics owned</div></div>
    <div class="stat"><div class="stat-n" style="color:#cc0000">{yt_foreground:,}</div><div class="stat-l">YouTube videos</div></div>
    <div class="stat"><div class="stat-n" style="color:#fe2c55">{tiktok_stats["watched"]:,}</div><div class="stat-l">TikTok watched</div></div>
  </div>
  <div class="dim" style="margin-top:12px;font-size:12px">Rating calibration: {cal.get("five_star_threshold","")}</div>
</div>

<!-- Analytics view wrapper (hidden in Picks mode) -->
<div id="analytics-view">

<!-- Films section -->
<!-- ═══ FILMS ══════════════════════════════════════════════════════════════ -->
<div id="sec-films">
  <div class="sec-heading">
    <img src="/culture/img/section-films.jpg" class="sec-img" alt="">
    <div class="sec-eyebrow" style="color:var(--accent-film)">Films &amp; TV</div>
    <div class="sec-title film">What I sit through.</div>
  </div>

  <div class="grid-2" style="margin-top:4px">
    <div class="panel">
      <h2>Films vs. Series</h2>
      <div style="display:flex;gap:32px;margin-bottom:20px;align-items:flex-end">
        <div>
          <div style="font-size:48px;font-weight:800;color:var(--accent-film);font-family:'Lora',serif;line-height:1">{film_pct}%</div>
          <div style="font-size:12px;color:var(--text-dim);margin-top:4px;text-transform:uppercase;letter-spacing:.06em">Films<br><span style="font-size:16px;font-weight:700;color:var(--text)">{n_films}</span></div>
        </div>
        <div>
          <div style="font-size:48px;font-weight:800;color:var(--accent-book);font-family:'Lora',serif;line-height:1">{series_pct}%</div>
          <div style="font-size:12px;color:var(--text-dim);margin-top:4px;text-transform:uppercase;letter-spacing:.06em">Series<br><span style="font-size:16px;font-weight:700;color:var(--text)">{n_series}</span></div>
        </div>
      </div>
      <div style="height:12px;background:rgba(26,22,18,0.1);border-radius:2px;overflow:hidden;display:flex">
        <div style="width:{film_pct}%;background:var(--accent-film)"></div>
        <div style="width:{series_pct}%;background:var(--accent-book);opacity:0.7"></div>
      </div>
    </div>
    <div class="panel">
      <h2>My Rating Distribution</h2>
      {user_rating_html}
      <div class="dim" style="margin-top:10px;font-size:12px">{len(film_ratings)} rated · avg {round(sum(film_ratings)/len(film_ratings),1) if film_ratings else "—"}★</div>
    </div>
  </div>

  <div class="grid-2">
    <div class="panel">
      <h2>Watched per Year</h2>
      {watched_by_year_html}
      {watched_legend}
    </div>
    <div class="panel">
      <h2>Film &amp; TV Genres</h2>
      {film_genre_chart}
    </div>
  </div>

  <div class="grid-2">
    <div class="panel">
      <h2>Era — Decade of Release</h2>
      {decade_chart_html}
      <div class="dim" style="margin-top:8px;font-size:12px">Where in film history your watchlist lives</div>
    </div>
    <div class="panel">
      <h2>Top Directors</h2>
      <div class="grid-2" style="gap:12px">
        <div>
          <h3 style="font-size:11px;color:var(--text-dim);text-transform:uppercase;letter-spacing:.08em;margin-bottom:8px">Highest rated</h3>
          <table><tr><th>Director</th><th>n</th><th>Avg</th></tr>{directors_by_rating_html}</table>
        </div>
        <div>
          <h3 style="font-size:11px;color:var(--text-dim);text-transform:uppercase;letter-spacing:.08em;margin-bottom:8px">Most watched</h3>
          <table><tr><th>Director</th><th>n</th><th>Avg</th></tr>{directors_by_count_html}</table>
        </div>
      </div>
    </div>
  </div>
</div>

<!-- ═══ SERIES (recent activity) ═════════════════════════════════════════ -->
<div id="sec-series">
  <div class="sec-heading">
    <img src="/culture/img/section-series.jpg" class="sec-img" alt="">
    <div class="sec-eyebrow" style="color:var(--accent-film)">Recent</div>
    <div class="sec-title film" style="font-size:clamp(28px,5vw,56px)">What I watched lately.</div>
  </div>

  <div class="panel" style="margin-top:4px">
    <div style="display:flex;align-items:center;gap:24px;margin-bottom:20px">
      <div class="stat"><div class="stat-n">{total_shows}</div><div class="stat-l">Shows watched</div></div>
      <div class="stat"><div class="stat-n">{total_films}</div><div class="stat-l">Films watched</div></div>
    </div>
    <div class="collapsible" data-max="420">
      <div class="collapsible-body">
        <div class="grid-2">
          <div>
            <h3>Recent Shows</h3>
            <table><tr><th>Title</th><th>Last watched</th></tr>{recent_shows_html}</table>
          </div>
          <div>
            <h3>Recent Films</h3>
            <table><tr><th>Title</th><th>Watched</th></tr>{recent_films_html}</table>
          </div>
        </div>
        {f'<div style="margin-top:16px"><h3>Recently rated</h3><table><tr><th>Title</th><th></th></tr>{recent_rated_html}</table></div>' if recent_rated_html else ''}
      </div>
      <div class="collapsible-fade"></div>
      <button class="collapsible-btn" onclick="toggleCollapsible(this)">See more ↓</button>
    </div>
  </div>
</div>

<!-- ═══ MUSIC ══════════════════════════════════════════════════════════════ -->
<div id="sec-music-wrap">
  <div class="sec-heading">
    <img src="/culture/img/section-music.jpg" class="sec-img" alt="">
    <div class="sec-eyebrow" style="color:var(--accent-music)">Music</div>
    <div class="sec-title music">What I hear.</div>
  </div>
</div>

<div class="panel" id="sec-music">
  <div class="stat-bar" style="margin-bottom:20px">
    <div class="stat"><div class="stat-n" style="color:var(--accent-music)">{spotify_total_plays}</div><div class="stat-l">Plays (≥30s)</div></div>
    <div class="stat"><div class="stat-n" style="color:var(--accent-music)">{spotify_total_hours}h</div><div class="stat-l">Listening time</div></div>
    <div class="stat"><div class="stat-n" style="color:var(--accent-music)">{spotify_total_artists}</div><div class="stat-l">Unique artists</div></div>
  </div>
  <div class="grid-2">
    <div>
      <h3>Top Artists by Plays</h3>
      {spotify_artists_html}
    </div>
    <div>
      <h3>Year by Year</h3>
      <table><tr><th>Year</th><th>Plays</th><th>Hours</th></tr>{spotify_year_rows}</table>
    </div>
  </div>
</div>

<div class="grid-2">
  <div class="panel">
    <h2>Top Tracks</h2>
    {top_tracks_html if top_tracks_html else "<p class='dim'>No track data.</p>"}
  </div>
  <div class="panel">
    <h2>Top Albums</h2>
    {top_albums_html if top_albums_html else "<p class='dim'>No album data.</p>"}
  </div>
</div>

<div class="panel">
  <h2>Artist Sprint — Top 5 by Year</h2>
  <div class="dim" style="margin-bottom:12px;font-size:12px">How your listening shifted year by year</div>
  {sprint_html if sprint_html else "<p class='dim'>No data.</p>"}
</div>

<!-- ═══ BOOKS ══════════════════════════════════════════════════════════════ -->
<div id="sec-books">
  <div class="sec-heading">
    <img src="/culture/img/section-books.jpg" class="sec-img" alt="">
    <div class="sec-eyebrow" style="color:var(--accent-book)">Books</div>
    <div class="sec-title book">What I read.</div>
  </div>

  <div class="grid-2" style="margin-top:4px">
    <div class="panel">
      <h2>Genre Fingerprint</h2>
      {genre_chart}
    </div>
    <div class="panel">
      <h2>Series vs. Standalone</h2>
      <div style="display:flex;gap:32px;margin-bottom:20px;align-items:flex-end">
        <div>
          <div style="font-size:48px;font-weight:800;color:var(--accent-book);font-family:'Lora',serif;line-height:1">{series_books_pct}%</div>
          <div style="font-size:12px;color:var(--text-dim);margin-top:4px;text-transform:uppercase;letter-spacing:.06em">Series<br><span style="font-size:16px;font-weight:700;color:var(--text)">{n_series_books}</span></div>
        </div>
        <div>
          <div style="font-size:48px;font-weight:800;color:var(--teal);font-family:'Lora',serif;line-height:1">{standalone_books_pct}%</div>
          <div style="font-size:12px;color:var(--text-dim);margin-top:4px;text-transform:uppercase;letter-spacing:.06em">Standalone<br><span style="font-size:16px;font-weight:700;color:var(--text)">{n_standalone_books}</span></div>
        </div>
      </div>
      <div style="height:12px;background:rgba(26,22,18,0.1);border-radius:2px;overflow:hidden;display:flex">
        <div style="width:{series_books_pct}%;background:var(--accent-book)"></div>
        <div style="width:{standalone_books_pct}%;background:var(--teal);opacity:0.7"></div>
      </div>
      <div class="dim" style="margin-top:12px;font-size:12px">You almost always commit to a series.</div>
    </div>
  </div>

  <div class="grid-2">
    <div class="panel">
      <h2>Book Length</h2>
      {page_bucket_chart}
      <div class="dim" style="margin-top:10px;font-size:12px">Avg {avg_pages}p · longest {max_pages}p</div>
    </div>
    <div class="panel">
      <h2>Era — Decade Published</h2>
      {book_decade_chart}
      <div class="dim" style="margin-top:8px;font-size:12px">When your books were written</div>
    </div>
  </div>

  <div class="grid-2">
    <div class="panel">
      <h2>Top Authors</h2>
      <table><tr><th>Author</th><th>Books</th><th>Avg</th></tr>{authors_html}</table>
    </div>
    <div class="panel">
      <h2>Series Read</h2>
      {series_html}
    </div>
  </div>

  <div class="panel">
    <h2>To-Read Queue ({len(to_read)})</h2>
    <div class="collapsible" data-max="380">
      <div class="collapsible-body">
        <table><tr><th>Title</th><th>Author</th></tr>{to_read_html}</table>
      </div>
      <div class="collapsible-fade"></div>
      <button class="collapsible-btn" onclick="toggleCollapsible(this)">See more ↓</button>
    </div>
  </div>
</div>

<!-- ═══ PODCASTS ══════════════════════════════════════════════════════════ -->
<div id="sec-podcasts">
  <div class="sec-heading">
    <div class="sec-eyebrow" style="color:var(--rust)">Podcasts</div>
    <div class="sec-title" style="color:var(--rust)">What I listen to.</div>
  </div>
  <div class="panel" style="margin-top:4px">
    <div class="dim" style="margin-bottom:16px;font-size:12px">Listening profile — {len(podcasts)} podcasts · used for recommendations</div>
    <div class="collapsible" data-max="420">
      <div class="collapsible-body">
        {podcasts_html if podcasts_html else "<p class='dim'>No podcasts yet.</p>"}
      </div>
      <div class="collapsible-fade"></div>
      <button class="collapsible-btn" onclick="toggleCollapsible(this)">See more ↓</button>
    </div>
  </div>
</div>

<!-- ═══ COMICS ════════════════════════════════════════════════════════════ -->
<div id="sec-comics">
  <div class="sec-heading">
    <img src="/culture/img/section-comics.jpg" class="sec-img" alt="">
    <div class="sec-eyebrow" style="color:var(--accent-patterns)">Comics</div>
    <div class="sec-title" style="color:var(--accent-patterns)">What I grew up reading.</div>
  </div>

  <div class="panel" style="margin-top:4px">
    <div style="display:flex;align-items:flex-start;gap:12px;margin-bottom:20px">
      <div style="flex:1">
        <p style="font-size:13px;color:var(--text-dim);line-height:1.6">
          Mostly read as a teenager / young adult — nostalgia, not current taste. Apply <strong style="color:var(--text)">lower relevancy weight</strong> when generating new recommendations.
        </p>
      </div>
      <div class="stat" style="flex-shrink:0">
        <div class="stat-n" style="color:var(--accent-patterns)">{comic_total}</div>
        <div class="stat-l">Albums owned</div>
      </div>
    </div>
    <h3 style="margin-bottom:12px">Series</h3>
    {comic_series_html}
    {f'''<h3 style="margin-top:20px;margin-bottom:12px">Standalone albums</h3>
    <table><tr><th>Title</th><th>Author</th><th>Year</th></tr>{comic_standalone_html}</table>''' if comic_standalone_html else ''}
  </div>
</div>

<!-- ═══ YOUTUBE ═══════════════════════════════════════════════════════════ -->
<div id="sec-youtube">
  <div class="sec-heading">
    <div class="sec-eyebrow" style="color:#cc0000">YouTube</div>
    <div class="sec-title" style="color:#cc0000">What I watch.</div>
  </div>

  <div class="panel" style="margin-top:4px">
    <div class="stat-bar">
      <div class="stat"><div class="stat-n" style="color:#cc0000">{yt_total:,}</div><div class="stat-l">Watch events</div></div>
      <div class="stat"><div class="stat-n" style="color:#cc0000">{yt_foreground:,}</div><div class="stat-l">Intentional (foreground)</div></div>
      <div class="stat"><div class="stat-n">{round(yt_fg_hrs):,}h</div><div class="stat-l">Foreground hours</div></div>
    </div>
    <div class="dim" style="margin-top:10px;font-size:12px">
      ambient: {yt_ambient} · childcare: {yt_childcare} · social/karaoke: {yt_social} — excluded from analysis
    </div>
  </div>

  <div class="grid-2">
    <div class="panel">
      <h2>Top Channels — Foreground (capped 90min/video)</h2>
      {yt_channels_html}
    </div>
    <div class="panel">
      <h2>Monthly Foreground Activity</h2>
      {yt_monthly_html}
    </div>
  </div>

  <div class="panel">
    <h2>Curiosity Trails — Duration-Weighted Interest</h2>
    <div class="dim" style="font-size:11px;margin-bottom:10px">Bar = time invested (capped 90min/video) × topic recurrence. ↩ = return rate (days/months).</div>
    {yt_trails_html}
  </div>

  <div class="panel">
    <h2>Tree Ring — Every Video, Width = Time Invested</h2>
    <div class="dim" style="font-size:11px;margin-bottom:10px">Each bar is one year. Each segment is one video — width proportional to duration (capped 90min). Bars scaled relative to busiest year.</div>
    {yt_ring_html}
  </div>

  <div class="grid-2">
    <div class="panel">
      <h2>Year-by-Year Foreground Viewing</h2>
      {yt_yearly_html}
    </div>
    <div class="panel">
      <h2>Life Chapters</h2>
      {yt_chapters_html}
    </div>
  </div>

  <div class="grid-2">
    <div class="panel">
      <h2>YouTube × Spotify — Do They Compete?</h2>
      {yt_spotify_html}
    </div>
    <div class="panel">
      <h2>Monthly Foreground Activity</h2>
      {yt_monthly_html}
    </div>
  </div>
</div>

<!-- ═══ TIKTOK ════════════════════════════════════════════════════════════ -->
<div id="sec-tiktok">
  <div class="sec-heading">
    <div class="sec-eyebrow" style="color:#fe2c55">TikTok</div>
    <div class="sec-title" style="color:#fe2c55">What I scroll.</div>
  </div>

  <div class="panel" style="margin-top:4px">
    <div class="stat-bar">
      <div class="stat"><div class="stat-n" style="color:#fe2c55">{tiktok_stats["watched"]:,}</div><div class="stat-l">Videos watched</div></div>
      <div class="stat"><div class="stat-n" style="color:#fe2c55">{tiktok_stats["liked"]:,}</div><div class="stat-l">Liked (★★★★)</div></div>
      <div class="stat"><div class="stat-n" style="color:#fe2c55">{tiktok_stats["favorited"]:,}</div><div class="stat-l">Favorited (★★★★★)</div></div>
    </div>
    <div class="dim" style="margin-top:10px;font-size:12px">watch=2★ · liked=4★ · favorited=5★ · searches and shares not tracked</div>
  </div>

  <div class="grid-2">
    <div class="panel">
      <h2>Monthly Watch Activity</h2>
      {tiktok_monthly_html}
    </div>
    <div class="panel">
      <h2>Peak Watch Hours</h2>
      {tiktok_hours_html}
      <div class="dim" style="margin-top:8px;font-size:12px">Hour based on TikTok export timestamps</div>
    </div>
  </div>

  {tiktok_enrich_html}
  {tiktok_crossplatform_html}
  {consumption_modes_html}
</div>

<!-- ═══ PATTERNS ══════════════════════════════════════════════════════════ -->
<div id="sec-patterns">
  <div class="sec-heading">
    <img src="/culture/img/section-patterns.jpg" class="sec-img" alt="">
    <div class="sec-eyebrow" style="color:var(--accent-patterns)">Patterns</div>
    <div class="sec-title pattern">I am one.</div>
  </div>

  {f'<p style="max-width:700px;line-height:1.6;color:var(--text-dim);margin:12px 0 20px;font-size:14px">{profile_summary}</p>' if profile_summary else ''}

  <div class="grid-2" style="margin-top:16px">
    <div class="panel">
      <h2>Core Themes</h2>
      <ul style="padding-left:16px">{themes_html}</ul>
    </div>
    <div class="panel">
      <h2>What I Don't Like</h2>
      <ul style="padding-left:16px">{dislikes_html}</ul>
    </div>
  </div>

  <div class="panel">
    <h2>Taste Clusters</h2>
    {clusters_html}
  </div>
</div>

</div><!-- /#analytics-view -->

<!-- ═══ RECOMMENDATIONS ═══════════════════════════════════════════════════ -->
<div id="sec-recs">
  <div class="sec-heading">
    <div class="sec-eyebrow" style="color:var(--accent-recs)">Recommendations</div>
    <div class="sec-title recs">What's next.</div>
  </div>
  <div class="panel" style="margin-top:16px" id="recs-panel">
    <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;margin-bottom:16px">
      <span id="recs-count" class="dim" style="font-size:13px">{len(recs)} across all media</span>
      <button onclick="refreshRecs()" class="action-btn" style="font-size:12px;padding:5px 12px;min-height:32px">↺ Refresh</button>
    </div>
    {all_recs_html}
  </div>
</div>

</div><!-- /.wrap -->

<script>
function switchTab(name) {{
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
  document.getElementById('tab-'+name).classList.add('active');
  event.target.classList.add('active');
}}

function dismiss(id) {{
  const el = document.getElementById('rec-'+id);
  if (el) el.style.display='none';
  const existing = JSON.parse(localStorage.getItem('dismissed_recs') || '[]');
  if (!existing.includes(id)) existing.push(id);
  localStorage.setItem('dismissed_recs', JSON.stringify(existing));
}}

function toggleWatchlist(id, btn) {{
  const key = 'watchlist_recs';
  const existing = JSON.parse(localStorage.getItem(key) || '[]');
  if (existing.includes(id)) {{
    localStorage.setItem(key, JSON.stringify(existing.filter(x => x !== id)));
    btn.classList.remove('saved');
    btn.textContent = btn.textContent.replace('✓ ','');
  }} else {{
    existing.push(id);
    localStorage.setItem(key, JSON.stringify(existing));
    btn.classList.add('saved');
    btn.textContent = '✓ ' + btn.textContent;
  }}
}}

function hoverStars(id, n) {{
  for (let i=1; i<=5; i++) {{
    const s = document.getElementById('s-'+id+'-'+i);
    if (s) s.style.color = i<=n ? '#f0883e' : '#30363d';
  }}
}}

function resetStars(id) {{
  const saved = (JSON.parse(localStorage.getItem('rated_recs') || '{{}}'  ))[id];
  for (let i=1; i<=5; i++) {{
    const s = document.getElementById('s-'+id+'-'+i);
    if (s) s.style.color = saved && i<=saved ? '#f0883e' : '#30363d';
  }}
}}

async function rateRec(id, stars) {{
  // 1. Immediate localStorage save + animation
  const ratings = JSON.parse(localStorage.getItem('rated_recs') || '{{}}');
  ratings[id] = stars;
  localStorage.setItem('rated_recs', JSON.stringify(ratings));
  const existing = JSON.parse(localStorage.getItem('dismissed_recs') || '[]');
  if (!existing.includes(id)) {{ existing.push(id); localStorage.setItem('dismissed_recs', JSON.stringify(existing)); }}
  const card = document.getElementById('rec-'+id);
  if (card) {{
    card.style.overflow = 'hidden';
    card.style.maxHeight = card.offsetHeight + 'px';
    card.style.marginBottom = card.style.marginBottom || getComputedStyle(card).marginBottom;
    void card.offsetHeight;
    card.style.transition = 'opacity .25s ease, max-height .35s ease .15s, margin-bottom .35s ease .15s, padding .35s ease .15s';
    card.style.opacity = '0';
    card.style.maxHeight = '0';
    card.style.marginBottom = '0';
    card.style.paddingTop = '0';
    card.style.paddingBottom = '0';
    setTimeout(() => card.remove(), 600);
  }}
  // 2. Persist to server — resolve title → TMDB/OL ID → /api/interactions
  if (!card) return;
  const title = card.dataset.title;
  const type = card.dataset.type;
  if (!title || !type || type === 'music' || type === 'podcast') return; // no search API for these yet
  try {{
    const sr = await fetch(`${{API}}/api/search?q=${{encodeURIComponent(title)}}&type=${{type}}`);
    if (!sr.ok) return;
    const results = await sr.json();
    if (!results.length) return;
    const item = results[0];
    // Ensure item is in DB
    await fetch(API+'/api/items', {{
      method:'POST', headers:{{'Content-Type':'application/json'}},
      body: JSON.stringify(item)
    }});
    // Record rating
    await fetch(API+'/api/interactions', {{
      method:'POST', headers:{{'Content-Type':'application/json'}},
      body: JSON.stringify({{item_id: item.id, interaction_type:'rating', value:String(stars)}})
    }});
  }} catch(e) {{
    console.warn('rateRec: server persist failed', e);
  }}
}}

document.addEventListener('DOMContentLoaded', () => {{
  const dismissed = JSON.parse(localStorage.getItem('dismissed_recs') || '[]');
  dismissed.forEach(id => {{
    const el = document.getElementById('rec-'+id);
    if (el) el.style.display='none';
  }});
  const watchlisted = JSON.parse(localStorage.getItem('watchlist_recs') || '[]');
  watchlisted.forEach(id => {{
    const btn = document.getElementById('wl-'+id);
    if (btn) {{ btn.classList.add('saved'); btn.textContent = '✓ '+btn.textContent; }}
  }});
  const rated = JSON.parse(localStorage.getItem('rated_recs') || '{{}}');
  Object.entries(rated).forEach(([id, stars]) => {{
    const badge = document.getElementById('rated-'+id);
    if (badge) {{ badge.textContent = '★'.repeat(stars); badge.style.display='inline'; }}
    const starRow = document.getElementById('stars-'+id);
    if (starRow) starRow.style.display='none';
  }});
  // Measure search bar + view tabs heights for sticky stacking
  const searchBar = document.getElementById('search-bar');
  if (searchBar) {{
    document.documentElement.style.setProperty('--search-h', searchBar.offsetHeight + 'px');
  }}
  loadWatchlist();
  initSectionNav();
  updateRecsCount();
  initCollapsibles();
}});

function initCollapsibles() {{
  document.querySelectorAll('.collapsible').forEach(el => {{
    const maxH = parseInt(el.dataset.max || '420');
    el.style.setProperty('--max-h', maxH + 'px');
    const body = el.querySelector('.collapsible-body');
    if (body && body.scrollHeight > maxH + 40) {{
      el.classList.add('collapsed');
    }} else {{
      // Content fits — hide button
      const btn = el.querySelector('.collapsible-btn');
      if (btn) btn.style.display = 'none';
    }}
  }});
}}

function toggleCollapsible(btn) {{
  const el = btn.closest('.collapsible');
  if (!el) return;
  const body = el.querySelector('.collapsible-body');
  if (el.classList.contains('collapsed')) {{
    el.classList.remove('collapsed');
    body.style.maxHeight = body.scrollHeight + 'px';
    btn.textContent = 'See less ↑';
  }} else {{
    body.style.maxHeight = '';
    el.classList.add('collapsed');
    btn.textContent = 'See more ↓';
    el.scrollIntoView({{ behavior: 'smooth', block: 'nearest' }});
  }}
}}

function initSectionNav() {{
  const sectionIds = ['sec-overview','sec-films','sec-series','sec-music-wrap','sec-books','sec-podcasts','sec-comics','sec-youtube','sec-tiktok','sec-patterns','sec-recs'];
  const links = {{}};
  sectionIds.forEach(id => {{
    const link = document.querySelector(`.snav-link[href="#${{id}}"]`);
    if (link) links[id] = link;
  }});
  if (!Object.keys(links).length) return;
  Object.values(links)[0].classList.add('active');
  const observer = new IntersectionObserver(entries => {{
    entries.forEach(entry => {{
      const link = links[entry.target.id];
      if (!link) return;
      if (entry.isIntersecting) {{
        Object.values(links).forEach(l => l.classList.remove('active'));
        link.classList.add('active');
        link.scrollIntoView({{ behavior:'smooth', block:'nearest', inline:'nearest' }});
      }}
    }});
  }}, {{ rootMargin:'-10% 0px -80% 0px', threshold:0 }});
  sectionIds.forEach(id => {{
    const el = document.getElementById(id);
    if (el) observer.observe(el);
  }});
}}

function updateRecsCount() {{
  const total = document.querySelectorAll('.rec-card').length;
  const hidden = document.querySelectorAll('.rec-card[style*="display: none"], .rec-card[style*="display:none"]').length;
  const el = document.getElementById('recs-count');
  if (el) el.textContent = `${{total - hidden}} across all media`;
}}

function refreshRecs() {{
  document.querySelectorAll('.rec-card').forEach(card => {{ card.style.cssText = ''; }});
  const dismissed = JSON.parse(localStorage.getItem('dismissed_recs') || '[]');
  dismissed.forEach(id => {{
    const el = document.getElementById('rec-'+id);
    if (el) el.style.display = 'none';
  }});
  const rated = JSON.parse(localStorage.getItem('rated_recs') || '{{}}');
  Object.entries(rated).forEach(([id, stars]) => {{
    const badge = document.getElementById('rated-'+id);
    if (badge) {{ badge.textContent = '★'.repeat(Number(stars)); badge.style.display = 'inline'; }}
    const starRow = document.getElementById('stars-'+id);
    if (starRow) starRow.style.display = 'none';
  }});
  updateRecsCount();
}}

// When opened as file:// use absolute server URL; when served, use relative
const API = window.location.protocol === 'file:' ? 'http://localhost:8000' : '';

let _lastResults = [];

// ── Search ─────────────────────────────────────────────────────────────────
async function doSearch() {{
  const q = document.getElementById('search-input').value.trim();
  if (!q) return;
  const type = document.getElementById('search-type').value;
  document.getElementById('search-status').textContent = 'Searching…';
  document.getElementById('search-panel').style.display = 'block';
  document.getElementById('search-results-list').innerHTML = '';
  document.getElementById('home-btn').style.display = 'inline-flex';
  document.getElementById('filter-pills').style.display = 'none';
  try {{
    const r = await fetch(`${{API}}/api/search?q=${{encodeURIComponent(q)}}&type=${{type}}`);
    _lastResults = await r.json();
    // Reset filter pills to All
    document.querySelectorAll('.filter-pill').forEach(p => p.classList.remove('active'));
    document.querySelector('.filter-pill').classList.add('active');
    // Only show pills if multiple types present
    const types = new Set(_lastResults.map(i => i.media_type));
    if (types.size > 1) document.getElementById('filter-pills').style.display = 'flex';
    renderFiltered('all', _lastResults, q);
  }} catch(e) {{
    document.getElementById('search-status').textContent = 'Search failed — is the server running?';
  }}
}}

function renderFiltered(type, items, q) {{
  const filtered = type === 'all' ? items : items.filter(i => i.media_type === type);
  const label = q || document.getElementById('search-input').value.trim();
  document.getElementById('search-status').textContent =
    filtered.length ? `${{filtered.length}} result${{filtered.length>1?'s':''}} for "${{label}}"` : `No results for "${{label}}"`;
  document.getElementById('search-results-list').innerHTML = filtered.map(renderResultCard).join('');
  wireResultCards();
}}

function filterResults(type, btn) {{
  document.querySelectorAll('.filter-pill').forEach(p => p.classList.remove('active'));
  btn.classList.add('active');
  renderFiltered(type, _lastResults);
}}

function closeSearch() {{
  document.getElementById('search-panel').style.display = 'none';
  document.getElementById('related-panel').style.display = 'none';
  document.getElementById('home-btn').style.display = 'none';
  document.getElementById('search-input').value = '';
  document.getElementById('search-status').textContent = '';
  document.getElementById('search-results-list').innerHTML = '';
  document.getElementById('filter-pills').style.display = 'none';
  _lastResults = [];
}}

function goHome() {{
  closeSearch();
  window.scrollTo({{top:0, behavior:'smooth'}});
}}

function typeEmoji(t) {{
  if (t === 'book') return '📖';
  if (t === 'tv_show') return '📺';
  if (t === 'music') return '🎵';
  if (t === 'podcast') return '🎙️';
  return '🎬';
}}

function renderResultCard(item) {{
  const wlLabel = item.watchlist ? '✓ Watchlist' : '+ Watchlist';
  const wlCls = item.watchlist ? 'saved' : '';
  const sid = item.id.replace(/:/g,'_');
  const cover = item.cover_url
    ? `<img class="result-cover" src="${{item.cover_url}}" onerror="this.style.display='none'">`
    : `<div class="result-cover-ph">${{typeEmoji(item.media_type)}}</div>`;
  const savedRating = item.rating || 0;
  const starsHtml = [1,2,3,4,5].map(i =>
    `<span id="sr-${{sid}}-${{i}}" class="${{i<=savedRating?'lit':''}}"
      onmouseenter="hvrItem('${{sid}}',${{i}})"
      onmouseleave="rstItem('${{sid}}',${{savedRating}})">★</span>`
  ).join('');
  return `<div class="result-card" id="rc-${{sid}}" data-id="${{item.id}}">
    ${{cover}}
    <div class="result-body" onclick="showDetail('${{item.id}}')" style="cursor:pointer">
      <div class="result-title">${{item.title}}</div>
      <div class="result-sub">${{item.subtitle}}</div>
      <div class="result-genres">${{(item.genres||[]).slice(0,3).join(' · ')}}</div>
      <div class="result-desc">${{item.description}}</div>
    </div>
    <div class="result-actions" style="margin-top:8px">
      <button class="action-btn watchlist ${{wlCls}}" id="wlbtn-${{sid}}">${{wlLabel}}</button>
      <div class="star-r" id="stars-r-${{sid}}">${{starsHtml}}</div>
    </div>
  </div>`;
}}

function wireResultCards() {{
  _lastResults.forEach(item => {{
    const sid = item.id.replace(/:/g,'_');
    const wlBtn = document.getElementById('wlbtn-'+sid);
    if (wlBtn) wlBtn.onclick = () => toggleItemWatchlist(item, wlBtn);
    const starContainer = document.getElementById('stars-r-'+sid);
    if (starContainer) starContainer.querySelectorAll('span').forEach((s,idx) => {{
      s.onclick = () => rateItem(item.id, idx+1);
    }});
  }});
}}

// ── Search item watchlist ─────────────────────────────────────────────────
async function toggleItemWatchlist(item, btn) {{
  if (btn.classList.contains('saved')) {{
    await fetch(API+'/api/watchlist/'+encodeURIComponent(item.id), {{method:'DELETE'}});
    btn.classList.remove('saved');
    btn.textContent = '+ Watchlist';
    loadWatchlist();
    return;
  }}
  btn.textContent = '…';
  btn.disabled = true;
  try {{
    const r1 = await fetch(API+'/api/items', {{
      method:'POST', headers:{{'Content-Type':'application/json'}},
      body: JSON.stringify(item)
    }});
    const {{item_id}} = await r1.json();
    const shelf = item.media_type === 'book' ? 'to-read' : 'to-watch';
    await fetch(API+'/api/interactions', {{
      method:'POST', headers:{{'Content-Type':'application/json'}},
      body: JSON.stringify({{item_id, interaction_type:'shelf', value:shelf}})
    }});
    btn.classList.add('saved');
    btn.textContent = '✓ On watchlist';
    loadWatchlist();
  }} catch(e) {{
    btn.textContent = 'Error';
  }} finally {{
    btn.disabled = false;
  }}
}}

// ── Star rating on search results ─────────────────────────────────────────
function hvrItem(sid, n) {{
  for(let i=1;i<=5;i++) {{
    const s=document.getElementById(`sr-${{sid}}-${{i}}`);
    if(s) s.style.color=i<=n?'#f0883e':'#30363d';
  }}
}}
function rstItem(sid, savedRating) {{
  for(let i=1;i<=5;i++) {{
    const s=document.getElementById(`sr-${{sid}}-${{i}}`);
    if(s) {{ s.className=''; if(i<=(savedRating||0)) s.classList.add('lit'); }}
  }}
}}
async function rateItem(itemId, stars, el) {{
  const sid = itemId.replace(/:/g,'_');
  // Update _lastResults so re-render shows correct state
  const idx = _lastResults.findIndex(r=>r.id===itemId);
  if(idx>=0) _lastResults[idx].rating = stars;
  for(let i=1;i<=5;i++) {{
    const s=document.getElementById(`sr-${{sid}}-${{i}}`);
    if(s) s.className=i<=stars?'lit':'';
  }}
  // Update hover listeners with new saved rating
  const container=document.getElementById(`stars-r-${{sid}}`);
  if(container) container.querySelectorAll('span').forEach((s,idx)=>{{
    s.onmouseleave=()=>rstItem(sid,stars);
  }});
  await fetch(API+'/api/interactions', {{
    method:'POST', headers:{{'Content-Type':'application/json'}},
    body: JSON.stringify({{item_id:itemId, interaction_type:'rating', value:String(stars)}})
  }});
}}

// ── Watchlist panel ───────────────────────────────────────────────────────
async function loadWatchlist() {{
  try {{
    const r = await fetch(API+'/api/watchlist');
    const items = await r.json();
    const panel = document.getElementById('watchlist-panel');
    const list = document.getElementById('watchlist-list');
    if (!items.length) {{ panel.style.display='none'; return; }}
    panel.style.display='block';
    list.innerHTML = items.map(it => {{
      const cover = it.cover_url
        ? `<img class="wl-cover" src="${{it.cover_url}}" onerror="this.style.display='none'">`
        : `<div class="wl-cover-ph">${{typeEmoji(it.media_type)}}</div>`;
      const sub = [it.author||it.director, it.year].filter(Boolean).join(' · ');
      return `<div class="wl-item">
        ${{cover}}
        <div style="flex:1;min-width:0">
          <div style="font-size:13px;font-weight:600;color:#e6edf3">${{it.title}}</div>
          <div class="dim">${{sub}}</div>
          <span class="wl-badge">${{it.shelf==='to-read'?'To read':'To watch'}}</span>
        </div>
        <button class="action-btn dismiss" onclick='removeWatchlistItem("${{it.id}}",this)'>Remove</button>
      </div>`;
    }}).join('');
  }} catch(e) {{ /* server not running — silently skip */ }}
}}

async function removeWatchlistItem(itemId, btn) {{
  btn.textContent = '…';
  await fetch(API+'/api/watchlist/'+encodeURIComponent(itemId), {{method:'DELETE'}});
  loadWatchlist();
}}

// ── Related ───────────────────────────────────────────────────────────────
async function showRelated(itemId, title) {{
  document.getElementById('related-title').textContent = title;
  document.getElementById('related-list').innerHTML = '<p class="dim">Loading…</p>';
  document.getElementById('related-panel').style.display = 'block';
  document.getElementById('related-panel').scrollIntoView({{behavior:'smooth', block:'nearest'}});
  try {{
    const r = await fetch(API+'/api/related/'+encodeURIComponent(itemId));
    const items = await r.json();
    if (!items.length) {{
      document.getElementById('related-list').innerHTML = '<p class="dim">No similar titles found.</p>';
      return;
    }}
    document.getElementById('related-list').innerHTML = items.map(it => {{
      const cover = it.cover_url
        ? `<img style="width:36px;height:52px;object-fit:cover;border-radius:3px;background:#21262d" src="${{it.cover_url}}">`
        : `<div style="width:36px;height:52px;border-radius:3px;background:#21262d;display:flex;align-items:center;justify-content:center;font-size:14px">${{typeEmoji(it.media_type)}}</div>`;
      return `<div class="related-item">
        ${{cover}}
        <div>
          <div style="font-size:13px;font-weight:600;color:#e6edf3">${{it.title}}</div>
          <div class="dim">${{it.year||''}}</div>
        </div>
      </div>`;
    }}).join('');
  }} catch(e) {{
    document.getElementById('related-list').innerHTML = '<p class="dim">Failed to load related titles.</p>';
  }}
}}

// ── Detail panel ─────────────────────────────────────────────────────────────
// ── Detail pane — Supabase-backed ────────────────────────────────────────────

function openDetailOverlay(title) {{
  const overlay = document.getElementById('detail-overlay');
  const body = document.getElementById('detail-content');
  document.getElementById('detail-panel-title').textContent = title || '';
  body.innerHTML = `<div style="padding:20px">
    <div class="skeleton" style="height:200px;border-radius:0;margin:-20px -20px 20px"></div>
    <div class="skeleton" style="height:28px;width:65%;margin-bottom:10px"></div>
    <div class="skeleton" style="height:14px;width:40%;margin-bottom:20px"></div>
    <div class="skeleton" style="height:90px;margin-bottom:12px"></div>
    <div class="skeleton" style="height:60px"></div>
  </div>`;
  overlay.classList.add('open');
  document.body.style.overflow = 'hidden';
  return body;
}}

// Build item_key from itemId string (handles "imdb:tt...", "netflix:...", etc.)
function itemKeyFromId(itemId, mediaType) {{
  // Already a full key like "film:imdb:tt123"
  if (itemId.startsWith('film:') || itemId.startsWith('tv_show:') || itemId.startsWith('book:')) return itemId;
  const mt = mediaType || 'film';
  return `${{mt}}:${{itemId}}`;
}}

async function showDetail(itemId, mediaType) {{
  const body = openDetailOverlay('');
  try {{
    const key = itemKeyFromId(itemId, mediaType);
    const r = await fetch(`/api/culture/detail?key=${{encodeURIComponent(key)}}`);
    if (r.status === 404) {{
      // Not enriched yet — show linkouts
      showDetailFallback(body, itemId, null);
      return;
    }}
    const d = await r.json();
    document.getElementById('detail-panel-title').textContent = d.title || '';
    body.innerHTML = renderStoryDetail(d, itemId);
    wireDetailInteractions(d, itemId);
  }} catch(e) {{
    showDetailFallback(body, itemId, null);
  }}
}}

async function showDirectorDetail(name) {{
  const body = openDetailOverlay(name);
  try {{
    const key = `director:${{name}}`;
    const r = await fetch(`/api/culture/detail?key=${{encodeURIComponent(key)}}`);
    if (r.status === 404) {{
      const q = encodeURIComponent(name);
      body.innerHTML = `<div style="padding:24px">
        <div style="font-size:18px;font-weight:700;color:var(--text);margin-bottom:16px">${{name}}</div>
        <div style="display:flex;flex-direction:column;gap:8px">
          <a class="detail-link" href="https://www.imdb.com/find?q=${{q}}&s=nm" target="_blank">🎬 IMDB ↗</a>
          <a class="detail-link" href="https://letterboxd.com/director/${{name.toLowerCase().replace(/ /g,'-')}}/" target="_blank">🎞 Letterboxd ↗</a>
        </div>
        <p class="dim" style="margin-top:16px;font-size:12px">Enrichment not yet run for this director.</p>
      </div>`;
      return;
    }}
    const d = await r.json();
    document.getElementById('detail-panel-title').textContent = name;
    body.innerHTML = renderDirectorDetail(d);
  }} catch(e) {{
    body.innerHTML = `<div style="padding:24px;color:var(--text-dim)">Failed to load details for ${{name}}.</div>`;
  }}
}}

async function showArtistDetail(name) {{
  const body = openDetailOverlay(name);
  try {{
    const key = `artist:${{name}}`;
    const r = await fetch(`/api/culture/detail?key=${{encodeURIComponent(key)}}`);
    if (r.status === 404) {{
      body.innerHTML = `<div style="padding:24px">
        <div style="font-size:18px;font-weight:700;color:var(--text);margin-bottom:16px">${{name}}</div>
        <a class="detail-link" href="https://www.last.fm/music/${{encodeURIComponent(name)}}" target="_blank">🎵 Last.fm ↗</a>
        <p class="dim" style="margin-top:16px;font-size:12px">Enrichment not yet run for this artist.</p>
      </div>`;
      return;
    }}
    const d = await r.json();
    document.getElementById('detail-panel-title').textContent = name;
    body.innerHTML = renderArtistDetail(d);
  }} catch(e) {{
    body.innerHTML = `<div style="padding:24px;color:var(--text-dim)">Failed to load details for ${{name}}.</div>`;
  }}
}}

// ── Renderers ─────────────────────────────────────────────────────────────────

function starBar(current, itemId, title, mediaType) {{
  return [1,2,3,4,5].map(i => {{
    const lit = i <= (current||0);
    return `<span class="star${{lit?' lit':''}}" style="font-size:24px;padding:4px 6px;cursor:pointer"
      onclick="rateDetailItem('${{itemId}}','${{(title||'').replace(/'/g,\"\\\\'\")}}',${{i}},'${{mediaType}}')"
      onmouseenter="hoverDetailStars(this,${{i}})"
      onmouseleave="resetDetailStars(this.parentNode,${{current||0}})">★</span>`;
  }}).join('');
}}

function streamingBadges(streaming) {{
  if (!streaming) return '';
  const flat = (streaming.flatrate||[]).map(s=>`<span class="streaming-pill flatrate">${{s}}</span>`).join('');
  const rent = (streaming.rent||[]).slice(0,3).map(s=>`<span class="streaming-pill">${{s}}</span>`).join('');
  const buy  = (streaming.buy||[]).slice(0,2).map(s=>`<span class="streaming-pill" style="opacity:.7">${{s}}</span>`).join('');
  return flat || rent || buy
    ? `<div class="detail-section">
        <div class="detail-section-label">Where to watch (DE)</div>
        <div class="streaming-pills">${{flat}}${{rent}}${{buy}}</div>
       </div>` : '';
}}

function linkRow(links) {{
  if (!links) return '';
  return Object.entries(links)
    .filter(([,url]) => url)
    .map(([label,url]) => `<a class="detail-link" href="${{url}}" target="_blank" rel="noopener">${{label}} ↗</a>`)
    .join('');
}}

function renderStoryDetail(d, itemId) {{
  const isBook = d.media_type === 'book';
  const backdrop = d.backdrop_url
    ? `<img class="detail-backdrop-img" src="${{d.backdrop_url}}" alt="">`
    : d.poster_url
    ? `<img class="detail-backdrop-img" src="${{d.poster_url}}" alt="" style="object-position:top">`
    : '';
  const coverImg = isBook && d.cover_url
    ? `<img src="${{d.cover_url}}" style="width:100px;border-radius:4px;margin-bottom:16px;box-shadow:0 2px 8px rgba(26,22,18,.15)" alt="">` : '';

  const metaParts = isBook
    ? [d.author, d.year, d.page_count ? d.page_count+'p' : '', d.series_name ? (d.series_name+' #'+(d.series_pos||'?')) : ''].filter(Boolean)
    : [d.directors?.join(', '), d.year, d.runtime_min ? d.runtime_min+'min' : ''].filter(Boolean);

  const genreTags = (d.genres||d.subjects||[]).slice(0,5).map(g=>`<span class="detail-genre-tag">${{g}}</span>`).join('');
  const castHtml = (d.cast||[]).slice(0,5).map(c => {{
    const img = c.profile ? `<img class="cast-avatar" src="${{c.profile}}" alt="${{c.name}}">` : `<div class="cast-avatar" style="display:flex;align-items:center;justify-content:center;font-size:18px">👤</div>`;
    return `<div class="cast-card">${{img}}<div class="cast-name">${{c.name}}<br><span style="opacity:.6">${{c.character||''}}</span></div></div>`;
  }}).join('');
  const tmdbScore = d.vote_average ? `<span style="font-weight:700;color:var(--rust)">${{d.vote_average}}</span><span style="color:var(--text-dim);font-size:12px"> /10 TMDB</span>` : '';
  const yourRating = d.your_rating;
  const yourDate = d.date_watched || d.date_read;

  // Author bio (books)
  const authorBio = isBook && d.author_bio
    ? `<div class="detail-section">
        ${{d.author_photo ? `<img src="${{d.author_photo}}" style="width:56px;height:56px;border-radius:50%;object-fit:cover;float:left;margin:0 12px 8px 0">` : ''}}
        <div class="detail-section-label">About ${{d.author||'the author'}}</div>
        <p style="font-size:13px;color:var(--text-dim);line-height:1.6">${{d.author_bio}}</p>
        <div style="clear:both"></div>
       </div>` : '';

  return `
    ${{backdrop}}
    <div class="detail-body">
      ${{coverImg}}
      <div class="detail-title">${{d.title}}</div>
      <div class="detail-meta">${{metaParts.join(' · ')}} ${{tmdbScore}}</div>
      ${{d.tagline ? `<p style="font-style:italic;color:var(--text-dim);font-size:13px;margin:8px 0 12px">"${{d.tagline}}"</p>` : ''}}
      <div class="detail-genres">${{genreTags}}</div>

      ${{yourRating || yourDate ? `<div class="detail-section" style="background:var(--bg-card);border-radius:4px;padding:12px;border:1px solid var(--border)">
        <div class="detail-section-label">Your history</div>
        ${{yourRating ? `<div style="font-size:20px;color:var(--gold)">${{'★'.repeat(Math.round(yourRating))}}<span style="font-size:13px;color:var(--text-dim);margin-left:6px">${{yourRating}} stars</span></div>` : ''}}
        ${{yourDate ? `<div style="font-size:12px;color:var(--text-dim);margin-top:4px">${{isBook?'Read':'Watched'}}: ${{yourDate?.slice(0,10)||''}}</div>` : ''}}
      </div>` : ''}}

      <div class="detail-section">
        <div class="detail-section-label">${{isBook ? 'Description' : 'Synopsis'}}</div>
        <p style="font-size:13px;color:var(--text-dim);line-height:1.6">${{d.overview || d.description || 'No description available.'}}</p>
      </div>
      ${{authorBio}}
      ${{castHtml ? `<div class="detail-section"><div class="detail-section-label">Cast</div><div class="detail-cast">${{castHtml}}</div></div>` : ''}}
      ${{streamingBadges(d.streaming)}}

      <div class="detail-section">
        <div class="detail-section-label">Rate this</div>
        <div id="detail-stars" style="display:flex;gap:2px">${{starBar(yourRating, itemId, d.title, d.media_type)}}</div>
      </div>

      <div style="margin-top:16px;flex-wrap:wrap;display:flex;gap:8px;align-items:center">
        ${{linkRow(d.links)}}
      </div>
    </div>`;
}}

function renderDirectorDetail(d) {{
  const filmRows = (d.your_films||[]).slice(0,10).map(f => {{
    const stars = f.rating ? '★'.repeat(Math.round(f.rating)) : '—';
    return `<tr>
      <td style="cursor:pointer;color:var(--cobalt)" onclick="searchAndShowDetail('${{f.title?.replace(/'/g,"\\\\'")}}','film')">${{f.title||''}}</td>
      <td style="color:var(--text-dim)">${{f.year||''}}</td>
      <td style="color:var(--gold)">${{stars}}</td>
    </tr>`;
  }}).join('');

  return `<div class="detail-body">
    ${{d.photo_url ? `<img src="${{d.photo_url}}" style="width:80px;height:80px;border-radius:50%;object-fit:cover;margin-bottom:16px;border:2px solid var(--border-dark)">` : ''}}
    <div class="detail-title">${{d.name}}</div>
    <div class="detail-meta">${{[d.birthday?.slice(0,4), d.place_of_birth].filter(Boolean).join(' · ')}}</div>
    ${{d.bio ? `<div class="detail-section"><p style="font-size:13px;color:var(--text-dim);line-height:1.6">${{d.bio}}</p></div>` : ''}}
    <div class="detail-section">
      <div class="detail-section-label">Your watch history (${{d.your_count}} films · avg ${{d.your_avg}}★)</div>
      <table><tr><th>Film</th><th>Year</th><th>Your rating</th></tr>${{filmRows}}</table>
    </div>
    <div style="margin-top:16px;display:flex;gap:8px;flex-wrap:wrap">${{linkRow(d.links)}}</div>
  </div>`;
}}

function renderArtistDetail(d) {{
  const trackRows = (d.your_top_tracks||[]).map((t,i) =>
    `<tr><td style="color:var(--text-dim)">${{i+1}}</td><td>${{t.title||t.track||''}}</td><td style="color:var(--accent-music)">${{(t.plays||0).toLocaleString()}}</td></tr>`
  ).join('');
  const albumRows = (d.your_top_albums||[]).map(a =>
    `<tr><td>${{a.title||a.album||''}}</td><td style="color:var(--accent-music)">${{(a.plays||0).toLocaleString()}}</td></tr>`
  ).join('');

  return `<div class="detail-body">
    <div class="detail-title">${{d.name}}</div>
    <div class="detail-meta">${{d.listeners ? Number(d.listeners).toLocaleString()+' Last.fm listeners' : ''}}</div>
    ${{d.tags?.length ? `<div style="display:flex;gap:6px;flex-wrap:wrap;margin:10px 0">${{d.tags.map(t=>`<span class="detail-genre-tag">${{t}}</span>`).join('')}}</div>` : ''}}
    ${{d.bio ? `<div class="detail-section"><p style="font-size:13px;color:var(--text-dim);line-height:1.6">${{d.bio}}</p></div>` : ''}}
    <div class="detail-section">
      <div class="detail-section-label">Your listening — ${{(d.your_plays||0).toLocaleString()}} plays · ${{d.your_hours||0}}h</div>
    </div>
    ${{trackRows ? `<div class="detail-section"><div class="detail-section-label">Your top tracks</div><table><tr><th></th><th>Track</th><th>Plays</th></tr>${{trackRows}}</table></div>` : ''}}
    ${{albumRows ? `<div class="detail-section"><div class="detail-section-label">Your top albums</div><table><tr><th>Album</th><th>Plays</th></tr>${{albumRows}}</table></div>` : ''}}
    ${{d.similar?.length ? `<div class="detail-section"><div class="detail-section-label">Similar artists</div><div style="font-size:13px;color:var(--cobalt)">${{d.similar.map(s=>`<span style="cursor:pointer;margin-right:10px" onclick="showArtistDetail('${{s}}')">${{s}}</span>`).join('')}}</div></div>` : ''}}
    <div style="margin-top:16px;display:flex;gap:8px;flex-wrap:wrap">${{linkRow(d.links)}}</div>
  </div>`;
}}

function showDetailFallback(body, itemId, title) {{
  const q = encodeURIComponent((title || itemId.split(':').pop() || ''));
  body.innerHTML = `<div style="padding:24px">
    <div style="font-size:16px;font-weight:700;color:var(--text);margin-bottom:8px">${{title || itemId}}</div>
    <p style="font-size:13px;color:var(--text-dim);margin-bottom:16px;line-height:1.6">Not yet enriched — search directly:</p>
    <div style="display:flex;flex-direction:column;gap:8px">
      <a class="detail-link" href="https://www.imdb.com/find?q=${{q}}" target="_blank">🎬 IMDB ↗</a>
      <a class="detail-link" href="https://letterboxd.com/search/${{q}}/" target="_blank">🎞 Letterboxd ↗</a>
      <a class="detail-link" href="https://www.goodreads.com/search?q=${{q}}" target="_blank">📖 Goodreads ↗</a>
    </div>
  </div>`;
}}

function wireDetailInteractions(d, itemId) {{
  // nothing extra needed — stars are wired inline
}}

async function rateDetailItem(itemId, title, stars, mediaType) {{
  // Optimistic UI
  const container = document.getElementById('detail-stars');
  if (container) {{
    container.querySelectorAll('.star').forEach((s,i) => {{
      s.classList.toggle('lit', i < stars);
    }});
  }}
  await fetch('/api/culture/interact', {{
    method: 'POST',
    headers: {{'Content-Type':'application/json'}},
    body: JSON.stringify({{ item_key: itemKeyFromId(itemId, mediaType), media_type: mediaType, title, interact: 'rating', value: String(stars) }}),
  }});
}}

function hoverDetailStars(el, n) {{
  const container = el.closest('[id="detail-stars"]') || el.parentNode;
  container.querySelectorAll('.star').forEach((s,i) => {{ s.style.color = i < n ? 'var(--gold)' : 'var(--border-dark)'; }});
}}
function resetDetailStars(container, saved) {{
  container.querySelectorAll('.star').forEach((s,i) => {{ s.style.color = i < saved ? 'var(--gold)' : 'var(--border-dark)'; }});
}}

function closeDetail() {{
  document.getElementById('detail-overlay').classList.remove('open');
  document.body.style.overflow='';
  setTimeout(()=>{{ document.getElementById('detail-content').innerHTML=''; }}, 260);
}}

document.addEventListener('keydown', e=>{{ if(e.key==='Escape') closeDetail(); }});

// ── Search-then-detail (rec cards click title) ────────────────────────────────
async function searchAndShowDetail(title, mediaType) {{
  const body = openDetailOverlay(title);
  // Derive a key to try
  const mt = mediaType === 'tv' ? 'tv_show' : (mediaType === 'book' ? 'book' : 'film');
  // Try local API first with a title search
  try {{
    const r = await fetch(`/api/culture/detail?key=${{encodeURIComponent(mt+':title:'+title)}}`);
    // 404 = not found by that key, try full search
    if (r.status === 404) {{
      // Fall back to TMDB search via local server if running, else show fallback
      const sr = await fetch(`${{API}}/api/search?q=${{encodeURIComponent(title)}}&type=${{mediaType}}`)
        .catch(() => null);
      if (sr && sr.ok) {{
        const results = await sr.json();
        if (results.length) {{
          _lastResults.push(...results.filter(r=>!_lastResults.find(x=>x.id===r.id)));
          await showDetail(results[0].id, mt);
          return;
        }}
      }}
      showDetailFallback(body, title, title);
      return;
    }}
    const d = await r.json();
    document.getElementById('detail-panel-title').textContent = d.title || title;
    body.innerHTML = renderStoryDetail(d, title);
  }} catch(e) {{
    showDetailFallback(body, title, title);
  }}
}}
</script>
</body>
</html>"""


def main():
    conn = get_conn()
    init_db(conn)
    html = render(conn)
    OUT.write_text(html, encoding="utf-8")
    print(f"Dashboard written to {OUT}")
    print(f"  Size: {len(html):,} bytes")


if __name__ == "__main__":
    main()
