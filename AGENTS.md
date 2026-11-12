# Observatory — Project Instructions

## What this is

Self-hosted personal entertainment dashboard.
Public name: **Observatory**. GitHub: `waldo-van-der-code/observatory`.

Covers: Spotify streaming history, Goodreads, IMDB, Netflix, JustWatch, Audible, TikTok.

## Oracle deployment (live)

- URL: **https://observatory.vanderlore.de** — HTTP basic auth (user: waldo, pw in keychain)
- Host: oracle (`/home/ubuntu/observatory/`), systemd service `observatory.service`
- Port: 8088 (proxied by nginx)
- **Deploy script**: `./scripts/deploy.sh` — offline evals → git push → oracle pull + build → health-check all 5 pages → auto-rollback on failure → Oracle probe (warn only). **Always use this; never rsync or restart manually.**
- Health-checked pages: `/`, `/brain`, `/ask`, `/picks`, `/api/recs` — fetched on oracle via `127.0.0.1:8088` (no password in the script; the repo is public). The public URL must answer 401.
- `dashboard.html` is always built on oracle (never rsynced) to protect personal data gitignore

## Oracle auth + monitoring (OBS-048)

Ask the Oracle shells out to the `claude` CLI on oracle (Claude Code subscription, no API key).
- **Auth:** long-lived token from `claude setup-token` (valid 1 year) stored in `~/.secrets/claude-code-oauth-token` on oracle (mode 600); `server.py` passes it as `CLAUDE_CODE_OAUTH_TOKEN`. The plain `claude /login` OAuth session expired after ~2 weeks and broke Ask from ~2026-10 until 2026-10-24.
- **Renew:** `ssh -t oracle '/home/ubuntu/.nvm/versions/node/v22.23.2/bin/claude setup-token'`, then run `ssh oracle 'umask 077; tr -d "[:space:]" > ~/.secrets/claude-code-oauth-token'`, paste the token, Enter, Ctrl+D. No service restart needed (read per call). The file's mtime is the token age.
  - The token wraps over two terminal lines: `read`-based pastes keep only the first line, and drag-selecting easily grabs a trailing letter of the next line. A valid token is exactly 108 chars (`sk-ant-oat01-…AA`); check with `wc -c` and `curl 127.0.0.1:8088/api/oracle/health?fresh=1`.
- **Health:** `GET /api/oracle/health` runs a one-word haiku probe (success cached 30 min, `?fresh=1` bypasses). 503 when the CLI fails or the token is >335 days old.
- **Monitoring:** oracle `~/scripts/uptime-monitor.py` (every 10 min) checks "Observatory" (public 401 + local pages) and "Observatory Oracle (Ask)" (the health endpoint); Telegram alerts topic after 2 failed runs.
- **Evals:** `evals/test_oracle.py` (offline, fake CLIs, run by deploy.sh) and the live `/api/oracle/health` check in `evals/smoke.ts`.
- The CLI prints auth errors to **stdout**, not stderr — always read both.

## Oracle chat actions (OBS-050)

Waldo can change his data from the Ask chat ("I've seen that, remove it from my list", "rate it 4 stars"). Code: `scripts/oracle_actions.py`; table `oracle_actions`.
- The Oracle only *proposes*: an ```` ```observatory-actions ```` JSON block at the end of its answer, stripped before display and storage.
- Whitelist: `rate` (0.5-5, steps of 0.5), `mark_seen` (off watchlist + pick `seen` + a `completed/seen` row), `remove_from_list` (off watchlist + pick `dismissed`). Max 5 per message. Each needs a `user_quote` that occurs in Waldo's *latest* message, or it is rejected before review.
- The server resolves titles itself (all imports of the same work; unknown-year rows and picks only when no remake/other year exists). Unknown titles for `rate`/`mark_seen` get a new `media_items` row with `source='oracle'`.
- A separate Sonnet call (no tools, data in one escaped JSON block) must return `{"verdict":"approve"}`; anything else is a reject. If the target changed during review it is rejected. Review failures retry on the next question, then fail after 3 tries.
- Undo restores the before-snapshot, and is refused once the rows were changed again afterwards.
- Eval: `evals/test_oracle_actions.py` (offline, fake CLI, temp DB via `OBS_DB_PATH`), run by `deploy.sh`.

### `add_to_list` (ME-397)
Fourth whitelisted action: "add Schild's Ladder to my reading list". Film and tv_show go on shelf `to-watch`, book and comic on `to-read`; podcast and music are rejected. Same safety path as the others (quote check, max 5, server-side resolve, Sonnet review, identity recheck, undo). A work already on any list through any import is rejected as a duplicate.
- The row (`interaction='watchlist'`, `source='oracle'`) goes on the top-priority item of the work (e.g. the imdb id), so `db.get_watchlist` no longer filters by source: search-added rows (tmdb/openlibrary/googlebooks) always show, any other source shows once per `COALESCE(work_key, id)` and never next to a search row of the same work. Do not narrow that filter again, or Oracle-added imports vanish from `/api/watchlist` and the search watchlist state.
- Unknown books/comics get a `source='oracle'` row filled by `oracle_actions.lookup_book` (reuses `api_search._search_openlibrary`, exact title match only, runs before the write lock); a failed lookup leaves a bare row. Films/series unknown to the DB get a bare row.
- Eval `evals/test_oracle_actions.py` A1-A7 checks visibility through `get_watchlist`, `/api/watchlist` and `_get_user_state`, not just row counts.
- `dashboard.html` (and its reading-list table) is static: `server._rebuild_dashboard()` rebuilds it in a background thread (one build at a time, ~7 s on oracle, written to a `.tmp` then `os.replace`) after Oracle actions are processed, undo, confirm, `/api/rate`, `/api/interactions` and watchlist DELETE. With `OBS_DB_PATH` set it only runs when `OBS_DASHBOARD_OUT` names the output, so evals never overwrite the real dashboard. Eval A8.
- Evals that import `server.py` start with `import use_project_venv` (`evals/use_project_venv.py`): under a Python without fastapi (Robbedoes's verify runs bare `python3`) they re-exec themselves with `~/Library/Scripts/entertainment-env/bin/python` (override `OBS_VENV_PYTHON`). Add it to any new eval that needs fastapi.

## Oracle sessions (OBS-051)

- Conversations are server-side: `oracle_sessions` plus `oracle_conversations.session_id` (`scripts/oracle_sessions.py`). `/api/ask` takes `{question, session_id?}` and reads the last 4 turns from the DB. The client's old `history` field is accepted and ignored.
- Each prompt carries a data block with what happened to this session's proposed changes (`oracle_actions.session_summary`), so the Oracle can truthfully say what was saved.
- Titles: a Haiku background call names a new session; a rename sets `title_source='user'` and is never overwritten.
- "Save anyway" (`POST /api/oracle/actions/{id}/confirm`) is Waldo's own click, limited to `security review:` rejections with a resolved target. Undo works as usual.
- HTML responses are `Cache-Control: no-cache`: without it Android Chrome kept running a days-old `/ask` that sent no history and drew no action cards, which looked like a dead queue.
- Evals: `evals/test_oracle_sessions.py` (run by `deploy.sh`) and `evals/browser/oracle-sessions.spec.ts`, which writes data, so only against `evals/browser/oracle_local_server.py` with `OBS_ORACLE_LOCAL=1`. Do not use port 8011 locally: the Open Brain tunnel holds it.

## What the Oracle knows (OBS-053)

`scripts/oracle_lookup.py` builds, per question, a list of every seen or rated work (no episodes: their score is the show's, copied), the titles found in the latest message, and recent ratings. `ORACLE_SYSTEM` in `server.py` is static: every database string goes into the `<library-data>` block in the stdin prompt with only `<` and `>` escaped, because `&amp;` would end up in action titles.
`oracle_actions.INFERRED_RATINGS` lists numbers the importers made up (JustWatch like 4.5, Netflix thumbs 4 and 1.5, Pocket Casts 3 for every subscription). The Oracle reports these as words. A real re-rating moves such a row to `source='oracle'` (`RERATE_SQL`), otherwise it would still read as a thumb.
Eval: `evals/test_oracle_lookup.py`.

## In-app ratings and re-imports (OBS-054)

Table `app_ratings` (`scripts/app_ratings.py`) holds ratings set in the app or chat, one row per `media_items.id`, with a real `rated_at`. Imports never write it. Every rating write goes through `app_ratings.set_rating` (chat actions, `/api/rate`, `/api/interactions`). `user_interactions` still carries the current value, and `ingest_films`, `ingest_books`, `ingest_netflix` and `ingest_justwatch` call `app_ratings.reapply` in their own transaction, so an import cannot lose an in-app rating; the export's value is kept in `import_rating`. An in-app rating always wins over an export, even a newer one; to take the export's score, set it again. Undo snapshots cover the table. After a re-import, undo of an older chat action is refused, because the import replaced the rows.
Commands on oracle: `scripts/app_ratings.py differences` lists rated rows with no in-app record that no export explains; `adopt <media_id> ...` records one as in-app; `set <media_id> <0.5 to 5>` sets one to a chosen score.
Imports are safe to run only after a dry run on a DB copy (`OBS_DB_PATH`) with a before and after diff of rated works. Importers: IMDb "TV Episode" is `tv_episode`. JustWatch matches on title, type and year (off by one only when unique) and rebuilds its own rows. Audible compares authors and skips a missing CSV. Netflix's full export (the format `ingest_netflix.py` reads) is requested at https://www.netflix.com/account/getmyinfo. On oracle `goodreads_import.csv` and the JustWatch CSVs in `data/raw/` are dangling symlinks to the Mac, so copy real files there before importing. Evals: `evals/test_app_ratings.py`, `evals/test_importers.py`.

## One rating per work (OBS-054)

View `my_ratings` (`scripts/my_ratings.py`) gives one row per work, and the Dashboard, Oracle, Taste Map, search and detail panel all read it. Winner order: in-app rating, IMDb, Goodreads, any other explicit row. Likes, thumbs and podcast subscriptions (`INFERRED_RATINGS`) are in `signal` with `rating` NULL, so they never enter an average. `conflict` and `export_rating` show where an export disagrees with an explicit rating.
`media_items.work_key` joins the imports of one work on media type, normalised title and year. A row with no year joins only when exactly one year is known for that title. Books and comics with the same title but different authors get an author mark in the key. Episodes have no key. Keys are derived, so undo snapshots leave them out.
`init` replaces the view only when its SQL changed, and in one transaction, because readers must never find it missing. It runs at server startup and in `build_dashboard.py`. `build_brain.py` runs per Taste Map request and only installs it when the view does not exist. `reapply(conn, "imdb")` names the export that was just read: only those rows can end a recorded difference. Eval: `evals/test_my_ratings.py`.

## Measured taste and picks (OBS-054)

`scripts/build_profile.py --draft` measures taste from `my_ratings` (genre, director, author and decade scores against his own average, sample counts, last 12 months) and has Sonnet write the portrait and picks; `--show` prints the draft and `--publish` applies it and rebuilds the dashboard. Numbers on the page always come from the measurement; the model only supplies the words, the clusters (only titles he rated or liked survive) and book genre labels, because only 4 books have genres in the data. Publishing is one transaction: picks keep their id when the work is the same, seen and dismissed works never return, and an unusable generation changes nothing. A day with 10 or more ratings from one source is an import or clean-up, so it does not count as recent. Finished against abandoned shows waits for the new Netflix export. Eval: `evals/test_build_profile.py`.

## Ratings scale (OBS-052)

`user_interactions.rating` and the Oracle's action JSON stay on 0.5 to 5 in half steps; everything Waldo sees is out of ten (stored x 2, doubled before rounding averages). Widgets have ten positions and save position/2. Detail panel and search save through `POST /api/rate`, which uses `oracle_actions.resolve`/`apply` so all imports of a work stay in step and keep their source and date. To the Oracle, a bare number means out of ten and "N stars" means out of five. Eval: `evals/test_ratings_out_of_ten.py`.

## Git & deploy

This directory is its own git repo (`main` branch → `waldo-van-der-code/observatory`).
It is **not** part of a monorepo — always `cd` into this directory before any git operation.

```bash
git push origin main
```

**Personal data is gitignored** — `data/`, `dashboard.html`, `static/map-pieces/*.png` are never committed to the public repo.

## Running locally

```bash
./run.sh --serve          # start server on port 8000, auto-reloads
./run.sh                  # ingest all present data sources + build dashboard
```

Python venv: `~/Library/Scripts/entertainment-env/`
Data: `data/raw/` (gitignored — personal exports go here)
DB: `data/processed/entertainment.db` (SQLite, gitignored)

## Architecture

| File | Role |
|---|---|
| `server.py` | FastAPI: search (TMDB/OpenLibrary), watchlist, ratings, Brain routes, `/api/recs`, `/picks`, `/favicon.ico` |
| `dashboard.html` | Generated static HTML (gitignored — build via `build_dashboard.py`) |
| `brain.html` | Interactive taste map (static, committed — no personal data) |
| `static/picks.html` | Standalone picks/recommendations page (static, committed) |
| `static/nav.js` / `nav.css` | Shared primary nav injected into every page |
| `static/detail.js` / `detail.css` | Shared detail panel (TMDB/OpenLibrary drawer) |
| `static/favicon.ico` | 16×16 gold ✶ on navy, PNG-in-ICO format |
| `scripts/deploy.sh` | One-command deploy with health-check + auto-rollback |
| `scripts/ingest_*.py` | One script per data source — idempotent, safe to re-run |
| `scripts/build_profile.py` | Measures taste, drafts portrait and picks through the `claude` CLI, publishes them together |
| `scripts/build_dashboard.py` | Renders taste profile + ingested data → `dashboard.html` |
| `scripts/build_brain.py` | Builds taste zone graph + item labels for Brain page |
| `config/exemplars.json` | Taste zone → exemplar artists/directors (editable) |
| `config/layout.json` | Brain node positions (editable) |

## Recommendations DB (`recommendations` table)

- 171 rows, all `status = 'pending'` by default (not NULL, not empty string)
- API filter for "not yet actioned": `WHERE status NOT IN ('seen', 'dismissed')` — the field is never NULL in practice
- `confidence` column has mixed scales: rows 37–136 use 0–1 float; rows 137–159 use 0–100 integer. Normalise via: `conf_pct = round(conf * 100) if conf <= 1.0 else round(conf)`
- `potential_issue` may be the literal string `"None — ..."` (LLM artifact). Strip: `if issue.lower().startswith("none"): issue = ""`
- Status values: `pending` (default), `seen`, `dismissed`, `want`. Only `seen` and `dismissed` are hidden from the picks page.
- **Never batch-update status from scripts** — status changes only via user clicks through the UI (`POST /api/recs/{id}`) or via a reviewed Oracle chat action (OBS-050)

## build_dashboard.py notes

- 2600+ line Python f-string template. Use `{{ }}` for literal CSS/JS braces inside the f-string.
- `dashboard.html` is gitignored and always built on oracle — never edit it directly.
- After removing a section (e.g. `#sec-recs` in OBS-041), also remove: the section from `sectionIds` in `initSectionNav()`, the scroll-margin selector list, and any DOMContentLoaded init calls for that section.

## Taste Map — atlas image workflow

`brain.html` renders as a cartographic map: one atlas background image + SVG label overlay
(zone names, artists, films, books — sized by engagement).

**Zone labels** are built from your personal data and populated at runtime by the server.
`brain.html` is committed with no embedded data; it fetches from `/api/brain/zones`.

**Atlas background image** (`static/map-pieces/world-atlas.png`) is gitignored.
Generate it once — see **README → Taste Map** for the ChatGPT prompt and workflow.

**Island images** per zone (optional, `static/map-pieces/*.ZONE_ID.png`) are also gitignored.
Generate with: `python3 scripts/gen_map_prompts.py` then follow the prompts.md instructions.

## AI token policy

**Never call the Anthropic API from scripts.** Claude is reached only through the `claude` CLI on the subscription (`scripts/claude_cli.py`, which never passes an API key).

## API keys

- TMDB: `~/.config/tmdb/api_key` (free — for film/TV search)

## What's gitignored

- `data/` — all personal data (raw exports, processed DB, caches)
- `dashboard.html` — generated, contains personal stats
- `youtube-watch-history/` — personal viewing history
- `static/map-pieces/*.png` — generated atlas + island images (derived from personal data)
- `*-draft.md` — local draft files

## Streaming region

JustWatch / streaming availability defaults to `DE`. Change the string `"DE"` in
`server.py → api_detail()` to your country code.


## Shared Claude–Codex workflow (2026-09-14)

This AGENTS.md is canonical. Claude imports it; do not maintain a second rule copy.
Before work in an independent personal repository, read the workspace AGENTS.md at
`/Users/waldo.vanderhaeghen/Documents/AI-projects-personal/AGENTS.md` if not already loaded.
Also read any intervening area AGENTS.md files relevant to this project. Project rules specialize
workspace rules; documented workspace protection rules remain in force.

For a continuing task, use the shared handoff/resume skills. Maintain `.agent-state/tasks/<task-id>.md`
at the checkout root, outside todos. Record objective, existing ticket, decisions, changed files,
verification results, pending external actions and next step at meaningful milestones.
Only one agent may edit a checkout at a time: stop the outgoing agent and its workers before taking
over. Check the actual diff and branch; never repeat an uncertain external action without checking
its result. An ownership marker is coordination, not a lock enforced on every process.
Neither handover nor a saved checkpoint authorizes new sends, deployments or purchases.
Service access and account routing: `Organization/agent-setup/access.md` under the workspace root.
