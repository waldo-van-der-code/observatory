#!/bin/bash
# Full pipeline: ingest → profile (if --refresh) → dashboard → server
# Usage: ./run.sh [--refresh] [--serve]
#   --serve   start the FastAPI server on port 8000
#   --refresh rebuild the AI taste profile (requires ANTHROPIC_API_KEY)
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"

# Use venv if present, otherwise fall back to system python3
if [ -f "$DIR/.venv/bin/python3" ]; then
  PYTHON="$DIR/.venv/bin/python3"
  UVICORN="$DIR/.venv/bin/uvicorn"
else
  PYTHON="python3"
  UVICORN="uvicorn"
fi

if [[ "$1" == "--serve" ]]; then
  echo "Starting Observatory → http://localhost:8000"
  cd "$DIR" && "$UVICORN" server:app --reload
  exit 0
fi

echo "→ Ingesting books (Goodreads)…"
"$PYTHON" "$DIR/scripts/ingest_books.py"

[ -f "$DIR/data/raw/imdb_ratings.csv" ] && {
  echo "→ Ingesting films (IMDB)…"
  "$PYTHON" "$DIR/scripts/ingest_films.py"
}

[ -f "$DIR/data/raw/netflix_viewing.csv" ] && {
  echo "→ Ingesting Netflix…"
  "$PYTHON" "$DIR/scripts/ingest_netflix.py"
}

[ -f "$DIR/data/raw/justwatch_seen.csv" ] || [ -f "$DIR/data/raw/justwatch_liked.csv" ] && {
  echo "→ Ingesting JustWatch…"
  "$PYTHON" "$DIR/scripts/ingest_justwatch.py"
}

ls "$DIR"/data/raw/spotify_streaming_audio_*.json &>/dev/null && {
  echo "→ Ingesting Spotify…"
  "$PYTHON" "$DIR/scripts/ingest_spotify.py"
}

[ -f "$DIR/data/raw/audible_extra.json" ] && {
  echo "→ Ingesting Audible…"
  "$PYTHON" "$DIR/scripts/ingest_audible.py"
}

[ -f "$DIR/youtube-watch-history/watch-history.md" ] && {
  echo "→ Ingesting YouTube watch history…"
  "$PYTHON" "$DIR/scripts/ingest_youtube.py"
}

if [[ "$1" == "--refresh" ]]; then
  echo "→ Building AI taste profile (requires ANTHROPIC_API_KEY)…"
  "$PYTHON" "$DIR/scripts/build_profile.py" --refresh
fi

echo "→ Building dashboard…"
"$PYTHON" "$DIR/scripts/build_dashboard.py"
echo "Done → $DIR/dashboard.html"
echo "Run './run.sh --serve' to start the server."
