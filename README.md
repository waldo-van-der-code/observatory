# Observatory

A self-hosted personal entertainment dashboard that unifies your entire taste history — films, TV, books, and music — into a single searchable interface with an AI-generated taste profile.

No accounts. No cloud. Your data stays on your machine.

---

## What it does

- **Unified stats** — books read (Goodreads), films & TV rated (IMDB, JustWatch, Netflix), music played (Spotify GDPR export) all in one place
- **Taste profile** — AI-generated genre fingerprints, rating distributions, top directors, listening stats by year
- **Brain** — an interactive taste map that clusters your consumption into zones (Soul & Jazz, Arthouse, Hard Sci-Fi, etc.) and visualises how they connect
- **Picks** — AI-powered recommendations based on your history, with confidence scores and friction notes ("you usually bounce off slow openers")
- **Search** — search films, TV shows, and books via TMDB and OpenLibrary; add to watchlist; rate inline
- **Detail panel** — cast, streaming availability in your country (JustWatch), related titles

---

## Data sources

Observatory ingests exports you download yourself from the original services:

| Source | What you export | Where to get it |
|--------|----------------|-----------------|
| **Spotify** | Extended streaming history (JSON) | Account → Privacy → Request data → Extended streaming history |
| **Goodreads** | Library export (CSV) | Account → Import/Export |
| **IMDB** | Ratings export (CSV) | Your ratings → … → Export |
| **Netflix** | Viewing activity (CSV) | Account → Privacy → Download your data |
| **JustWatch** | Liked / seen lists (CSV) | Profile → Export (seen list + liked list) |
| **Audible** | Purchase/history JSON | Manual export or `audible_extra.json` |
| **YouTube** | Watch history (JSON) | Google Takeout → YouTube → Watch history *(planned — not yet in pipeline)* |

All files go in `data/raw/`. None of your data is uploaded anywhere.

---

## Prerequisites

- Python 3.10+
- [TMDB API key](https://www.themoviedb.org/settings/api) (free) — for film/TV search and details
- [Anthropic API key](https://console.anthropic.com/) — for the AI taste profile and recommendations (one-time build step)

---

## Setup

```bash
git clone https://github.com/waldo-van-der-code/observatory.git
cd observatory
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

Store your API keys:

```bash
mkdir -p ~/.config/tmdb
echo "YOUR_TMDB_KEY" > ~/.config/tmdb/api_key

export ANTHROPIC_API_KEY=sk-ant-...  # or add to .env
```

Add your data exports to `data/raw/`, then run the pipeline:

```bash
# Ingest all data sources present in data/raw/
python3 scripts/ingest_books.py                  # Goodreads CSV
python3 scripts/ingest_films.py                  # IMDB ratings CSV
python3 scripts/ingest_netflix.py                # Netflix viewing CSV
python3 scripts/ingest_justwatch.py              # JustWatch seen/liked CSVs
python3 scripts/ingest_spotify.py                # Spotify extended history JSON(s)
python3 scripts/ingest_audible.py                # Audible JSON (optional)

# Build AI taste profile (calls Anthropic API — runs once, result cached)
python3 scripts/build_profile.py

# Generate the dashboard HTML
python3 scripts/build_dashboard.py

# Start the server
uvicorn server:app --reload
# → http://localhost:8000
```

Or use the convenience script (automatically skips sources whose files are absent):

```bash
./run.sh             # ingest everything present + build dashboard
./run.sh --refresh   # same + rebuild AI taste profile
./run.sh --serve     # start server only (dashboard already built)
```

---

## Add to phone home screen

The dashboard is a PWA. On iOS: open in Safari → Share → Add to Home Screen.
On Android: open in Chrome → … → Add to Home Screen.

---

## Project structure

```
.
├── server.py              # FastAPI server (search, watchlist, ratings)
├── dashboard.html         # Generated dashboard (gitignored — build it yourself)
├── brain.html             # Interactive taste map
├── scripts/
│   ├── ingest_*.py        # Data ingestion per source
│   ├── build_profile.py   # AI taste profile generator
│   ├── build_dashboard.py # Static HTML generator
│   ├── build_brain.py     # Taste zone builder
│   ├── api_search.py      # TMDB + OpenLibrary search
│   ├── db.py              # SQLite helpers
│   └── gen_icons.py       # PWA icon generator
├── config/
│   ├── exemplars.json     # Taste zone → exemplar artists/directors
│   ├── layout.json        # Brain node positions
│   └── weights.json       # Taste zone weights
├── static/
│   ├── manifest.json      # PWA manifest
│   └── icon-*.png         # Home screen icons
├── data/
│   ├── raw/               # Your exports go here (gitignored)
│   ├── processed/         # Ingested SQLite + JSON (gitignored)
│   └── cache/             # TMDB poster cache (gitignored)
└── requirements.txt
```

---

## Tech stack

- **Backend**: FastAPI + uvicorn
- **Frontend**: vanilla HTML/CSS/JS (no build step)
- **Storage**: SQLite (watchlist, ratings, ingested media)
- **AI**: Claude (Anthropic) for taste profiling and recommendations
- **APIs**: TMDB (films/TV), OpenLibrary (books)

---

## Limitations

- The AI profile build requires an Anthropic API key and costs roughly $0.05–0.20 per run depending on library size
- TMDB search covers films and TV only; book search uses OpenLibrary
- Streaming availability is fetched live from JustWatch via TMDB — DE region by default (change `DE` in `server.py` → `api_detail`)

---

## License

MIT
