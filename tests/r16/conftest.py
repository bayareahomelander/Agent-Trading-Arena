"""Shared R16 raw process and Grok streaming-json fixtures."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from arena_runtime.process import ProcessFacts


def jsonl(*events: dict[str, object]) -> bytes:
    return b"".join((json.dumps(event) + "\n").encode("utf-8") for event in events)


def facts(
    stdout: bytes,
    *,
    exit_status: int = 0,
    timed_out: bool = False,
) -> ProcessFacts:
    started = datetime(2026, 8, 17, 10, 0, tzinfo=timezone.utc)
    return ProcessFacts(
        argv=("grok", "--single", "prompt"),
        cwd=Path("C:/arena/replica"),
        pid=123,
        started_at=started,
        finished_at=started + timedelta(seconds=1),
        exit_status=exit_status,
        timed_out=timed_out,
        stdout=stdout,
        stderr=b"",
        stdout_truncated=False,
        stderr_truncated=False,
    )
