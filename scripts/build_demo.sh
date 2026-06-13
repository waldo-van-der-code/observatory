#!/usr/bin/env bash
# Build static demo files for GitHub Pages (docs/ folder on main branch).
# Run from the repo root: bash scripts/build_demo.sh
set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "=== Building Observatory demo ==="

# 1. Fixture data
python3 scripts/load_fixtures.py --reset

# 2. Zone graph
python3 scripts/build_brain.py

# 3. Dashboard HTML
python3 scripts/build_dashboard.py

# 4. Bake dashboard → docs/index.html and brain.html → docs/brain.html
python3 scripts/bake_demo.py

# 5. Copy static assets
mkdir -p docs/static/map-pieces
cp static/manifest.json docs/static/ 2>/dev/null || true
cp static/icon-*.png    docs/static/ 2>/dev/null || true
cp static/map-pieces/*.png docs/static/map-pieces/ 2>/dev/null || true

# 6. Copy demo search results
cp data/fixtures/demo_results.json docs/demo_results.json

echo ""
echo "=== Demo built in docs/ ==="
echo "Preview locally:"
echo "  python3 -m http.server 8080 --directory docs"
echo "  → http://localhost:8080/"
