#!/Users/waldo.vanderhaeghen/Library/Scripts/watcher-env/bin/python3
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


def svg_bar_chart(data: dict[str, float], color: str = "#58a6ff",
                  max_width: int = 340, bar_h: int = 22, gap: int = 6) -> str:
    if not data:
        return "<p class='dim'>No data yet.</p>"
    items = sorted(data.items(), key=lambda x: x[1], reverse=True)[:12]
    max_val = max(v for _, v in items) or 1
    rows = []
    for label, val in items:
        w = int(val / max_val * max_width)
        pct = f"{val:.0%}" if val <= 1 else f"{val:.1f}"
        rows.append(
            f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:{gap}px">'
            f'<div style="width:160px;font-size:12px;text-align:right;color:#8b949e;white-space:nowrap;'
            f'overflow:hidden;text-overflow:ellipsis">{label}</div>'
            f'<div style="width:{w}px;height:{bar_h}px;background:{color};border-radius:3px"></div>'
            f'<div style="font-size:12px;color:#e6edf3">{pct}</div>'
            f'</div>'
        )
    return "\n".join(rows)


def svg_rating_histogram(ratings: list[float], color: str = "#3fb950") -> str:
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
            f'<div style="font-size:11px;color:#8b949e">{count}</div>'
            f'<div style="width:32px;height:{h}px;background:{color};border-radius:3px 3px 0 0"></div>'
            f'<div style="font-size:12px;color:#e6edf3">{"★"*star}</div>'
            f'</div>'
        )
    return f'<div style="display:flex;align-items:flex-end;gap:8px;height:120px;padding-top:16px">{"".join(bars)}</div>'


def render(conn) -> str:
    # ── Data pulls ────────────────────────────────────────────────────────────
    dismissed = load_dismissed()

    stats = conn.execute("""
        SELECT
          sum(case when m.media_type='book' then 1 end) books,
          sum(case when m.media_type='audiobook' then 1 end) audiobooks,
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

    recs_raw = [dict(r) for r in conn.execute(
        "SELECT * FROM recommendations WHERE status='pending' ORDER BY confidence DESC"
    ).fetchall() if r["id"] not in dismissed]
    # Enrich with year from media_items where available
    for r in recs_raw:
        row = conn.execute(
            "SELECT year FROM media_items WHERE lower(title)=lower(?) LIMIT 1", (r["title"],)
        ).fetchone()
        r["year"] = row["year"] if row and row["year"] else None
    recs = recs_raw

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

    to_read = conn.execute("""
        SELECT m.title, m.author, m.series_name, m.series_pos, ui.date_added
        FROM media_items m JOIN user_interactions ui ON ui.media_id=m.id
        WHERE ui.shelf='to-read'
        ORDER BY m.series_name NULLS LAST, m.series_pos NULLS LAST, m.title
    """).fetchall()

    generated = profile_row["generated_at"][:10] if profile_row else "—"

    film_ratings = [r["rating"] for r in conn.execute(
        "SELECT rating FROM user_interactions WHERE rating IS NOT NULL "
        "AND source IN ('imdb','justwatch_liked')"
    ).fetchall()]

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

    # ── Netflix ───────────────────────────────────────────────────────────────
    netflix_shows = conn.execute("""
        SELECT m.title, ui.date_completed
        FROM media_items m JOIN user_interactions ui ON ui.media_id=m.id
        WHERE m.source='netflix' AND m.media_type='tv_show' AND ui.interaction='completed'
        ORDER BY ui.date_completed DESC LIMIT 15
    """).fetchall()
    netflix_films = conn.execute("""
        SELECT m.title, ui.date_completed
        FROM media_items m JOIN user_interactions ui ON ui.media_id=m.id
        WHERE m.source='netflix' AND m.media_type='film' AND ui.interaction='completed'
        ORDER BY ui.date_completed DESC LIMIT 15
    """).fetchall()
    netflix_counts = conn.execute("""
        SELECT
          sum(case when m.media_type='tv_show' then 1 end) shows,
          sum(case when m.media_type='film' then 1 end) films
        FROM media_items m JOIN user_interactions ui ON ui.media_id=m.id
        WHERE m.source='netflix' AND ui.interaction='completed'
    """).fetchone()
    netflix_rated = conn.execute("""
        SELECT m.title, ui.rating
        FROM media_items m JOIN user_interactions ui ON ui.media_id=m.id
        WHERE m.source='netflix' AND ui.interaction='rated'
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

    top_directors = profile.get("top_directors", [])
    directors_html = ""
    for d in top_directors[:8]:
        avg = f'{d["avg_rating"]:.1f}' if d.get("avg_rating") else "—"
        directors_html += f'<tr><td>{d["name"]}</td><td>{d.get("count","")}</td><td>{avg}★</td></tr>'

    # ── Genre chart ───────────────────────────────────────────────────────────
    genre_chart = svg_bar_chart(profile.get("genre_fingerprint", {}))
    film_genre_chart = svg_bar_chart(profile.get("film_genre_fingerprint", {}), color="#f0883e")
    rating_hist = svg_rating_histogram(book_ratings)
    film_rating_hist = svg_rating_histogram(film_ratings, color="#f0883e")

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
        {r["artist"]: r["plays"] for r in spotify_top_artists}, color="#1db954"
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

    # ── Netflix HTML ──────────────────────────────────────────────────────────
    def nf_row(title: str, date: str) -> str:
        d = date[:7] if date else ""  # YYYY-MM
        return f'<tr><td>{title}</td><td class="dim">{d}</td></tr>'

    netflix_shows_html = "".join(nf_row(r["title"], r["date_completed"]) for r in netflix_shows) \
        or "<tr><td class='dim' colspan='2'>No data</td></tr>"
    netflix_films_html = "".join(nf_row(r["title"], r["date_completed"]) for r in netflix_films) \
        or "<tr><td class='dim' colspan='2'>No data</td></tr>"
    netflix_rated_html = ""
    for r in netflix_rated:
        stars = "👍" if (r["rating"] or 0) >= 3.5 else "👎"
        netflix_rated_html += f'<tr><td>{r["title"]}</td><td>{stars}</td></tr>'
    netflix_total_shows = netflix_counts["shows"] or 0
    netflix_total_films = netflix_counts["films"] or 0

    # ── Themes + Dislikes ─────────────────────────────────────────────────────
    cal = profile.get("rating_calibration", {})
    themes_html = "".join(f'<li>{t}</li>' for t in profile.get("top_themes", []))
    dislikes_html = "".join(f'<li>{d}</li>' for d in profile.get("dislikes_pattern", []))

    # ── Recommendations ───────────────────────────────────────────────────────
    def rec_card(r: dict) -> str:
        rid = r["id"]
        conf_pct = int(r.get("confidence", 0) * 100)
        badge = "📺" if r["media_type"] == "tv_show" else ("🎬" if r["media_type"] == "film" else "📖")
        wl_label = "Want to watch" if r["media_type"] in ("film", "tv_show") else "Want to read"
        api_type = "tv" if r["media_type"] == "tv_show" else ("film" if r["media_type"] == "film" else "book")
        safe_title = r["title"].replace("'", "\\'").replace('"', '&quot;')
        stars = "".join(
            f'<span class="star" id="s-{rid}-{i}" onclick="rateRec({rid},{i})" '
            f'onmouseenter="hoverStars({rid},{i})" onmouseleave="resetStars({rid})">★</span>'
            for i in range(1, 6)
        )
        return (
            f'<div class="card rec-card" id="rec-{rid}" style="cursor:pointer" onclick="searchAndShowDetail(\'{safe_title}\',\'{api_type}\')">'
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
            f'<button class="action-btn detail-btn">Details ↗</button>'
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

    # ── Render ────────────────────────────────────────────────────────────────
    total_consumed = (stats["books"] or 0) + (stats["audiobooks"] or 0) + (stats["films"] or 0) + (stats["shows"] or 0)
    mean_str = f'{cal.get("mean","—")}'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Entertainment Dashboard</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2290%22>🎷</text></svg>">
<style>
  *, *::before, *::after {{ box-sizing:border-box; }}
  body {{ background:#0d1117; color:#e6edf3; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif; margin:0; padding:0; }}
  .wrap {{ max-width:1000px; margin:0 auto; padding:0 24px 40px; }}
  .panel {{ background:#161b22; border:1px solid #30363d; border-radius:10px; padding:20px; margin-bottom:20px; }}
  .card {{ background:#1c2128; border:1px solid #30363d; border-radius:8px; padding:16px; margin-bottom:12px; }}
  h1 {{ font-size:24px; font-weight:700; color:#e6edf3; margin-bottom:4px; }}
  h2 {{ font-size:16px; font-weight:600; color:#58a6ff; margin-bottom:16px; text-transform:uppercase; letter-spacing:.05em; }}
  h3 {{ font-size:14px; font-weight:600; color:#e6edf3; margin-bottom:8px; }}
  .dim {{ color:#8b949e; font-size:13px; }}
  .stat-bar {{ display:flex; gap:24px; margin-bottom:4px; flex-wrap:wrap; }}
  .stat {{ text-align:center; }}
  .stat-n {{ font-size:28px; font-weight:700; color:#58a6ff; }}
  .stat-l {{ font-size:12px; color:#8b949e; }}
  .tabs {{ display:flex; gap:8px; margin-bottom:16px; flex-wrap:wrap; }}
  .tab {{ padding:8px 16px; border-radius:6px; cursor:pointer; font-size:14px; border:1px solid #30363d; background:#1c2128; color:#8b949e; min-height:44px; display:flex; align-items:center; }}
  .tab.active {{ background:#1f6feb; color:#fff; border-color:#1f6feb; }}
  .tab-content {{ display:none; }}
  .tab-content.active {{ display:block; }}
  .series-row {{ display:flex; justify-content:space-between; padding:10px 0; border-bottom:1px solid #21262d; }}
  .series-name {{ font-size:14px; color:#e6edf3; }}
  .series-count {{ font-size:13px; color:#8b949e; }}
  .cluster-card {{ margin-bottom:12px; }}
  .cluster-name {{ font-size:15px; font-weight:600; color:#f0883e; margin-bottom:6px; }}
  .cluster-desc {{ font-size:13px; color:#8b949e; margin-bottom:8px; line-height:1.5; }}
  .cluster-items {{ font-size:12px; color:#58a6ff; }}
  .rec-card {{ position:relative; }}
  .rec-header {{ display:flex; align-items:flex-start; gap:10px; margin-bottom:8px; }}
  .rec-badge {{ font-size:20px; flex-shrink:0; }}
  .rec-title-block {{ flex:1; }}
  .rec-title-block strong {{ font-size:15px; color:#e6edf3; }}
  .rec-conf {{ font-size:13px; color:#3fb950; font-weight:600; flex-shrink:0; }}
  .rec-reason {{ font-size:13px; color:#8b949e; margin-bottom:6px; line-height:1.5; }}
  .rec-friction {{ font-size:12px; color:#d29922; line-height:1.4; margin-bottom:10px; }}
  .rec-actions {{ display:flex; align-items:center; gap:8px; flex-wrap:wrap; }}
  .star-row {{ display:flex; gap:2px; }}
  .star {{ font-size:18px; cursor:pointer; color:#30363d; transition:color .15s; line-height:1; padding:4px 2px; }}
  .star.lit {{ color:#f0883e; }}
  .star:hover {{ color:#f0883e; }}
  .action-btn {{ font-size:13px; background:none; border:1px solid #30363d; border-radius:6px; padding:8px 14px; cursor:pointer; white-space:nowrap; min-height:36px; display:inline-flex; align-items:center; transition:all .15s; color:#8b949e; }}
  .action-btn.watchlist {{ color:#58a6ff; border-color:#1f6feb55; }}
  .action-btn.watchlist:hover {{ border-color:#58a6ff; background:#1f6feb22; }}
  .action-btn.watchlist.saved {{ color:#3fb950; border-color:#3fb950; background:#3fb95022; }}
  .action-btn.dismiss:hover {{ color:#f85149; border-color:#f85149; }}
  .action-btn.detail-btn {{ color:#8b949e; }}
  .action-btn.detail-btn:hover {{ color:#e6edf3; border-color:#58a6ff; }}
  .rated-badge {{ font-size:12px; color:#f0883e; font-weight:600; }}
  table {{ width:100%; border-collapse:collapse; }}
  td, th {{ padding:10px; text-align:left; border-bottom:1px solid #21262d; font-size:13px; }}
  th {{ color:#8b949e; font-weight:500; }}
  li {{ margin-bottom:6px; font-size:13px; color:#8b949e; line-height:1.5; }}
  .grid-2 {{ display:grid; grid-template-columns:1fr 1fr; gap:20px; }}
  @media(max-width:700px) {{ .grid-2 {{ grid-template-columns:1fr; }} }}
  #search-bar {{ position:sticky; top:0; z-index:100; background:#0d1117; border-bottom:1px solid #30363d; padding:12px 24px; margin:0 -24px 20px; }}
  .search-row {{ max-width:1000px; margin:0 auto; display:flex; gap:8px; align-items:center; }}
  #search-input {{ flex:1; background:#161b22; border:1px solid #30363d; border-radius:6px; padding:10px 14px; color:#e6edf3; font-size:14px; outline:none; min-height:44px; }}
  #search-input:focus {{ border-color:#58a6ff; }}
  #search-type {{ background:#161b22; border:1px solid #30363d; border-radius:6px; padding:10px; color:#e6edf3; font-size:13px; min-height:44px; }}
  #search-btn {{ background:#1f6feb; border:none; border-radius:6px; padding:10px 18px; color:#fff; font-size:13px; cursor:pointer; white-space:nowrap; min-height:44px; font-weight:500; }}
  #search-btn:hover {{ background:#388bfd; }}
  #home-btn {{ display:none; background:none; border:1px solid #30363d; border-radius:6px; padding:10px 14px; color:#8b949e; font-size:13px; cursor:pointer; white-space:nowrap; min-height:44px; }}
  #home-btn:hover {{ color:#e6edf3; border-color:#58a6ff; }}
  .result-card {{ display:flex; gap:12px; background:#1c2128; border:1px solid #30363d; border-radius:8px; padding:14px; margin-bottom:10px; transition:border-color .15s; }}
  .result-card:hover {{ border-color:#58a6ff44; }}
  .result-cover {{ width:60px; height:88px; object-fit:cover; border-radius:4px; background:#21262d; flex-shrink:0; }}
  .result-cover-ph {{ width:60px; height:88px; border-radius:4px; background:#21262d; flex-shrink:0; display:flex; align-items:center; justify-content:center; font-size:22px; }}
  .result-body {{ flex:1; min-width:0; }}
  .result-title {{ font-size:14px; font-weight:600; color:#e6edf3; margin-bottom:2px; }}
  .result-sub {{ font-size:12px; color:#8b949e; margin-bottom:4px; }}
  .result-genres {{ font-size:12px; color:#58a6ff; margin-bottom:6px; }}
  .result-desc {{ font-size:12px; color:#8b949e; line-height:1.4; margin-bottom:8px; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; }}
  .result-actions {{ display:flex; align-items:center; gap:6px; flex-wrap:wrap; }}
  .skeleton {{ background:linear-gradient(90deg,#1c2128 25%,#21262d 50%,#1c2128 75%); background-size:200% 100%; animation:shimmer 1.2s infinite; border-radius:4px; }}
  @keyframes shimmer {{ 0%{{background-position:200% 0}} 100%{{background-position:-200% 0}} }}
  .wl-item {{ display:flex; align-items:center; gap:12px; padding:12px 0; border-bottom:1px solid #21262d; cursor:pointer; }}
  .wl-item:hover .wl-title {{ color:#58a6ff; }}
  .wl-cover {{ width:40px; height:58px; object-fit:cover; border-radius:3px; background:#21262d; flex-shrink:0; }}
  .wl-cover-ph {{ width:40px; height:58px; border-radius:3px; background:#21262d; flex-shrink:0; display:flex; align-items:center; justify-content:center; font-size:16px; }}
  .wl-title {{ font-size:13px; font-weight:600; color:#e6edf3; transition:color .15s; }}
  .wl-badge {{ background:#161b22; border:1px solid #30363d; border-radius:12px; padding:2px 8px; font-size:11px; color:#8b949e; }}
  .filter-pill {{ background:#1c2128; border:1px solid #30363d; border-radius:20px; padding:8px 14px; font-size:12px; color:#8b949e; cursor:pointer; white-space:nowrap; min-height:36px; transition:all .15s; }}
  .filter-pill:hover {{ border-color:#58a6ff; color:#58a6ff; }}
  .filter-pill.active {{ background:#1f6feb22; border-color:#1f6feb; color:#58a6ff; }}
  .related-item {{ display:flex; align-items:center; gap:10px; padding:10px 0; border-bottom:1px solid #21262d; }}
  .star-r {{ display:inline-flex; gap:1px; }}
  .star-r span {{ font-size:18px; cursor:pointer; color:#30363d; transition:color .15s; padding:4px 2px; }}
  .star-r span.lit {{ color:#f0883e; }}
  #detail-overlay {{ position:fixed; inset:0; z-index:200; display:none; }}
  #detail-backdrop {{ position:absolute; inset:0; background:rgba(0,0,0,.7); }}
  #detail-panel {{ position:absolute; top:0; right:0; bottom:0; width:min(560px,100vw); background:#161b22; border-left:1px solid #30363d; overflow-y:auto; display:flex; flex-direction:column; transform:translateX(100%); transition:transform .25s ease; }}
  #detail-overlay.open #detail-panel {{ transform:translateX(0); }}
  #detail-overlay.open {{ display:block; }}
  .detail-backdrop-img {{ width:100%; height:180px; object-fit:cover; background:#1c2128; flex-shrink:0; }}
  .detail-body {{ padding:20px; flex:1; }}
  .detail-title {{ font-size:20px; font-weight:700; color:#e6edf3; margin-bottom:4px; }}
  .detail-meta {{ font-size:13px; color:#8b949e; margin-bottom:12px; }}
  .detail-genres {{ display:flex; gap:6px; flex-wrap:wrap; margin-bottom:14px; }}
  .detail-genre-tag {{ background:#1c2128; border:1px solid #30363d; border-radius:12px; padding:3px 10px; font-size:12px; color:#8b949e; }}
  .detail-section {{ margin-bottom:16px; }}
  .detail-section-label {{ font-size:11px; font-weight:600; color:#58a6ff; text-transform:uppercase; letter-spacing:.06em; margin-bottom:6px; }}
  .detail-cast {{ display:flex; gap:10px; overflow-x:auto; padding-bottom:4px; }}
  .cast-card {{ text-align:center; flex-shrink:0; width:64px; }}
  .cast-avatar {{ width:56px; height:56px; border-radius:50%; object-fit:cover; background:#21262d; margin:0 auto 4px; display:block; }}
  .cast-name {{ font-size:10px; color:#8b949e; line-height:1.2; }}
  .streaming-pills {{ display:flex; gap:6px; flex-wrap:wrap; }}
  .streaming-pill {{ background:#1c2128; border:1px solid #30363d; border-radius:6px; padding:5px 10px; font-size:12px; color:#e6edf3; }}
  .streaming-pill.flatrate {{ border-color:#3fb95055; color:#3fb950; }}
  .detail-link {{ display:inline-flex; align-items:center; gap:6px; padding:8px 14px; border:1px solid #30363d; border-radius:6px; font-size:13px; color:#58a6ff; text-decoration:none; transition:border-color .15s; margin-right:8px; margin-bottom:8px; }}
  .detail-link:hover {{ border-color:#58a6ff; background:#1f6feb11; }}
  .detail-close {{ position:sticky; top:0; z-index:1; background:#161b22; border-bottom:1px solid #21262d; padding:14px 20px; display:flex; justify-content:space-between; align-items:center; }}
  .detail-close button {{ background:none; border:none; color:#8b949e; font-size:22px; cursor:pointer; padding:4px; line-height:1; }}
  .detail-close button:hover {{ color:#e6edf3; }}
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
    </select>
    <button id="search-btn" onclick="doSearch()">Search</button>
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
  <h1>Entertainment Dashboard</h1>
  <div class="dim">Profile generated {generated} · {total_consumed} items consumed · {len(book_ratings)} ratings</div>
</div>

<!-- Stats bar -->
<div class="panel">
  <div class="stat-bar">
    <div class="stat"><div class="stat-n">{stats["books"] or 0}</div><div class="stat-l">Books read</div></div>
    <div class="stat"><div class="stat-n">{stats["audiobooks"] or 0}</div><div class="stat-l">Audiobooks</div></div>
    <div class="stat"><div class="stat-n">{len(to_read)}</div><div class="stat-l">To-read</div></div>
    <div class="stat"><div class="stat-n">{mean_str}</div><div class="stat-l">Mean rating</div></div>
    <div class="stat"><div class="stat-n">{stats["films"] or 0}</div><div class="stat-l">Films seen</div></div>
    <div class="stat"><div class="stat-n">{stats["shows"] or 0}</div><div class="stat-l">Shows seen</div></div>
    <div class="stat"><div class="stat-n">{stats["films_rated"] or 0}</div><div class="stat-l">Rated (film+TV)</div></div>
    <div class="stat"><div class="stat-n" style="color:#c792ea">{comic_total}</div><div class="stat-l">Comics owned</div></div>
  </div>
  <div class="dim" style="margin-top:12px;font-size:12px">Rating calibration: {cal.get("five_star_threshold","")}</div>
</div>

<!-- Genre fingerprint + Rating distribution -->
<div class="grid-2">
  <div class="panel">
    <h2>Genre Fingerprint</h2>
    {genre_chart}
  </div>
  <div class="panel">
    <h2>Rating Distribution</h2>
    {rating_hist}
    <div class="dim" style="margin-top:8px;font-size:12px">Tendency: {cal.get("tendency","—")}</div>
  </div>
</div>

<!-- Film genre fingerprint + Rating distribution -->
<div class="grid-2">
  <div class="panel">
    <h2>Film & TV Genres</h2>
    {film_genre_chart}
  </div>
  <div class="panel">
    <h2>Film Rating Distribution</h2>
    {film_rating_hist}
  </div>
</div>

<!-- Top directors -->
<div class="panel">
  <h2>Top Directors</h2>
  <table>
    <tr><th>Director</th><th>Films</th><th>Avg</th></tr>
    {directors_html}
  </table>
</div>

<!-- Spotify -->
<div class="panel">
  <h2>Spotify</h2>
  <div class="stat-bar" style="margin-bottom:20px">
    <div class="stat"><div class="stat-n" style="color:#1db954">{spotify_total_plays}</div><div class="stat-l">Plays (≥30s)</div></div>
    <div class="stat"><div class="stat-n" style="color:#1db954">{spotify_total_hours}h</div><div class="stat-l">Listening time</div></div>
    <div class="stat"><div class="stat-n" style="color:#1db954">{spotify_total_artists}</div><div class="stat-l">Unique artists</div></div>
  </div>
  <div class="grid-2">
    <div>
      <h3>Top Artists by Plays</h3>
      {spotify_artists_html}
    </div>
    <div>
      <h3>Year by Year</h3>
      <table>
        <tr><th>Year</th><th>Plays</th><th>Hours</th></tr>
        {spotify_year_rows}
      </table>
    </div>
  </div>
</div>

<!-- Netflix -->
<div class="panel">
  <h2>Netflix</h2>
  <div class="stat-bar" style="margin-bottom:20px">
    <div class="stat"><div class="stat-n" style="color:#e50914">{netflix_total_shows}</div><div class="stat-l">Shows watched</div></div>
    <div class="stat"><div class="stat-n" style="color:#e50914">{netflix_total_films}</div><div class="stat-l">Films &amp; specials</div></div>
  </div>
  <div class="grid-2">
    <div>
      <h3>Recent Shows</h3>
      <table><tr><th>Title</th><th>Last watched</th></tr>{netflix_shows_html}</table>
    </div>
    <div>
      <h3>Recent Films</h3>
      <table><tr><th>Title</th><th>Watched</th></tr>{netflix_films_html}</table>
    </div>
  </div>
  {f'<div style="margin-top:16px"><h3>Rated</h3><table><tr><th>Title</th><th></th></tr>{netflix_rated_html}</table></div>' if netflix_rated_html else ''}
</div>

<!-- Themes + Dislikes -->
<div class="grid-2">
  <div class="panel">
    <h2>Core Themes</h2>
    <ul style="padding-left:16px">{themes_html}</ul>
  </div>
  <div class="panel">
    <h2>Dislikes Pattern</h2>
    <ul style="padding-left:16px">{dislikes_html}</ul>
  </div>
</div>

<!-- Taste clusters -->
<div class="panel">
  <h2>Taste Clusters</h2>
  {clusters_html}
</div>

<!-- Recommendations -->
<div class="panel">
  <h2>Recommendations <span style="font-size:13px;font-weight:400;color:#8b949e;text-transform:none;letter-spacing:0">— {len(recs)} across all media</span></h2>
  {all_recs_html}
</div>

<!-- Top authors + Series tracker -->
<div class="grid-2">
  <div class="panel">
    <h2>Top Authors</h2>
    <table>
      <tr><th>Author</th><th>Books</th><th>Avg</th></tr>
      {authors_html}
    </table>
  </div>
  <div class="panel">
    <h2>Series Read</h2>
    {series_html}
  </div>
</div>

<!-- To-read queue -->
<div class="panel">
  <h2>To-Read Queue ({len(to_read)})</h2>
  <table>
    <tr><th>Title</th><th>Author</th></tr>
    {to_read_html}
  </table>
</div>

<!-- Comics & Graphic Novels -->
<div class="panel">
  <h2>Comics &amp; Graphic Novels
    <span style="font-size:13px;font-weight:400;color:#8b949e;text-transform:none;letter-spacing:0">
      — {comic_total} albums owned
    </span>
  </h2>
  <div style="background:#1c2128;border:1px solid #c792ea44;border-radius:8px;padding:12px 16px;margin-bottom:20px;display:flex;align-items:flex-start;gap:10px">
    <span style="font-size:18px;flex-shrink:0">📚</span>
    <div>
      <div style="font-size:13px;font-weight:600;color:#c792ea;margin-bottom:4px">Mostly read as a teenager / young adult</div>
      <div class="dim" style="font-size:12px;line-height:1.5">
        These are dear to the heart but the context is nostalgia, not current taste.
        Apply <strong style="color:#e6edf3">lower relevancy</strong> when generating new comic recommendations — prefer confirming emotional resonance over pure novelty matching.
      </div>
    </div>
  </div>
  <h3 style="margin-bottom:12px">Series</h3>
  {comic_series_html}
  {f'''<h3 style="margin-top:20px;margin-bottom:12px">Standalone albums</h3>
  <table>
    <tr><th>Title</th><th>Author</th><th>Year</th></tr>
    {comic_standalone_html}
  </table>''' if comic_standalone_html else ''}
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

function rateRec(id, stars) {{
  const ratings = JSON.parse(localStorage.getItem('rated_recs') || '{{}}');
  ratings[id] = stars;
  localStorage.setItem('rated_recs', JSON.stringify(ratings));
  // Persist as dismissed so it stays gone on reload
  const existing = JSON.parse(localStorage.getItem('dismissed_recs') || '[]');
  if (!existing.includes(id)) {{ existing.push(id); localStorage.setItem('dismissed_recs', JSON.stringify(existing)); }}
  // Animate out: fix current height first, then collapse
  const card = document.getElementById('rec-'+id);
  if (card) {{
    card.style.overflow = 'hidden';
    card.style.maxHeight = card.offsetHeight + 'px';
    card.style.marginBottom = card.style.marginBottom || getComputedStyle(card).marginBottom;
    void card.offsetHeight; // force reflow so browser registers the starting values
    card.style.transition = 'opacity .25s ease, max-height .35s ease .15s, margin-bottom .35s ease .15s, padding .35s ease .15s';
    card.style.opacity = '0';
    card.style.maxHeight = '0';
    card.style.marginBottom = '0';
    card.style.paddingTop = '0';
    card.style.paddingBottom = '0';
    setTimeout(() => card.remove(), 600);
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
  loadWatchlist();
}});

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
  return t === 'book' ? '📖' : t === 'tv_show' ? '📺' : '🎬';
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
      <button class="action-btn detail-btn" onclick="showDetail('${{item.id}}')">Details ↗</button>
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
async function showDetail(itemId) {{
  const overlay = document.getElementById('detail-overlay');
  const body = document.getElementById('detail-content');
  document.getElementById('detail-panel-title').textContent = '';
  body.innerHTML = `<div style="padding:20px"><div class="skeleton" style="height:180px;border-radius:0;margin:-20px -20px 20px"></div><div class="skeleton" style="height:24px;width:60%;margin-bottom:12px"></div><div class="skeleton" style="height:14px;width:40%;margin-bottom:20px"></div><div class="skeleton" style="height:80px"></div></div>`;
  overlay.classList.add('open');
  document.body.style.overflow='hidden';

  try {{
    const r = await fetch(API+'/api/detail/'+encodeURIComponent(itemId));
    const d = await r.json();
    document.getElementById('detail-panel-title').textContent = d.title||'';
    if (d.media_type === 'book') {{
      body.innerHTML = renderBookDetail(d, itemId);
    }} else {{
      body.innerHTML = renderFilmDetail(d, itemId);
    }}
    // Wire watchlist button
    const wlBtn = document.getElementById('detail-wl-btn');
    if(wlBtn) {{
      const matchedItem = _lastResults.find(r=>r.id===itemId);
      if(matchedItem) wlBtn.onclick = ()=>toggleItemWatchlist(matchedItem, wlBtn);
    }}
  }} catch(e) {{
    body.innerHTML = '<div style="padding:20px;color:#8b949e">Failed to load details.</div>';
  }}
}}

function closeDetail() {{
  const overlay = document.getElementById('detail-overlay');
  overlay.classList.remove('open');
  document.body.style.overflow='';
  setTimeout(()=>{{ document.getElementById('detail-content').innerHTML=''; }}, 260);
}}

document.addEventListener('keydown', e=>{{ if(e.key==='Escape') closeDetail(); }});

function renderFilmDetail(d, itemId) {{
  const meta = [d.directors&&d.directors.length?d.directors.join(', '):'', d.year, d.runtime_min?d.runtime_min+'min':d.seasons?d.seasons+' seasons':''].filter(Boolean).join(' · ');
  const genres = (d.genres||[]).map(g=>`<span class="detail-genre-tag">${{g}}</span>`).join('');
  const cast = (d.cast||[]).map(c=>{{
    const img = c.profile ? `<img class="cast-avatar" src="${{c.profile}}" alt="${{c.name}}">` : `<div class="cast-avatar" style="display:flex;align-items:center;justify-content:center;font-size:20px">👤</div>`;
    return `<div class="cast-card">${{img}}<div class="cast-name">${{c.name}}</div></div>`;
  }}).join('');
  const streamPills = (d.streaming_de||[]).map(s=>`<span class="streaming-pill flatrate">${{s}}</span>`).join('');
  const rentPills = (d.rent_de||[]).map(s=>`<span class="streaming-pill">${{s}}</span>`).join('');
  const backdrop = d.backdrop_url ? `<img class="detail-backdrop-img" src="${{d.backdrop_url}}" alt="">` : '';
  const imdbLink = d.imdb_id ? `<a class="detail-link" href="https://www.imdb.com/title/${{d.imdb_id}}" target="_blank">IMDb ↗</a>` : '';
  const jwLink = d.justwatch_url ? `<a class="detail-link" href="${{d.justwatch_url}}" target="_blank">JustWatch ↗</a>` : '';
  const matched = _lastResults.find(r=>r.id===itemId)||{{}};
  const wlLabel = matched.watchlist ? '✓ Watchlist' : '+ Watchlist';
  const wlCls = matched.watchlist ? 'saved' : '';
  const savedRating = matched.rating||0;
  const starsHtml = [1,2,3,4,5].map(i=>`<span style="font-size:22px;cursor:pointer;color:${{i<=savedRating?'#f0883e':'#30363d'}};padding:4px" onclick="rateItem('${{itemId}}',${{i}})"  onmouseenter="this.style.color='#f0883e'" onmouseleave="this.style.color=this.className?'#f0883e':(${{i<=savedRating}})? '#f0883e':'#30363d'">★</span>`).join('');
  const score = d.vote_average ? `<span style="color:#f0883e;font-weight:600">${{d.vote_average}}</span><span class="dim"> / 10 (TMDB)</span>` : '';
  return `
    ${{backdrop}}
    <div class="detail-body">
      <div class="detail-title">${{d.title}}</div>
      <div class="detail-meta">${{meta}} ${{score}}</div>
      <div class="detail-genres">${{genres}}</div>
      ${{d.tagline?`<p style="font-style:italic;color:#8b949e;font-size:13px;margin-bottom:14px">"${{d.tagline}}"</p>`:''}}
      <div class="detail-section">
        <div class="detail-section-label">Synopsis</div>
        <p style="font-size:13px;color:#8b949e;line-height:1.6">${{d.overview||'No synopsis available.'}}</p>
      </div>
      ${{cast?`<div class="detail-section"><div class="detail-section-label">Cast</div><div class="detail-cast">${{cast}}</div></div>`:''}}
      ${{(streamPills||rentPills)?`<div class="detail-section"><div class="detail-section-label">Where to watch (DE)</div><div class="streaming-pills">${{streamPills}}${{rentPills}}</div></div>`:''}}
      <div class="detail-section">
        <div class="detail-section-label">Your rating</div>
        <div>${{starsHtml}}</div>
      </div>
      <div style="margin-top:16px;display:flex;align-items:center;gap:8px;flex-wrap:wrap">
        <button class="action-btn watchlist ${{wlCls}}" id="detail-wl-btn">${{wlLabel}}</button>
        ${{imdbLink}}${{jwLink}}
      </div>
    </div>`;
}}

function renderBookDetail(d, itemId) {{
  const matched = _lastResults.find(r=>r.id===itemId)||{{}};
  const wlLabel = matched.watchlist ? '✓ To-read list' : '+ To-read list';
  const wlCls = matched.watchlist ? 'saved' : '';
  const savedRating = matched.rating||0;
  const starsHtml = [1,2,3,4,5].map(i=>`<span style="font-size:22px;cursor:pointer;color:${{i<=savedRating?'#f0883e':'#30363d'}};padding:4px" onclick="rateItem('${{itemId}}',${{i}})">★</span>`).join('');
  const subjects = (d.subjects||[]).map(s=>`<span class="detail-genre-tag">${{s}}</span>`).join('');
  const cover = d.cover_url ? `<img src="${{d.cover_url}}" style="width:120px;border-radius:6px;margin-bottom:16px" alt="">` : '';
  return `
    <div class="detail-body">
      ${{cover}}
      <div class="detail-title">${{d.title}}</div>
      <div class="detail-meta">${{[d.author,d.year].filter(Boolean).join(' · ')}}</div>
      <div class="detail-genres" style="margin-bottom:14px">${{subjects}}</div>
      ${{d.description?`<div class="detail-section"><div class="detail-section-label">Description</div><p style="font-size:13px;color:#8b949e;line-height:1.6">${{d.description}}</p></div>`:''}}
      <div class="detail-section">
        <div class="detail-section-label">Your rating</div>
        <div>${{starsHtml}}</div>
      </div>
      <div style="margin-top:16px;display:flex;align-items:center;gap:8px;flex-wrap:wrap">
        <button class="action-btn watchlist ${{wlCls}}" id="detail-wl-btn">${{wlLabel}}</button>
        <a class="detail-link" href="${{d.goodreads_url}}" target="_blank">Goodreads ↗</a>
        <a class="detail-link" href="${{d.audible_url}}" target="_blank">Audible DE ↗</a>
        <a class="detail-link" href="${{d.ol_url}}" target="_blank">Open Library ↗</a>
      </div>
    </div>`;
}}

// ── Search-then-detail (for rec cards) ───────────────────────────────────────
async function searchAndShowDetail(title, mediaType) {{
  // Show loading detail immediately
  const overlay = document.getElementById('detail-overlay');
  const body = document.getElementById('detail-content');
  document.getElementById('detail-panel-title').textContent = title;
  body.innerHTML = `<div style="padding:20px"><div class="skeleton" style="height:180px;border-radius:0;margin:-20px -20px 20px"></div><div class="skeleton" style="height:24px;width:60%;margin-bottom:12px"></div><div class="skeleton" style="height:80px"></div></div>`;
  overlay.classList.add('open');
  document.body.style.overflow = 'hidden';

  try {{
    const r = await fetch(`${{API}}/api/search?q=${{encodeURIComponent(title)}}&type=${{mediaType}}`);
    const results = await r.json();
    if (!results.length) {{
      body.innerHTML = `<div style="padding:20px;color:#8b949e">No details found for "${{title}}".</div>`;
      return;
    }}
    // Store in _lastResults so detail watchlist/rating buttons work
    results.forEach(item => {{ if (!_lastResults.find(r=>r.id===item.id)) _lastResults.push(item); }});
    const topResult = results[0];
    await showDetail(topResult.id);
  }} catch(e) {{
    body.innerHTML = `<div style="padding:20px;color:#8b949e">Failed to load details for "${{title}}".</div>`;
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
