"""Shared R8 season and replica workspace fixtures."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

FIXTURE = Path(__file__).parent / "fixtures" / "isolation_fixture.py"


def make_season(
    root: Path,
    replica_ids: tuple[str, ...] = ("product-a-1", "product-a-2"),
) -> Path:
    season = root / "season"
    for replica_id in replica_ids:
        workspace = season / "replicas" / replica_id
        (workspace / "state" / "market").mkdir(parents=True)
        (workspace / "agent" / "notes").mkdir(parents=True)
        (workspace / "agent" / "research").mkdir()
        (workspace / "agent" / "tools").mkdir()
        (workspace / "outbox").mkdir()
        (workspace / "RULES.md").write_text("frozen rules\n", encoding="utf-8")
        (workspace / "PROMPT.md").write_text("frozen prompt\n", encoding="utf-8")
        (workspace / "state" / "portfolio.json").write_text(
            '{}\n',
            encoding="utf-8",
        )
    return season.resolve()


def sanitized_host_environment() -> dict[str, str]:
    environment = {
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
        "HOME": "C:/must-not-pass",
        "UNRELATED_SETTING": "must-not-pass",
        "PROVIDER_API_KEY": "must-not-pass",
    }
    for key in ("PATH", "PATHEXT", "SystemRoot", "TEMP", "TMP", "WINDIR"):
        value = os.environ.get(key)
        if value is not None:
            environment[key] = value
    return environment


def argv(*arguments: str) -> tuple[str, ...]:
    return sys.executable, str(FIXTURE), *arguments


def deadline(seconds: float = 5.0) -> datetime:
    return datetime.now(timezone.utc) + timedelta(seconds=seconds)
