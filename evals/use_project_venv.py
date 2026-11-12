"""Re-run an eval under the project venv when the current Python lacks its packages (ME-397).

Robbedoes's verify step runs evals with a bare `python3` that has no fastapi, so evals that
import server.py died with ModuleNotFoundError and proved nothing. Import this first:

    import use_project_venv  # noqa: F401

It does nothing when fastapi is importable or when the venv is missing (the eval then fails
on its own import as before, which is the honest result).
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

VENV_PYTHON = Path(os.environ.get("OBS_VENV_PYTHON") or Path.home() / "Library/Scripts/entertainment-env/bin/python")

if (
    importlib.util.find_spec("fastapi") is None
    and VENV_PYTHON.exists()
    and Path(sys.executable).resolve() != VENV_PYTHON.resolve()
    and not os.environ.get("OBS_VENV_REEXEC")
):
    os.environ["OBS_VENV_REEXEC"] = "1"
    os.execv(str(VENV_PYTHON), [str(VENV_PYTHON), *sys.argv])
