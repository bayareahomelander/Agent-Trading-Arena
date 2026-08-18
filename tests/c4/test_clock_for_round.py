"""C4: Clock from a scheduled round. No vendor, no workspace writes."""

from datetime import date, datetime
from pathlib import Path

import pytest

from arena_kernel.calendar import (
    ScheduledRound,
    clock_for_round,
    parse_calendar,
    rounds_for_day,
)
from arena_kernel.schema.clock import clock_to_dict, dump_clock, parse_clock
from arena_kernel.schema.errors import SchemaError
from arena_kernel.types import EXCHANGE_TIMEZONE_NAME

_REPO = Path(__file__).resolve().parents[2]
CALENDAR_PATH = _REPO / "fixtures" / "golden" / "calendar" / "calendar.json"
D13_MORNING_CLOCK = (
    _REPO
    / "fixtures"
    / "golden"
    / "tape"
    / "rounds"
    / "2026-08-17-morning"
    / "clock.json"
)
REGULAR = date(2026, 11, 2)


def _morning() -> ScheduledRound:
    calendar = parse_calendar(CALENDAR_PATH.read_text(encoding="utf-8"))
    morning, _late = rounds_for_day(calendar, REGULAR)
    return morning


def test_dump_then_parse_equals_constructed_clock() -> None:
    scheduled = _morning()
    clock = clock_for_round(scheduled, exchange_timestamp=scheduled.start)
    assert parse_clock(dump_clock(clock)) == clock


def test_timezone_is_america_new_york() -> None:
    scheduled = _morning()
    clock = clock_for_round(scheduled, exchange_timestamp=scheduled.start)
    assert clock.timezone == EXCHANGE_TIMEZONE_NAME


def test_deadline_is_after_start() -> None:
    scheduled = _morning()
    clock = clock_for_round(scheduled, exchange_timestamp=scheduled.start)
    assert clock.deadline > clock.round_start


def test_c3_and_c4_morning_matches_d13_clock_fields() -> None:
    calendar = parse_calendar(
        {
            "schema_version": "1",
            "entries": [
                {
                    "date": "2026-08-17",
                    "kind": "regular",
                    "scheduled_close": "16:00",
                }
            ],
        }
    )
    morning, _late = rounds_for_day(calendar, date(2026, 8, 17))
    clock = clock_for_round(morning, exchange_timestamp=morning.start)
    expected = parse_clock(D13_MORNING_CLOCK.read_text(encoding="utf-8"))
    assert clock_to_dict(clock) == clock_to_dict(expected)
    assert clock.schema_version == expected.schema_version
    assert clock.exchange_timestamp == expected.exchange_timestamp
    assert clock.timezone == expected.timezone
    assert clock.session_status == expected.session_status
    assert clock.round_id == expected.round_id
    assert clock.round_start == expected.round_start
    assert clock.deadline == expected.deadline


def test_exchange_timestamp_is_caller_supplied() -> None:
    scheduled = _morning()
    clock = clock_for_round(scheduled, exchange_timestamp=scheduled.deadline)
    assert clock.exchange_timestamp == scheduled.deadline
    assert clock.round_start == scheduled.start
    assert clock.exchange_timestamp != clock.round_start


def test_unknown_session_status_fails_with_field_path() -> None:
    scheduled = _morning()
    with pytest.raises(SchemaError) as exc:
        clock_for_round(
            scheduled,
            exchange_timestamp=scheduled.start,
            session_status="halted",
        )
    assert exc.value.path == "session_status"


def test_naive_exchange_timestamp_fails_with_field_path() -> None:
    scheduled = _morning()
    with pytest.raises(SchemaError) as exc:
        clock_for_round(
            scheduled,
            exchange_timestamp=datetime(2026, 11, 2, 10, 0),
        )
    assert exc.value.path == "exchange_timestamp"


def test_deadline_not_after_start_fails_with_field_path() -> None:
    scheduled = _morning()
    broken = ScheduledRound(
        round_id=scheduled.round_id,
        kind=scheduled.kind,
        start=scheduled.start,
        deadline=scheduled.start,
        reference_minute=scheduled.reference_minute,
    )
    with pytest.raises(SchemaError) as exc:
        clock_for_round(broken, exchange_timestamp=scheduled.start)
    assert exc.value.path == "deadline"


def test_default_session_status_is_open() -> None:
    scheduled = _morning()
    clock = clock_for_round(scheduled, exchange_timestamp=scheduled.start)
    assert clock.session_status == "open"
