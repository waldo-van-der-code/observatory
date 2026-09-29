#!/usr/bin/env bash
# scripts/deploy.sh — build, deploy, health-check, auto-rollback
# Usage: ./scripts/deploy.sh
# Never rsync dashboard.html; always build on oracle.
set -euo pipefail

ORACLE_DIR="/home/ubuntu/observatory"
SERVICE="observatory"
# Core pages always checked; /picks and /api/recs added after P3b
PAGES=("/" "/brain" "/ask")
BASE_URL="https://observatory.vanderlore.de"
AUTH="waldo:odlaw"

# ── 1. Refuse dirty tree ───────────────────────────────────────────────────────
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "ERROR: Local git tree is dirty. Commit or stash before deploying." >&2
  exit 1
fi

# ── 2. Push ────────────────────────────────────────────────────────────────────
echo "→ Pushing to GitHub..."
git push origin main

# ── 3. Oracle: save rollback ref, pull, build, restart ────────────────────────
echo "→ Deploying on oracle..."
ssh oracle "bash -s" << 'REMOTE'
set -euo pipefail
cd /home/ubuntu/observatory

PREV=$(git rev-parse HEAD)
echo "  Rollback ref: $PREV"
echo "$PREV" > /tmp/obs_rollback_ref

# Pull
git pull origin main

# Back up dashboard
if [ -f dashboard.html ]; then
  cp dashboard.html dashboard.html.bak
  echo "  Backed up dashboard.html"
fi

# Build
echo "  Building dashboard..."
.venv/bin/python scripts/build_dashboard.py
echo "  Build OK ($(wc -c < dashboard.html) bytes)"

# Restart service
sudo systemctl restart observatory
sleep 2
if ! sudo systemctl is-active --quiet observatory; then
  echo "ERROR: Service failed to start" >&2
  exit 1
fi
echo "  Service restarted OK"
REMOTE

# ── 4. Health checks ──────────────────────────────────────────────────────────
echo "→ Health-checking live pages..."
ALL_OK=true
for path in "${PAGES[@]}"; do
  STATUS=$(curl -s -o /dev/null -w "%{http_code}" -u "$AUTH" "$BASE_URL$path")
  if [ "$STATUS" != "200" ]; then
    echo "  FAIL $path → HTTP $STATUS" >&2
    ALL_OK=false
  else
    echo "  OK   $path → $STATUS"
  fi
done

# ── 5. Auto-rollback on failure ───────────────────────────────────────────────
if [ "$ALL_OK" = "false" ]; then
  echo "→ HEALTH CHECK FAILED — rolling back..." >&2
  ssh oracle "bash -s" << 'ROLLBACK'
set -euo pipefail
cd /home/ubuntu/observatory
PREV=$(cat /tmp/obs_rollback_ref 2>/dev/null || echo "")
if [ -z "$PREV" ]; then
  echo "ERROR: No rollback ref found" >&2
  exit 1
fi
echo "  Rolling back to $PREV"
git checkout "$PREV" -- .
if [ -f dashboard.html.bak ]; then
  cp dashboard.html.bak dashboard.html
  echo "  Restored dashboard.html from backup"
fi
sudo systemctl restart observatory
sleep 2
echo "  Rollback complete"
ROLLBACK
  echo "→ Rollback complete. Deploy FAILED." >&2
  exit 1
fi

echo "→ Deploy complete ✓"
