# Observatory — Project Instructions

## What this is

Self-hosted personal entertainment dashboard.
Public name: **Observatory**. GitHub: `waldo-van-der-code/observatory`.

Covers: Spotify streaming history, Goodreads, IMDB, Netflix, JustWatch, Audible, TikTok.

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
