#!/bin/bash
# Full pipeline: ingest → profile (if --refresh) → dashboard → server
# Usage: ./run.sh [--refresh] [--serve]
#   --serve  start the FastAPI server on port 8000 (instead of pipeline)
set -e
PYTHON=/Users/waldo.vanderhaeghen/Library/Scripts/watcher-env/bin/python3
SERVER_PYTHON=/Users/waldo.vanderhaeghen/Library/Scripts/entertainment-env/bin/python3
DIR="$(cd "$(dirname "$0")" && pwd)"

if [[ "$1" == "--serve" ]]; then
  echo "Starting entertainment server → http://localhost:8000"
  cd "$DIR" && /Users/waldo.vanderhaeghen/Library/Scripts/entertainment-env/bin/uvicorn server:app --reload
  exit 0
fi

$PYTHON "$DIR/scripts/ingest_books.py"
[ -f "$DIR/data/raw/imdb_ratings.csv" ] && $PYTHON "$DIR/scripts/ingest_films.py"
[ -f "$DIR/data/raw/netflix_viewing.csv" ] && $PYTHON "$DIR/scripts/ingest_netflix.py"

if [[ "$1" == "--refresh" ]]; then
  echo "Note: build_profile.py requires ANTHROPIC_API_KEY or re-run via Claude Code."
  $PYTHON "$DIR/scripts/build_profile.py" --refresh
fi

$PYTHON "$DIR/scripts/build_dashboard.py"
echo "Done → $DIR/dashboard.html"
