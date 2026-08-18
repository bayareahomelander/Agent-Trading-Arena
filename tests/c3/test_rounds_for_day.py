"""C3: two rounds on a trading day; none on a holiday. No clocks."""

from datetime import date, datetime
from pathlib import Path

import pytest

from arena_kernel.calendar import parse_calendar, rounds_for_day
from arena_kernel.schema.round_id import parse_round_id
from arena_kernel.types import EXCHANGE_TIMEZONE_NAME, format_et_timestamp

_REPO = Path(__file__).resolve().parents[2]
CALENDAR_PATH = _REPO / "fixtures" / "golden" / "calendar" / "calendar.json"

REGULAR = date(2026, 11, 2)
EARLY_CLOSE = date(2026, 11, 3)
HOLIDAY = date(2026, 11, 4)
UNLISTED = date(2026, 8, 17)


def _calendar():
    return parse_calendar(CALENDAR_PATH.read_text(encoding="utf-8"))


def test_regular_day_morning_is_1000_to_1015_with_reference_1016() -> None:
    morning, _late = rounds_for_day(_calendar(), REGULAR)
    assert morning.round_id == "2026-11-02-morning"
    assert morning.kind == "morning"
    assert parse_round_id(morning.round_id) == morning.round_id
    assert format_et_timestamp(morning.start) == "2026-11-02T10:00:00-05:00"
    assert format_et_timestamp(morning.deadline) == "2026-11-02T10:15:00-05:00"
    assert format_et_timestamp(morning.reference_minute) == "2026-11-02T10:16:00-05:00"


def test_regular_day_late_is_1530_to_1545_with_reference_1546() -> None:
    _morning, late = rounds_for_day(_calendar(), REGULAR)
    assert late.round_id == "2026-11-02-late"
    assert late.kind == "late"
    assert format_et_timestamp(late.start) == "2026-11-02T15:30:00-05:00"
    assert format_et_timestamp(late.deadline) == "2026-11-02T15:45:00-05:00"
    assert format_et_timestamp(late.reference_minute) == "2026-11-02T15:46:00-05:00"


def test_late_round_shifts_on_early_close() -> None:
    _morning, late = rounds_for_day(_calendar(), EARLY_CLOSE)
    assert late.round_id == "2026-11-03-late"
    assert format_et_timestamp(late.start) == "2026-11-03T12:30:00-05:00"
    assert format_et_timestamp(late.deadline) == "2026-11-03T12:45:00-05:00"
    assert format_et_timestamp(late.reference_minute) == "2026-11-03T12:46:00-05:00"


def test_morning_round_does_not_shift_on_early_close() -> None:
    morning, _late = rounds_for_day(_calendar(), EARLY_CLOSE)
    assert morning.round_id == "2026-11-03-morning"
    assert format_et_timestamp(morning.start) == "2026-11-03T10:00:00-05:00"
    assert format_et_timestamp(morning.deadline) == "2026-11-03T10:15:00-05:00"
    assert format_et_timestamp(morning.reference_minute) == "2026-11-03T10:16:00-05:00"


def test_trading_day_has_morning_then_late() -> None:
    rounds = rounds_for_day(_calendar(), REGULAR)
    assert tuple(item.kind for item in rounds) == ("morning", "late")
    assert len(rounds) == 2


def test_holiday_has_no_rounds() -> None:
    assert rounds_for_day(_calendar(), HOLIDAY) == ()


def test_unlisted_date_has_no_rounds() -> None:
    assert rounds_for_day(_calendar(), UNLISTED) == ()


def test_round_times_are_america_new_york() -> None:
    morning, late = rounds_for_day(_calendar(), REGULAR)
    for instant in (
        morning.start,
        morning.deadline,
        morning.reference_minute,
        late.start,
        late.deadline,
        late.reference_minute,
    ):
        assert instant.tzinfo is not None
        assert instant.tzinfo.key == EXCHANGE_TIMEZONE_NAME  # type: ignore[union-attr]


def test_rounds_for_day_rejects_datetime_in_place_of_date() -> None:
    with pytest.raises(TypeError):
        rounds_for_day(_calendar(), datetime(2026, 11, 2, 10, 0))
