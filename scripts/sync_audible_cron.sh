#!/usr/bin/env bash
# Daily wrapper for oracle cron. Logs, and alerts via the existing Telegram helper if present.
set -u
DIR="$(cd "$(dirname "$0")/.." && pwd)"
PY="${AUDIBLE_PYTHON:-$HOME/audible-env/bin/python3}"
LOG="$HOME/logs/audible-sync.log"; mkdir -p "$(dirname "$LOG")"
{ echo "== $(TZ=Europe/Berlin date '+%F %T %Z')"; "$PY" "$DIR/scripts/sync_audible.py"; } >>"$LOG" 2>&1
rc=$?
if [ $rc -ne 0 ]; then echo "audible sync failed rc=$rc, see $LOG" >&2; fi
exit $rc
