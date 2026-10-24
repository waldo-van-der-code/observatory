"""Regression OBS-048: the Oracle's Claude login on oracle expired and Ask returned an empty
"Claude CLI error (rc=1): " because the CLI prints auth failures to stdout, not stderr.
Nothing noticed for weeks: no health probe existed and the deploy check only fetched /ask.

Runs offline against fake `claude` binaries (no server, no login, no subscription usage):
    ~/Library/Scripts/entertainment-env/bin/python evals/test_oracle.py
"""

from __future__ import annotations

import os
import stat
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="obs-oracle-eval-"))
TOKEN_FILE = TMP / "claude-code-oauth-token"
os.environ["OBS_CLAUDE_TOKEN_FILE"] = str(TOKEN_FILE)
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402

client = TestClient(server.app)
failures = 0


def fake_cli(name: str, body: str) -> str:
    p = TMP / name
    p.write_text("#!/bin/sh\ncat > /dev/null\n" + body + "\n")
    p.chmod(p.stat().st_mode | stat.S_IXUSR)
    return str(p)


EXPIRED = fake_cli("claude-expired", 'echo "Failed to authenticate: OAuth session expired and could not be refreshed"; exit 1')
HEALTHY = fake_cli("claude-ok", 'echo ok')
NEEDS_TOKEN = fake_cli("claude-token", '[ "$CLAUDE_CODE_OAUTH_TOKEN" = "test-token" ] && echo ok || { echo "Invalid API key · Please run /login"; exit 1; }')


def check(label: str, cond: bool, info: object = "") -> None:
    global failures
    print(f"{'✅' if cond else '❌'} {label}" + ("" if cond else f" — {info}"))
    failures += 0 if cond else 1


def use(cli: str | None) -> None:
    os.environ["OBS_CLAUDE_CLI"] = cli or str(TMP / "does-not-exist")
    server._oracle_health_ok_at = 0.0


# 1. Expired login: health goes red, Ask names the cause instead of an empty error
use(EXPIRED)
r = client.get("/api/oracle/health")
check("expired login → /api/oracle/health 503", r.status_code == 503, r.status_code)
check("expired login → health error names the expired login + fix", "expired" in r.text and "setup-token" in r.text, r.text)
r = client.post("/api/ask", json={"question": "anything good tonight?"})
check("expired login → /api/ask 502 with the CLI's stdout message", r.status_code == 502 and "authenticate" in r.json().get("detail", ""), r.text)

# 2. Healthy CLI: 200, then served from cache without re-running the CLI
use(HEALTHY)
r = client.get("/api/oracle/health")
check("healthy CLI → 200 ok", r.status_code == 200 and r.json().get("ok") is True and r.json().get("cached") is False, r.text)
use(EXPIRED)
server._oracle_health_ok_at = time.time()
r = client.get("/api/oracle/health")
check("success is cached (no CLI call within TTL)", r.status_code == 200 and r.json().get("cached") is True, r.text)
r = client.get("/api/oracle/health?fresh=1")
check("fresh=1 bypasses the cache", r.status_code == 503, r.text)

# 3. Long-lived token file is passed to the CLI as CLAUDE_CODE_OAUTH_TOKEN
use(NEEDS_TOKEN)
r = client.get("/api/oracle/health")
check("no token file → CLI fails → 503", r.status_code == 503, r.text)
TOKEN_FILE.write_text("test-token\n")
use(NEEDS_TOKEN)
r = client.get("/api/oracle/health")
check("token file → CLAUDE_CODE_OAUTH_TOKEN reaches CLI → 200", r.status_code == 200, r.text)
check("token age reported", r.json().get("token_age_days") == 0, r.text)

# 4. Token nearing its 1-year expiry goes red a month early
old = time.time() - 340 * 86400
os.utime(TOKEN_FILE, (old, old))
use(HEALTHY)
r = client.get("/api/oracle/health")
check("340-day-old token → 503 'expires soon'", r.status_code == 503 and "expires soon" in r.text, r.text)
TOKEN_FILE.unlink()

# 5. CLI missing
use(None)
r = client.get("/api/oracle/health")
check("missing CLI → 503", r.status_code == 503 and "not found" in r.text, r.text)

print(f"\n{'All checks passed.' if not failures else f'{failures} check(s) failed.'}")
sys.exit(1 if failures else 0)
