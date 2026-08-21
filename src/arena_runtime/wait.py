"""Blocking wait for one aware instant. Not a scheduler."""

from __future__ import annotations

from datetime import datetime
from time import sleep as _sleep
from typing import Callable, Final

MAX_SLEEP_SECONDS: Final[float] = 1.0


def wait_until(
    target: datetime,
    *,
    clock: Callable[[], datetime] = lambda: datetime.now().astimezone(),
    sleep: Callable[[float], None] = _sleep,
) -> None:
    """Block in bounded intervals until an aware ``target`` is reached."""

    target = _aware(target, "target")
    while True:
        remaining = (target - _aware(clock(), "clock")).total_seconds()
        if remaining <= 0:
            return
        sleep(min(remaining, MAX_SLEEP_SECONDS))


def _aware(value: datetime, name: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError(f"{name} must be timezone-aware")
    return value
