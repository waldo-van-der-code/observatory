# Observatory — Project Instructions

## What this is

Self-hosted personal entertainment dashboard.
Public name: **Observatory**. GitHub: `waldo-van-der-code/observatory`.

Covers: Spotify streaming history, Goodreads, IMDB, Netflix, JustWatch, Audible, TikTok.

## Oracle deployment (live)

- URL: **https://observatory.vanderlore.de** — HTTP basic auth (user: waldo)
- Host: oracle (`/home/ubuntu/observatory/`), systemd service `observatory.service`
- Port: 8088 (proxied by nginx)
- To redeploy after code changes: `ssh oracle 'cd /home/ubuntu/observatory && git pull && sudo systemctl restart observatory'`
- To sync updated data/dashboard: `rsync -avz data/processed/entertainment.db data/processed/brain_data.json dashboard.html oracle:/home/ubuntu/observatory/data/processed/` and `rsync dashboard.html oracle:/home/ubuntu/observatory/`

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
| `server.py` | FastAPI: search (TMDB/OpenLibrary), watchlist, ratings, Brain routes |
| `dashboard.html` | Generated static HTML (gitignored — build via `build_dashboard.py`) |
| `brain.html` | Interactive taste map (static, committed — no personal data) |
| `scripts/ingest_*.py` | One script per data source — idempotent, safe to re-run |
| `scripts/build_profile.py` | Builds taste profile JSON via Claude API |
| `scripts/build_dashboard.py` | Renders taste profile + ingested data → `dashboard.html` |
| `scripts/build_brain.py` | Builds taste zone graph + item labels for Brain page |
| `scripts/gen_map_prompts.py` | Generates Imagen 3 prompts → `static/map-pieces/prompts.md` |
| `scripts/enrich_tiktok.py` | Enriches TikTok liked/favorited videos via yt-dlp |
| `scripts/enrich_youtube.py` | YouTube topic tagging from watch history |
| `config/exemplars.json` | Taste zone → exemplar artists/directors (editable) |
| `config/layout.json` | Brain node positions (editable) |

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

**Never call the Anthropic API from scripts directly.** Use the Claude Code session instead:
1. Export rated history → `/tmp/ent_signal.json`
2. Read data in the session
3. Generate profile + recs as structured Python dicts
4. Write to DB with inline Python (no SDK needed)
5. Run `python3 scripts/build_dashboard.py` to render

## API keys

- TMDB: `~/.config/tmdb/api_key` (free — for film/TV search)
- Anthropic: `ANTHROPIC_API_KEY` env var (for taste profile build)

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
