"""OBS-052: offline rating checks with fake CLI, disposable SQLite DB and Node.js."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import use_project_venv  # noqa: E402,F401  re-runs under the project venv when fastapi is missing (ME-397)
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]
failures = 0
checks = 0


def check(label, condition, info=""):
    global failures, checks
    checks += 1
    print(f"{'PASS' if condition else 'FAIL'} OBS-052: {label}" +
          (f" ({info})" if not condition and info else ""))
    failures += not condition


with tempfile.TemporaryDirectory(prefix="obs-052-eval-") as folder:
    tmp = Path(folder)
    os.environ["OBS_DB_PATH"] = str(tmp / "test.db")
    os.environ["OBS_CLAUDE_TOKEN_FILE"] = str(tmp / "no-token")
    prompts = tmp / "prompts.jsonl"
    cli = tmp / "claude"
    cli.write_text(f'''#!{sys.executable}
import json, sys
from pathlib import Path
system = sys.argv[sys.argv.index("--system-prompt") + 1]
prompt = sys.stdin.read()
with Path({str(prompts)!r}).open("a") as f:
    f.write(json.dumps({{"system": system, "prompt": prompt}}) + "\\n")
print("Rating discussion" if "Name this conversation" in system else "A thoughtful film.")
''')
    cli.chmod(0o700)
    os.environ["OBS_CLAUDE_CLI"] = str(cli)

    import httpx
    from fastapi.testclient import TestClient
    import server
    import oracle_actions as actions
    import build_dashboard as dashboard
    from db import get_conn

    with TestClient(server.app, raise_server_exceptions=False) as client:
        with get_conn() as conn:
            conn.executemany("INSERT INTO media_items (id,media_type,title,year,source,source_id,genres) VALUES (?,?,?,?,?,?,?)", [
                ("film", "film", "Seed Film", 2020, "imdb", "tt052", "[]"),
                ("tmdb:movie:52", "film", "Unrated Film", 2021, "tmdb", "52", "[]"),
                ("thumb", "film", "Netflix Thumb", 2022, "netflix", "52", "[]"),
            ])
            conn.executemany("INSERT INTO user_interactions (media_id,interaction,rating,source) VALUES (?,?,?,?)", [
                ("film", "rated", 4.0, "imdb"), ("thumb", "rated", 1.5, "netflix"),
            ])
        result = client.post("/api/ask", json={"question": "What did I rate Seed Film?"})
        check("fake CLI answers", result.status_code == 200, result.text)
        turn = next(json.loads(line) for line in prompts.read_text().splitlines()
                    if "personal entertainment advisor" in json.loads(line)["system"])
        system, data = turn["system"], turn["prompt"]
        check("Oracle film uses out of ten and no rating stars", "Seed Film (2020) | 8" in data and "★" not in system + data)
        check("Oracle keeps Netflix thumbs as thumbs (OBS-053)", "Netflix Thumb (2022) | thumbs down" in data)
        check("Oracle averages keep a decimal", "average 8.0/10" in data)
        for stored, shown in [(4.0, "8/10"), (4.5, "9/10"), (3.5, "7/10")]:
            action = {"action": "rate", "title": "Seed Film", "rating": stored}
            check(f"describe {stored} as {shown}", actions.describe(action) == f"Rate Seed Film {shown}")
        check("reviewer explains 8/10 = rating 4.0 and bare scores", "8/10" in actions.REVIEW_SYSTEM and
              "4.0" in actions.REVIEW_SYSTEM and "bare" in actions.REVIEW_SYSTEM and "out of ten" in actions.REVIEW_SYSTEM)
        row = {"context": "[]", "action": json.dumps(action | {"rating": 4.0}), "target": "{}", "user_message": "rate Seed Film 8/10"}
        check("review proposed_change uses out of ten", '"proposed_change": "Rate Seed Film 8/10"' in actions.review_prompt(row))
        raw = action | {"rating": 3.5, "media_type": "film", "user_quote": "rate Seed Film 7"}
        check("actions accept stored 3.5", actions.validate(raw, raw["user_quote"])[1] is None)
        check("actions reject stored 7", actions.validate(raw | {"rating": 7}, raw["user_quote"])[1] is not None)

        def rate(value):
            return client.post("/api/interactions", json={"item_id": "tmdb:movie:52", "interaction_type": "rating", "value": value})

        check("POST stored 3.5 succeeds", rate("3.5").status_code == 200)
        with get_conn() as conn:
            check("POST stores 3.5 unchanged", conn.execute("SELECT rating FROM user_interactions WHERE media_id='tmdb:movie:52'").fetchone()[0] == 3.5)
        for invalid in ["7", "0.25", "nope", "NaN", "inf", "0", "5.5"]:
            check(f"POST rejects {invalid} with 422", rate(invalid).status_code == 422)
        with get_conn() as conn:
            check("invalid POST leaves saved rating intact", conn.execute("SELECT rating FROM user_interactions WHERE media_id='tmdb:movie:52'").fetchone()[0] == 3.5)
        for valid in ["0.5", "1", "1.5", "2", "2.5", "3", "3.5", "4", "4.5", "5"]:
            check(f"POST accepts stored half step {valid}", rate(valid).status_code == 200)
        rate("3.5")

        async_client = httpx.AsyncClient

        def upstream(request):
            if request.url.path.endswith("/credits"):
                return httpx.Response(200, json={"cast": [], "crew": []})
            if request.url.path.endswith("/watch/providers"):
                return httpx.Response(200, json={"results": {}})
            return httpx.Response(200, json={"title": "Unrated Film", "release_date": "2021-01-01", "vote_average": 7.4})

        with patch.object(server, "_tmdb_key", return_value="fake"), patch.object(httpx, "AsyncClient", side_effect=lambda **kw: async_client(transport=httpx.MockTransport(upstream), **kw)):
            detail = client.get("/api/culture/detail?key=film:tmdb:movie:52").json()
        check("reopened detail returns stored 3.5", detail["your_rating"] == 3.5, detail)
        check("external TMDB score stays 7.4", detail["vote_average"] == 7.4)
        item = client.post("/api/items", json={"id": "ol:OL052W", "source": "openlibrary", "source_id": "OL052W", "media_type": "book", "title": "Seed Book"})
        check("unrated detail item can be created", item.status_code == 200)
        book_rate = client.post("/api/interactions", json={"item_id": item.json()["item_id"], "interaction_type": "rating", "value": "4.5"})
        check("detail book stores 4.5 for 9/10", book_rate.status_code == 200 and server._culture_rating("ol:OL052W") == 4.5)
        with get_conn() as conn:
            conn.execute("UPDATE media_items SET source_id='tt0000052' WHERE id='film'")
        check("detail reads existing IMDb import without rescaling", server._culture_rating("tmdb:movie:999", "tt0000052") == 4.0)
        check("detail widget avoids obsolete culture interaction endpoint", "/api/culture/interact'" not in (ROOT / "static/detail.js").read_text())
        helper = getattr(dashboard, "format_rating", None)
        check("dashboard helper formats ratings and average", helper is not None and
              [helper(4.0), helper(4.5), helper(3.8, average=True)] == ["8/10", "9/10", "7.6/10"])
        with get_conn() as conn:
            conn.execute("INSERT INTO taste_profile (id,generated_at,rating_calibration) VALUES (1,'2026-11-09',?)",
                         (json.dumps({"mean": 3.8, "five_star_threshold": "Keep calibration fixture"}),))
            before = [tuple(row) for row in conn.execute("SELECT * FROM user_interactions ORDER BY id")]
            html = dashboard.render(conn)
            after = [tuple(row) for row in conn.execute("SELECT * FROM user_interactions ORDER BY id")]
        check("dashboard renders converted mean and all distribution labels", "7.6/10" in html and
              all(f'>{score}/10</div>' in html for score in range(1, 11)))
        check("dashboard keeps calibration text and stored rows", "Rating calibration: Keep calibration fixture" in html and before == after)
        check("TikTok derived scores are out of ten", "Liked (8/10)" in html and "Favorited (10/10)" in html and "watch=4/10" in html)
        check("Taste Map has no numeric star ratings", not re.search(r"\d★", (ROOT / "brain.html").read_text()))

        # Regression OBS-052: F1 preserves imported rating identity and completion history.
        with get_conn() as conn:
            conn.execute("UPDATE user_interactions SET date_completed='2020-04-05', date_added='2020-04-06' WHERE media_id='film'")
            old = dict(conn.execute("SELECT * FROM user_interactions WHERE media_id='film'").fetchone())
        response = client.post("/api/interactions", json={"item_id": "film", "interaction_type": "rating", "value": "4.5"})
        with get_conn() as conn:
            rows = [dict(r) for r in conn.execute("SELECT * FROM user_interactions WHERE media_id='film'")]
        check("Regression OBS-052: F1 update preserves source, dates and row id", response.status_code == 200 and rows == [old | {"rating": 4.5}], rows)
        with get_conn() as conn:
            conn.execute("INSERT INTO user_interactions (media_id,interaction,rating,source,date_completed) VALUES ('film','completed',3,'netflix','2020-05-06')")
            conn.execute("INSERT INTO user_interactions (media_id,interaction,shelf,source) VALUES ('film','watchlist','to-watch','manual')")
            old_rows = [dict(r) for r in conn.execute("SELECT * FROM user_interactions WHERE media_id='film' ORDER BY id")]
        client.post("/api/interactions", json={"item_id": "film", "interaction_type": "rating", "value": "4"})
        with get_conn() as conn:
            rows = [dict(r) for r in conn.execute("SELECT * FROM user_interactions WHERE media_id='film' ORDER BY id")]
        check("Regression OBS-052: F1 updates every existing rating and preserves non-rating rows", rows == [r | {"rating": 4.0} if r["rating"] is not None else r for r in old_rows], rows)
        with get_conn() as conn:
            conn.execute("INSERT INTO media_items (id,media_type,title,source) VALUES ('fresh','film','Fresh','tmdb')")
        for value in ["3.5", "4"]:
            client.post("/api/interactions", json={"item_id": "fresh", "interaction_type": "rating", "value": value})
        with get_conn() as conn:
            rows = [dict(r) for r in conn.execute("SELECT * FROM user_interactions WHERE media_id='fresh'")]
        check("Regression OBS-052: F1 new manual rating has completion date and no duplicates", len(rows) == 1 and rows[0]["source"] == "manual" and bool(rows[0]["date_completed"]), rows)

        with get_conn() as conn:
            conn.executemany("INSERT INTO media_items (id,media_type,title,year,source,source_id,genres) VALUES (?,?,?,?,?,?,?)", [
                ("identity-imdb", "film", "Identity Film", 2001, "imdb", "tt052identity", "[]"),
                ("identity-netflix", "film", "Identity Film", 2001, "netflix", "identity", "[]"),
                ("identity-remake", "film", "Identity Film", 2021, "imdb", "tt052remake", "[]"),
                ("identity-book", "book", "Identity Book", 1999, "goodreads", "052", "[]"),
                ("identity-ol", "book", "Identity Book", None, "openlibrary", "OLIdentityW", "[]"),
            ])
            conn.executemany("INSERT INTO user_interactions (media_id,interaction,rating,source,date_completed) VALUES (?,'rated',?,?, '2002-01-02')", [
                ("identity-imdb", 5, "imdb"), ("identity-netflix", 4, "netflix"),
                ("identity-remake", 2, "imdb"), ("identity-book", 5, "goodreads"), ("identity-ol", 4, "openlibrary"),
            ])
            history = [dict(r) for r in conn.execute("SELECT * FROM user_interactions WHERE media_id LIKE 'identity-%' ORDER BY id")]
            queued = conn.execute("SELECT COUNT(*) FROM oracle_actions").fetchone()[0]

        def rate_work(title, media_type, rating, **extra):
            return client.post("/api/rate", json={"title": title, "media_type": media_type, "rating": rating, **extra})

        response = rate_work("identity film", "film", 3.5, year=2001)
        with get_conn() as conn:
            ratings = {r["media_id"]: r["rating"] for r in conn.execute("SELECT * FROM user_interactions WHERE media_id LIKE 'identity-%'")}
        check("Regression OBS-052: F2 rate actual film across imports without touching remake", response.status_code == 200 and response.json() == {"rating": 3.5} and ratings["identity-imdb"] == ratings["identity-netflix"] == 3.5 and ratings["identity-remake"] == 2, response.text)
        response = rate_work("Identity Book", "book", 4)
        with get_conn() as conn:
            rows = [dict(r) for r in conn.execute("SELECT * FROM user_interactions WHERE media_id LIKE 'identity-%' ORDER BY id")]
            count = conn.execute("SELECT COUNT(*) FROM media_items WHERE title='Identity Book'").fetchone()[0]
            now_queued = conn.execute("SELECT COUNT(*) FROM oracle_actions").fetchone()[0]
        expected = [r | {"rating": 3.5 if r["media_id"] in ("identity-imdb", "identity-netflix") else 4 if r["media_id"] in ("identity-book", "identity-ol") else r["rating"], "source": "oracle" if r["media_id"] == "identity-netflix" else r["source"]} for r in history]
        check("Regression OBS-052: F3 book rating updates Goodreads and OL in place, without queue or duplicate", response.status_code == 200 and rows == expected and count == 2 and queued == now_queued, response.text)
        ambiguous = rate_work("Identity Film", "film", 5)
        check("Regression OBS-052: ambiguous work returns inline-ready 409 reason", ambiguous.status_code == 409 and "ambiguous" in ambiguous.text, ambiguous.text)
        with get_conn() as conn:
            unchanged = [dict(r) for r in conn.execute("SELECT * FROM user_interactions WHERE media_id LIKE 'identity-%' ORDER BY id")]
        check("Regression OBS-052: refused resolve leaves all imports unchanged", unchanged == expected)
        for invalid in [7, 0.25, "NaN", "inf", 0, 5.5, "nope"]:
            response = rate_work("Identity Film", "film", invalid, year=2001)
            check(f"Regression OBS-052: work rating rejects {invalid}", response.status_code == 422, response.text)
        response = rate_work("Identity Film", "film", True, year=2001)
        check("Regression OBS-052: work rating rejects boolean scores", response.status_code == 422, response.text)
        unknown = rate_work("Previously Unknown", "book", 3.5)
        with get_conn() as conn:
            rows = conn.execute("SELECT ui.rating FROM media_items m JOIN user_interactions ui ON ui.media_id=m.id WHERE m.title='Previously Unknown'").fetchall()
        check("Regression OBS-052: unknown work creates one rated item", unknown.status_code == 200 and len(rows) == 1 and rows[0][0] == 3.5, unknown.text)

        from unittest.mock import AsyncMock
        search_items = [
            {"id": "tmdb:movie:identity", "title": "IDENTITY FILM", "media_type": "film", "year": 2001, "source": "tmdb"},
            {"id": "ol:OLIdentityW", "title": "identity book", "media_type": "book", "year": None, "source": "openlibrary"},
            {"id": "tmdb:movie:other-year", "title": "Identity Film", "media_type": "film", "year": 2025, "source": "tmdb"},
            {"id": "ol:wrong-type", "title": "Identity Film", "media_type": "book", "year": 2001, "source": "openlibrary"},
        ]
        with patch.object(server, "search", new=AsyncMock(return_value=search_items)):
            found = client.get("/api/search?q=identity").json()["results"]
        check("Regression OBS-052: F2 F3 re-search finds same-work ratings by title, type and year", [r["rating"] for r in found] == [3.5, 4, None, None], found)

        def identity_upstream(request):
            if request.url.host == "openlibrary.org":
                return httpx.Response(200, json={"title": "Identity Book", "first_publish_date": "1999"})
            if request.url.path.endswith("/credits"):
                return httpx.Response(200, json={"cast": [], "crew": []})
            if request.url.path.endswith("/watch/providers"):
                return httpx.Response(200, json={"results": {}})
            return httpx.Response(200, json={"title": "Identity Film", "release_date": "2001-01-01", "vote_average": 7.4})

        with patch.object(server, "_tmdb_key", return_value="fake"), patch.object(httpx, "AsyncClient", side_effect=lambda **kw: async_client(transport=httpx.MockTransport(identity_upstream), **kw)):
            film_detail = client.get("/api/culture/detail?key=film:tmdb:movie:identity").json()
            book_detail = client.get("/api/culture/detail?key=book:ol:OLIdentityW").json()
        check("Regression OBS-052: F2 F3 detail IDs inherit actual work rating", film_detail.get("your_rating") == 3.5 and book_detail.get("your_rating") == 4, [film_detail, book_detail])

        # Regression OBS-052: F6 reads resolve exactly the work that writes resolve.
        with get_conn() as conn:
            conn.executemany("INSERT INTO media_items (id,media_type,title,year,source) VALUES (?,?,?,?,?)", [
                ("f6-old", "film", "Remade Film", 1980, "imdb"),
                ("f6-new", "film", "Remade Film", 2020, "imdb"),
                ("f6-unknown", "film", "Remade Film", None, "netflix"),
                ("f6-spider", "film", "Spider Man", 2002, "imdb"),
                ("f6-priority", "film", "Priority Film", 2000, "imdb"),
                ("f6-later", "film", "Priority Film", 2000, "netflix"),
                ("f6-unrated", "film", "No Rating", 2000, "imdb"),
            ])
            conn.executemany("INSERT INTO user_interactions (media_id,interaction,rating,source) VALUES (?,'rated',?,?)", [
                ("f6-old", 4, "imdb"), ("f6-new", 1, "imdb"),
                ("f6-unknown", 2.5, "netflix"), ("f6-spider", 2, "imdb"),
                ("f6-later", 2, "netflix"), ("f6-priority", 4.5, "imdb"),
            ])
        spider_save = rate_work("Spider-Man", "film", 3.5, year=2002)
        f6_queries = [("Remade Film", 1980), ("Remade Film", 2020),
                      ("Remade Film", None), ("Spider-Man", 2002),
                      ("Priority Film", 2000), ("No Rating", 2000), ("Absent Film", 2000)]
        with patch.object(server, "search", new=AsyncMock(return_value=[
            {"id": f"tmdb:movie:f6-{i}", "title": title, "media_type": "film", "year": year, "source": "tmdb"}
            for i, (title, year) in enumerate(f6_queries)
        ])):
            f6_found = client.get("/api/search?q=fixtures").json()["results"]
        f6_ratings = [r["rating"] for r in f6_found]
        f6_details = [server._culture_rating(f"tmdb:movie:f6-{i}", title=title, media_type="film", year=year)
                      for i, (title, year) in enumerate(f6_queries)]
        check("Regression OBS-052: F6 known remakes exclude unknown-year ratings", f6_ratings[:2] == f6_details[:2] == [4, 1], [f6_ratings, f6_details])
        check("Regression OBS-052: F6 ambiguous works inherit no rating", f6_ratings[2] is None and f6_details[2] is None, [f6_ratings, f6_details])
        check("Regression OBS-052: F6 punctuation-normalized save reads back", spider_save.status_code == 200 and f6_ratings[3] == f6_details[3] == 3.5, [f6_ratings, f6_details])
        check("Regression OBS-052: F6 source priority matches resolved item order", f6_ratings[4] == f6_details[4] == 4.5, [f6_ratings, f6_details])
        check("Regression OBS-052: F6 unrated and missing works inherit no rating", f6_ratings[5:] == f6_details[5:] == [None, None])
        with get_conn() as conn:
            before_reads = conn.total_changes
            for title, year in f6_queries:
                server._work_rating(conn, title, "film", year)
            check("Regression OBS-052: F6 inherited reads have no write side effects", conn.total_changes == before_reads)

        def broken_apply(conn, action, target):
            conn.execute("UPDATE user_interactions SET rating=1 WHERE media_id='identity-imdb'")
            raise RuntimeError("simulated write failure")

        with patch.object(actions, "apply", side_effect=broken_apply):
            rolled_back = rate_work("Identity Film", "film", 5, year=2001)
        with get_conn() as conn:
            rating = conn.execute("SELECT rating FROM user_interactions WHERE media_id='identity-imdb'").fetchone()[0]
        check("Regression OBS-052: resolve/apply transaction rolls back failed writes", rolled_back.status_code == 500 and rating == 3.5, rolled_back.text)

        detail_js = (ROOT / "static/detail.js").read_text()
        rate_js = detail_js.split("async function rateDetailItem(")[1].split("function hoverDetailStars")[0]
        search_js = html.split("async function rateItem(")[1].split("async function showRelated")[0]
        check("Regression OBS-052: both rating widgets use only the work rating endpoint", all("/api/rate" in js and "/api/items" not in js and "/api/interactions" not in js for js in [rate_js, search_js]))
        check("Regression OBS-052: widgets show refusal reason beside saved rating", all(".detail" in js and "error" in js.lower() for js in [rate_js, search_js]))

        # Regression OBS-052: F4 double unrounded averages, then format once.
        start = detail_js.index("function renderDirectorDetail(")
        end = detail_js.index("function ", start + 9)
        script = detail_js[start:end] + '\nfunction linkRow(){return "";}\nconsole.log(renderDirectorDetail({name:"Director",your_avg:4.2,your_count:2,your_films:[{rating:4},{rating:4.5}]}));'
        director_html = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True, timeout=10).stdout
        check("Regression OBS-052: F4 director mean 4.25 displays 8.5/10", "avg 8.5/10" in director_html, director_html)
        check("Regression OBS-052: F4 dashboard formats raw mean 4.25 as 8.5/10", dashboard.format_rating(4.25, average=True) == "8.5/10")
        source = (ROOT / "server.py").read_text()
        check("Regression OBS-052: F4 Oracle SQL leaves rating averages unrounded", not re.search(r"ROUND\(AVG\(ui.rating\)", source, re.I))

        # Execute the actual widget handlers against small DOM/fetch fakes.
        # Browser screenshots and layout checks still require a browser-enabled runner.
        widget_script = r'''
const assert = require('node:assert/strict');
const API = '';
function button() {
  const classes = new Set();
  return {style:{}, disabled:false, classList:{
    toggle:(name,on)=>on?classes.add(name):classes.delete(name),
    add:name=>classes.add(name), contains:name=>classes.has(name)
  }, get className(){return [...classes].join(' ')}, set className(s){classes.clear();}};
}
let nodes, buttons, _lastResults, calls, response;
const document = {getElementById:id=>nodes[id]};
async function fetch(url, options) {
  calls.push({url, body:JSON.parse(options.body)});
  const reply=response;
  if (reply.wait) await reply.wait;
  return {ok:reply.ok, json:async()=>reply.body};
}
function setup(kind, rating) {
  buttons = Array.from({length:10},button);
  const ownButtons=buttons;
  const item={id:'tmdb:movie:52',title:'Identity Film',year:2001,media_type:'film',rating};
  const container={dataset:{saved:String(rating)},_item:item,querySelectorAll:()=>ownButtons};
  _lastResults=[item]; calls=[];
  nodes={'detail-stars':container,'detail-rating-value':{textContent:(rating*2)+'/10'},
    'detail-rating-error':{},'detail-history-rating':{},'stars-r-tmdb_movie_52':container,
    'rating-r-tmdb_movie_52':{textContent:(rating*2)+'/10'},'rating-error-tmdb_movie_52':{}};
  buttons.forEach((b,i)=>{nodes['sr-tmdb_movie_52-'+(i+1)]=b;});
  return {item,container,label:nodes[kind==='detail'?'detail-rating-value':'rating-r-tmdb_movie_52'],
    error:nodes[kind==='detail'?'detail-rating-error':'rating-error-tmdb_movie_52']};
}
'''
        widget_script += "\nasync function rateDetailItem(" + rate_js
        widget_script += detail_js[detail_js.index("function resetDetailStars("):detail_js.index("function closeDetail(")]
        widget_script += html[html.index("function rstItem("):html.index("async function rateItem(")]
        widget_script += "\nasync function rateItem(" + search_js
        widget_common = widget_script
        widget_script += r'''
(async()=>{
  for (const kind of ['detail','search']) {
    const call=()=>kind==='detail'?rateDetailItem(7):rateItem('tmdb:movie:52',7);
    let state=setup(kind,4);
    response={ok:true,body:{rating:3.5}};
    await call();
    assert.deepEqual(calls,[{url:'/api/rate',body:{title:'Identity Film',year:2001,media_type:'film',rating:3.5}}]);
    assert.equal(state.label.textContent,'7/10');
    assert.equal(buttons.filter(b=>b.classList.contains('lit')).length,7);
    assert.ok(buttons.every(b=>!b.disabled));
    response={ok:false,body:{detail:'ambiguous: say which year'}};
    await call();
    assert.equal(state.label.textContent,'7/10');
    assert.equal(state.error.textContent,'ambiguous: say which year');
    assert.equal(buttons.filter(b=>b.classList.contains('lit')).length,7);
    assert.ok(buttons.every(b=>!b.disabled));
    state=setup(kind,0);
    await call();
    assert.equal(state.label.textContent,'Unrated');
    assert.equal(buttons.filter(b=>b.classList.contains('lit')).length,0);
    console.log(kind+' success, refusal and unrated restoration passed');
  }
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
        widgets = subprocess.run(["node", "-e", widget_script], capture_output=True, text=True, timeout=10)
        check("Regression OBS-052: widget success and refusal preserve saved state and show reason", widgets.returncode == 0, widgets.stderr)

        # Regression OBS-052: F7 a late save must not alter the next panel or its pending buttons.
        for stale_ok in [True, False]:
            race_script = widget_common + "\nconst staleOK=" + json.dumps(stale_ok) + r''';
(async()=>{
  const a=setup('detail',4), aButtons=buttons;
  let finishA;
  response={ok:staleOK,body:staleOK?{rating:3.5}:{detail:'A was refused'},wait:new Promise(r=>finishA=r)};
  const pendingA=rateDetailItem(7);
  const b=setup('detail',2), bButtons=buttons;
  b.item.title='Title B';
  const history=nodes['detail-history-rating'];
  history.textContent='4/10';
  resetDetailStars(b.container);
  let finishB;
  response={ok:true,body:{rating:4.5},wait:new Promise(r=>finishB=r)};
  const pendingB=rateDetailItem(9);
  finishA(); await pendingA;
  assert.equal(history.textContent,'4/10','A completion changed B history');
  assert.equal(b.label.textContent,'4/10');
  assert.equal(b.container.dataset.saved,'2');
  assert.equal(b.error.textContent,'');
  assert.equal(bButtons.filter(b=>b.classList.contains('lit')).length,4);
  assert.ok(bButtons.every(b=>b.disabled),'B pending buttons were reset by A');
  assert.equal(b.container.dataset.busy,'1');
  assert.ok(aButtons.every(b=>!b.disabled));
  finishB(); await pendingB;
  assert.equal(history.textContent,'9/10');
  assert.equal(b.label.textContent,'9/10');
  assert.equal(bButtons.filter(b=>b.classList.contains('lit')).length,9);
  assert.ok(bButtons.every(b=>!b.disabled));
  assert.equal(b.container.dataset.busy,undefined);
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
            race = subprocess.run(["node", "-e", race_script], capture_output=True, text=True, timeout=10)
            check(f"Regression OBS-052: F7 stale {'success' if stale_ok else 'refusal'} leaves current panel and buttons intact", race.returncode == 0, race.stderr)

        # The search box's default "All" option sends an empty type.
        async def _no_results(*args, **kwargs):
            return []
        real_search, server.search = server.search, _no_results
        blank_type = client.get("/api/search", params={"q": "Arrival", "type": "", "page": 1})
        server.search = real_search
        check("Regression OBS-052: F5 search with the default All option is accepted", blank_type.status_code == 200, blank_type.text)

        # Exercise every displayed data average, including the Oracle's SQL source.
        with get_conn() as conn:
            conn.execute("UPDATE media_items SET source='fixture'")
            conn.execute("UPDATE user_interactions SET source='fixture'")
            # OBS-054: the dashboard now counts every rated work, so earlier fixtures must not rate
            conn.execute("DELETE FROM user_interactions")
            conn.execute("DELETE FROM app_ratings")
            for kind, source in [("film", "imdb"), ("book", "goodreads")]:
                for n, rating in enumerate([4, 4, 4, 4.5]):
                    item_id = f"precision-{kind}-{n}"
                    conn.execute("INSERT INTO media_items (id,media_type,title,source,director,author,series_name,genres) VALUES (?,?,?,?,?,?,?,?)",
                                 (item_id, kind, item_id, source, "Precision Director" if kind == "film" else None, "Precision Author", "Precision Series" if kind == "book" else None, "[]"))
                    conn.execute("INSERT INTO user_interactions (media_id,interaction,rating,source,shelf) VALUES (?,'rated',?,?,?)", (item_id, rating, source, "read" if kind == "book" else None))
            precision_html = dashboard.render(conn)
        client.post("/api/ask", json={"question": "Compare my average film and book ratings."})
        data = [json.loads(line)["prompt"] for line in prompts.read_text().splitlines()
                if "personal entertainment advisor" in json.loads(line)["system"]][-1]
        check("Regression OBS-052: F4 Oracle film, director and book means round after doubling", "Films rated via IMDb: 4, average 8.2/10" in data and "Precision Director (avg 8.2/10, 4 films)" in data and "Books rated via Goodreads: 4, average 8.2/10" in data, data[:600])
        check("Regression OBS-052: F4 dashboard director and author means round after doubling", re.search(r"Precision Director</span></td><td>4</td><td>8.2/10", precision_html) is not None and "Precision Author</td><td>4</td><td>8.2/10" in precision_html)
        check("Regression OBS-052: F4 dashboard series and overall film means round after doubling", "4 read · avg 8.2/10" in precision_html and "4 rated · avg 8.2/10" in precision_html)

print(f"\n{failures}/{checks} check(s) failed." if failures else f"\nAll {checks} checks passed.")
sys.exit(1 if failures else 0)
