"""How Observatory reaches Claude: the `claude` CLI on the subscription, isolated from local settings."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

# Long-lived token from `claude setup-token` (1 year). Without it the CLI falls back to the
# interactive OAuth login in ~/.claude, which expired on oracle and broke the Oracle (OBS-048).
TOKEN_FILE = Path(os.environ.get("OBS_CLAUDE_TOKEN_FILE", Path.home() / ".secrets" / "claude-code-oauth-token"))
ISOLATION_FLAGS = ["--tools", "", "--strict-mcp-config", "--setting-sources", "local",
                   "--disable-slash-commands", "--no-session-persistence"]


def find() -> str | None:
    cli = os.environ.get("OBS_CLAUDE_CLI") or shutil.which("claude") or "/home/ubuntu/.nvm/versions/node/v22.23.2/bin/claude"
    return cli if os.path.isfile(cli) else None


def env() -> dict:
    """The CLI's environment. An API key would take priority over the subscription, so it never gets one."""
    result = dict(os.environ)
    result.pop("ANTHROPIC_API_KEY", None)
    if TOKEN_FILE.is_file():
        token = TOKEN_FILE.read_text().strip()
        if token:
            result["CLAUDE_CODE_OAUTH_TOKEN"] = token
    return result
