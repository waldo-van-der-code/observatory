<!-- project-meta
schema_version: 1
slug: observatory
prefix: ENT
stack: python-html
deploy: github-pages
harness_layers:
  - playwright
registry_managed: true
-->

# Observatory — Standing Instructions

## Ticket prefix
Prefix: ENT
Use `/project-ticket ENT-NN: title` to generate tickets.
Tickets: ~/Documents/AI-projects-personal/todos/ent-nn-slug.md

## Pre-deploy checklist
- [ ] build passes
- [ ] npx playwright test passes

## Harness layers
Layer 2: evals/browser/ (Playwright). Run: `npx playwright test`
Details: evals/README.md

## What this is

Self-hosted personal entertainment dashboard at `Fun!/entertainment/`.
Public name: **Observatory**. GitHub: `waldo-van-der-code/observatory`.
Live (password-protected): `https://waldo.vanderlore.de/culture`

Covers: Spotify streaming history, Goodreads, IMDB, Netflix, JustWatch, Audible.

## Git & deploy

This directory is its own git repo (`main` branch → `waldo-van-der-code/observatory`).
It is **not** the workspace root repo — always `cd` here before any git operation.

```bash
cd '/Users/waldo.vanderhaeghen/Documents/AI-projects-personal/Fun!/entertainment'
git push origin main
```

The live `/culture` page on `waldo.vanderlore.de` is **not** auto-synced from this repo.
It is served from a separate copy in `personal-site/public/culture/`.
After updating `dashboard.html` or `brain.html` here, copy them there and redeploy:

```bash
cp dashboard.html /Users/waldo.vanderhaeghen/Documents/AI-projects-personal/personal-site/public/culture/dashboard.html
cp brain.html     /Users/waldo.vanderhaeghen/Documents/AI-projects-personal/personal-site/public/culture/brain.html
cd /Users/waldo.vanderhaeghen/Documents/AI-projects-personal/personal-site
vercel deploy --prod
curl -s https://waldo.vanderlore.de/culture/dashboard.html | grep "Profile generated"
```

## AI token policy

**Never call the Anthropic API directly** (no `build_profile.py --refresh`). The `anthropic` package is not installed in the venv and API credits cost money.

Instead, **use the current Claude Code session** to generate profile JSON and recommendations in-session, then write them directly to the SQLite DB with a Python script:
1. Export rated history: `python3 -c "import sqlite3,json; ..."` → `/tmp/ent_signal.json`
2. Read the data in the Claude session
3. Generate profile + recs as structured Python dicts
4. Write to DB with inline Python (no SDK needed)
5. Run `python3 scripts/build_dashboard.py` to render

The `build_profile.py` script is kept for reference but should not be called — it requires `ANTHROPIC_API_KEY` and the venv doesn't have the `anthropic` package installed.

## Running locally

```bash
./run.sh --serve          # start server on port 8000, auto-reloads
./run.sh                  # ingest all present data sources + build dashboard
# Do NOT use ./run.sh --refresh — use in-session Claude generation instead (see AI token policy above)
```

Python venv: `/Users/waldo.vanderhaeghen/Library/Scripts/entertainment-env/`
Data: `data/raw/` (gitignored — personal exports)
DB: `data/processed/entertainment.db` (SQLite, gitignored)

## PWA / home screen icon

Icons live in two places — keep them in sync:
- `static/icon-{180,192,512}.png` — served by local FastAPI
- `personal-site/public/static/icon-{180,192,512}.png` — served by Vercel

Regenerate with:
```bash
python3 scripts/gen_icons.py
cp static/icon-*.png /Users/waldo.vanderhaeghen/Documents/AI-projects-personal/personal-site/public/static/
```

## Architecture

| File | Role |
|---|---|
| `server.py` | FastAPI: search (TMDB/OpenLibrary), watchlist, ratings, Brain routes |
| `dashboard.html` | Generated static HTML (gitignored — build via `build_dashboard.py`) |
| `brain.html` | Interactive taste map (static, committed) |
| `scripts/ingest_*.py` | One script per data source — idempotent, safe to re-run |
| `scripts/build_profile.py` | Calls Claude API to generate taste profile JSON |
| `scripts/build_dashboard.py` | Renders taste profile + ingested data → `dashboard.html` |
| `scripts/build_brain.py` | Builds taste zone graph for Brain page |
| `config/exemplars.json` | Taste zone → exemplar artists/directors (editable) |
| `config/layout.json` | Brain node positions (editable) |

## API keys

- TMDB: `~/.config/tmdb/api_key` (free — for film/TV search)
- Anthropic: `ANTHROPIC_API_KEY` env var (for taste profile build)

## What's gitignored

- `data/` — all personal data (raw exports, processed DB, poster cache)
- `dashboard.html` — generated, contains personal stats
- `youtube-watch-history/` — personal viewing history
- `*-draft.md` — local post drafts

## Streaming region

JustWatch / streaming availability defaults to `DE`. Change the string `"DE"` in
`server.py → api_detail()` to your country code.
