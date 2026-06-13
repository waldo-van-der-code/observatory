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
| **TikTok** | Full account data (JSON) | See below |
| **YouTube** | Watch history (JSON) | Google Takeout → YouTube → Watch history *(planned — not yet in pipeline)* |

All files go in `data/raw/`. None of your data is uploaded anywhere.

---

## TikTok watch history

### Getting the export — not obvious

TikTok makes you request a full data export and wait for it to be prepared. The file is not available
immediately and only stays available for download for a few days.

**Steps (as of mid-2026):**
1. Open the TikTok app → Profile → Menu (☰, top right)
2. Settings and privacy → Account → Download your data
3. Select the data to include (everything is fine; we only use Watch History, Liked Videos, and Favorite Videos)
4. Choose file format: **JSON**
5. Tap **Request data**
6. Wait a few days — TikTok will notify you when it's ready
7. Download `user_data_tiktok.json` and place it in `data/raw/`

**Notes:**
- Preparation takes a few days (varies)
- The file remains available for up to 4 days after generation — download it promptly
- The most recent 24–48 hours of some categories may be missing from the export

### What's in it (and what's not)

The export contains a list of videos you watched, liked, and favorited — but **each entry is just a date
and a URL**. There are no titles, no creator names, no categories, nothing but a link. This is a
significant limitation TikTok buries in the spec.

To do anything useful with the data, you need to enrich the videos by fetching their metadata from
TikTok's servers.

### Ingestion

```bash
cp ~/Downloads/user_data_tiktok.json data/raw/user_data_tiktok.json
python3 scripts/ingest_tiktok.py
```

This is fast (~30s for 87k records) and fully idempotent — running it twice produces identical row counts.

Rating signal used: **watch = ★★**, **liked = ★★★★**, **favorited = ★★★★★**.

Searches, share history, and followed hashtags are intentionally ignored.

### Metadata enrichment (OBS-17B)

After ingesting, ~1,740 liked + favorited videos are marked `enrichment_status='pending'`. You can
enrich them with `yt-dlp` to extract titles, descriptions, and hashtags:

```bash
# Test first (20 videos)
python3 scripts/enrich_tiktok.py --limit 20

# Full run (~45–60 min for ~1,740 videos; resumable)
python3 scripts/enrich_tiktok.py

# Rebuild dashboard to see hashtag analysis
python3 scripts/build_dashboard.py
```

**Caveats:**
- Enrichment is best-effort — TikTok can break yt-dlp extractors at any time
- Deleted, private, or region-blocked videos will fail and are tracked as `enrichment_status='failed'`
- Videos are retried up to 3 times; failures after that are not retried
- Rate-limited to ~1 request/1.5s with backoff to avoid blocks

Watch-only videos (85k+) are never enriched — only liked and favorited videos. This keeps
enrichment manageable and focuses on the high-signal content.

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

## Taste Map

The **Brain** page (`brain.html`) renders an interactive cartographic map of your taste zones — a
Voronoi-partitioned world where each region represents a genre cluster, labelled with your most
played artists, watched films, and read books, sized by engagement.

`brain.html` is committed with **no embedded data**. It fetches zone data from `/api/brain/zones`
at runtime, so it renders your own taste once you've run the ingestion pipeline. Clone it, run
the server, and it shows yours.

### Populating the map

After ingesting your data sources, build the Brain zone data:

```bash
python3 scripts/build_brain.py
```

This reads your DB and writes zone data that the server exposes at `/api/brain/zones`.

### Generating the atlas background image

The map renders over a hand-painted atlas background (`static/map-pieces/world-atlas.png`).
This file is gitignored — you generate it once, then it stays on your machine.

**Option A — Composite from 12 zone island images (recommended)**

1. Generate prompts for each zone:

   ```bash
   python3 scripts/gen_map_prompts.py
   # → static/map-pieces/prompts.md
   ```

2. Paste each prompt into **Gemini Imagen 3** (`imagen-3.0-generate-001`) at **1024×1024 PNG**.
   The prompts already contain the style preamble — just paste and generate.

3. Save each image as `static/map-pieces/{ZONE_ID}.png`
   (e.g. `SOUL_JAZZ.png`, `FOLK_SINGER.png`, `DRAMA.png`, …)

4. Optional — remove white backgrounds with `rembg`:

   ```bash
   pip install "rembg[cpu]" pillow
   python3 scripts/process_map_pieces.py
   ```

5. Composite into a single atlas:

   ```bash
   pip install scipy
   python3 scripts/composite_map.py
   # → static/map-pieces/world-map.png
   cp static/map-pieces/world-map.png static/map-pieces/world-atlas.png
   ```

**Option B — Single-image generation (quicker)**

Generate one wide-format atlas in ChatGPT or DALL-E 3 with this prompt:

> Antique fantasy world map. Hand-painted watercolor with fine ink linework, aged parchment
> texture. Top-down view. No text labels, no cartouches, no compass roses. A 3:2 landscape
> image showing a fictional continent divided into distinct climate / terrain regions:
> warm delta river estuary (soul/jazz), enchanted Celtic forest (folk), neon-lit megacity
> (electronic/hip-hop), layered canyon desert (rock), misty fjord coastline (indie/world),
> Gothic nocturnal city (crime/thriller), arthouse lighthouse on stormy headland (arthouse),
> space-elevator orbital ring (sci-fi), cloud-kingdom floating islands (fantasy/comedy),
> war-scarred ancient ruins (history/war), volcanic archipelago (action/adventure), and
> luminous deep-sea reef (animation). Ocean is a muted dark blue-grey (#0c1820).
> Museum-quality 1890s geographical survey plate style.

Save as `static/map-pieces/world-atlas.png` at **2160×1440** (3:2).

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
