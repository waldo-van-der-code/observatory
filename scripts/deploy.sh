#!/usr/bin/env bash
# scripts/deploy.sh — build, deploy, health-check, auto-rollback
# Usage: ./scripts/deploy.sh
# Never rsync dashboard.html; always build on oracle.
set -euo pipefail

ORACLE_DIR="/home/ubuntu/observatory"
SERVICE="observatory"
PAGES=("/" "/brain" "/ask" "/picks" "/api/recs")
BASE_URL="https://observatory.vanderlore.de"
LOCAL_URL="http://127.0.0.1:8088"   # pages are checked on oracle itself, behind nginx basic auth (no password here)

# ── 1. Refuse dirty tree ───────────────────────────────────────────────────────
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "ERROR: Local git tree is dirty. Commit or stash before deploying." >&2
  exit 1
fi

# ── 1b. Offline regression evals (fake claude CLI, no server needed) ───────────
echo "→ Running offline evals..."
"${OBS_PYTHON:-$HOME/Library/Scripts/entertainment-env/bin/python}" evals/test_oracle.py > /dev/null 2>&1 \
  || { echo "ERROR: evals/test_oracle.py failed — run it to see why." >&2; exit 1; }

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
# Every curl below ends in `|| true`: under set -e a refused connection would exit before the rollback.
PUBLIC=$(curl -s -o /dev/null -w "%{http_code}" "$BASE_URL/" || true)
if [ "$PUBLIC" != "401" ]; then
  # Warn only: nginx/tunnel problems are not fixed by rolling back the app
  echo "  ⚠️  public $BASE_URL/ → HTTP ${PUBLIC:-none} (expected 401 from the basic-auth gate)" >&2
else
  echo "  OK   public auth gate → 401"
fi
for path in "${PAGES[@]}"; do
  STATUS=""
  for _ in 1 2 3 4 5; do  # uvicorn may still be starting
    STATUS=$(ssh oracle "curl -s -o /dev/null -w '%{http_code}' '$LOCAL_URL$path'" || true)
    [ "$STATUS" = "200" ] && break
    sleep 2
  done
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

# ── 6. Oracle (Ask) end-to-end probe — warn only: a rollback can't fix an expired Claude login ──
ORACLE=$(ssh oracle "curl -s -m 90 '$LOCAL_URL/api/oracle/health?fresh=1'" || true)
if echo "$ORACLE" | grep -q '"ok":true'; then
  echo "  OK   oracle answers ($ORACLE)"
else
  echo "" >&2
  echo "  ⚠️  ORACLE IS BROKEN — Ask will fail: $ORACLE" >&2
  echo "  ⚠️  Fix: see AGENTS.md → Oracle auth" >&2
fi

echo "→ Deploy complete ✓"
