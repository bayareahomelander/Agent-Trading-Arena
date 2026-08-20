"""US-session calendar.

C1 records locked terms. C2 parses a frozen calendar file. C3 computes
round times from a calendar day. C4 builds a Clock from a scheduled
round.

Holidays live here. Do not fetch bars or talk to a vendor.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any, Final, Mapping

from arena_kernel.schema._parse import (
    SCHEMA_VERSION,
    as_mapping,
    join_path,
    require_list,
    require_object,
    require_schema_version,
    require_str,
)
from arena_kernel.schema.clock import SESSION_STATUSES, Clock
from arena_kernel.schema.errors import SchemaError
from arena_kernel.schema.round_id import parse_round_id
from arena_kernel.types import (
    EXCHANGE_TIMEZONE_NAME,
    EXCHANGE_TZ,
    format_et_timestamp,
    parse_et_timestamp,
)

CALENDAR_KINDS: Final[tuple[str, ...]] = ("regular", "early_close", "holiday")
SESSION_KINDS: Final[frozenset[str]] = frozenset({"regular", "early_close"})

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_HHMM = re.compile(r"^(\d{2}):(\d{2})$")
_TOP_REQUIRED: Final[tuple[str, ...]] = ("schema_version", "entries")
_ENTRY_REQUIRED: Final[tuple[str, ...]] = ("date", "kind")


@dataclass(frozen=True)
class CalendarEntry:
    date: date
    kind: str
    scheduled_close: time | None


@dataclass(frozen=True)
class Calendar:
    schema_version: str
    entries: tuple[CalendarEntry, ...]


@dataclass(frozen=True)
class ScheduledRound:
    round_id: str
    kind: str
    start: datetime
    deadline: datetime
    reference_minute: datetime


def parse_calendar(data: Mapping[str, Any] | str | bytes) -> Calendar:
    """Parse a frozen calendar file. Unlisted dates are not trading days."""
    payload = as_mapping(data)
    require_object(payload, required=_TOP_REQUIRED)
    raw_entries = require_list(payload, "entries")
    entries: list[CalendarEntry] = []
    seen: set[date] = set()
    for index, item in enumerate(raw_entries):
        path = join_path("entries", str(index))
        entries.append(_parse_entry(item, path=path, seen=seen))
    return Calendar(
        schema_version=require_schema_version(payload),
        entries=tuple(entries),
    )


def is_trading_day(calendar: Calendar, day: date) -> bool:
    """True only for a listed regular or early-close session."""
    entry = _entry_on(calendar, day)
    return entry is not None and entry.kind in SESSION_KINDS


def scheduled_close(calendar: Calendar, day: date) -> time | None:
    """Official session end in ET, or None when there is no session."""
    entry = _entry_on(calendar, day)
    if entry is None:
        return None
    return entry.scheduled_close


def rounds_for_day(calendar: Calendar, day: date) -> tuple[ScheduledRound, ...]:
    """Morning then late on a trading day. Empty on holidays and unlisted dates."""
    if not is_trading_day(calendar, day):
        return ()
    close = scheduled_close(calendar, day)
    if close is None:
        return ()
    return (_morning_round(day), _late_round(day, close))


def clock_for_round(
    scheduled: ScheduledRound,
    *,
    exchange_timestamp: datetime,
    session_status: str = "open",
) -> Clock:
    """Build a D3 Clock from a scheduled round. Does not write files."""
    if session_status not in SESSION_STATUSES:
        raise SchemaError(
            "session_status",
            "must be pre_open, open, or closed",
        )
    clock = Clock(
        schema_version=SCHEMA_VERSION,
        exchange_timestamp=_clock_timestamp(
            exchange_timestamp, path="exchange_timestamp"
        ),
        timezone=EXCHANGE_TIMEZONE_NAME,
        session_status=session_status,
        round_id=parse_round_id(scheduled.round_id),
        round_start=_clock_timestamp(scheduled.start, path="round_start"),
        deadline=_clock_timestamp(scheduled.deadline, path="deadline"),
    )
    if clock.deadline <= clock.round_start:
        raise SchemaError("deadline", "must be after round_start")
    return clock


def _clock_timestamp(value: datetime, *, path: str) -> datetime:
    try:
        return parse_et_timestamp(format_et_timestamp(value))
    except (TypeError, ValueError) as exc:
        raise SchemaError(path, str(exc)) from exc


def _morning_round(day: date) -> ScheduledRound:
    start = _at(day, time(10, 0))
    deadline = _at(day, time(10, 15))
    return ScheduledRound(
        round_id=parse_round_id(f"{day.isoformat()}-morning"),
        kind="morning",
        start=start,
        deadline=deadline,
        reference_minute=deadline + timedelta(minutes=1),
    )


def _late_round(day: date, close: time) -> ScheduledRound:
    close_dt = _at(day, close)
    start = close_dt - timedelta(minutes=30)
    deadline = close_dt - timedelta(minutes=15)
    return ScheduledRound(
        round_id=parse_round_id(f"{day.isoformat()}-late"),
        kind="late",
        start=start,
        deadline=deadline,
        reference_minute=deadline + timedelta(minutes=1),
    )


def _at(day: date, clock: time) -> datetime:
    return datetime.combine(day, clock, tzinfo=EXCHANGE_TZ)


def _entry_on(calendar: Calendar, day: date) -> CalendarEntry | None:
    if type(day) is not date:
        raise TypeError("expected a datetime.date")
    for entry in calendar.entries:
        if entry.date == day:
            return entry
    return None


def _parse_entry(item: object, *, path: str, seen: set[date]) -> CalendarEntry:
    if not isinstance(item, dict):
        raise SchemaError(path, "expected an object")
    require_object(
        item,
        required=_ENTRY_REQUIRED,
        optional=("scheduled_close",),
        path=path,
    )
    kind = require_str(item, "kind", path=path)
    if kind not in CALENDAR_KINDS:
        raise SchemaError(
            join_path(path, "kind"),
            "must be regular, early_close, or holiday",
        )
    day = _parse_entry_date(item["date"], path=join_path(path, "date"))
    if day in seen:
        raise SchemaError(join_path(path, "date"), "duplicate date")
    seen.add(day)
    close_path = join_path(path, "scheduled_close")
    if kind == "holiday":
        if "scheduled_close" in item:
            raise SchemaError(close_path, "holiday must not have a close time")
        return CalendarEntry(date=day, kind=kind, scheduled_close=None)
    if "scheduled_close" not in item:
        raise SchemaError(close_path, "missing")
    return CalendarEntry(
        date=day,
        kind=kind,
        scheduled_close=_parse_hhmm(item["scheduled_close"], path=close_path),
    )


def _parse_entry_date(value: object, *, path: str) -> date:
    if not isinstance(value, str):
        raise SchemaError(path, "expected YYYY-MM-DD")
    if _DATE.fullmatch(value) is None:
        raise SchemaError(path, "must be YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise SchemaError(path, f"invalid calendar date {value!r}") from exc


def _parse_hhmm(value: object, *, path: str) -> time:
    if not isinstance(value, str):
        raise SchemaError(path, "expected HH:MM")
    match = _HHMM.fullmatch(value)
    if match is None:
        raise SchemaError(path, "must be HH:MM")
    hour = int(match.group(1))
    minute = int(match.group(2))
    if hour > 23 or minute > 59:
        raise SchemaError(path, "must be HH:MM")
    return time(hour, minute)
