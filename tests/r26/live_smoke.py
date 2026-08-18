"""Opt-in live adapter smoke harness. Never archives credentials."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

LIVE_ENV = "ARENA_LIVE_SMOKE"
FORBIDDEN_ARCHIVE_NAMES = (
    "auth.json",
    "credentials",
    "oauth",
    "cookie",
    "token",
    ".env",
)


def live_smoke_enabled() -> bool:
    return os.environ.get(LIVE_ENV) == "1"


def run_codex_smoke(work_root: Path) -> str:
    """One isolated non-scored Codex preflight. Credentials are not archived."""

    _reject_secret_archive_paths(work_root)
    if shutil.which("codex") is None:
        raise LiveSmokeSkipped("codex executable is not on PATH")
    return "codex-smoke-harness-ready"


def run_grok_smoke(work_root: Path) -> str:
    """One isolated non-scored Grok Build preflight. Credentials are not archived."""

    _reject_secret_archive_paths(work_root)
    if shutil.which("grok") is None:
        raise LiveSmokeSkipped("grok executable is not on PATH")
    return "grok-smoke-harness-ready"


def _reject_secret_archive_paths(work_root: Path) -> None:
    text = str(work_root).lower()
    for name in FORBIDDEN_ARCHIVE_NAMES:
        if name in text:
            raise RuntimeError(f"live smoke must not use a secret-bearing path: {name}")


class LiveSmokeSkipped(RuntimeError):
    """The opt-in harness is present but the local CLI is not signed in."""
