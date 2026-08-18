"""Shared R7 launch helpers."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

FIXTURE = Path(__file__).parent / "fixtures" / "process_fixture.py"


def argv(*arguments: str) -> tuple[str, ...]:
    return sys.executable, str(FIXTURE), *arguments


def deadline(seconds: float = 5.0) -> datetime:
    return datetime.now(timezone.utc) + timedelta(seconds=seconds)


def sanitized_environment() -> dict[str, str]:
    environment = {
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
    }
    for key in ("PATH", "SystemRoot", "TEMP", "TMP"):
        value = os.environ.get(key)
        if value is not None:
            environment[key] = value
    return environment
