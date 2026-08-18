"""C2: frozen calendar file. Unlisted dates are not trading days."""

from datetime import date, time
from pathlib import Path

import pytest

from arena_kernel.calendar import (
    is_trading_day,
    parse_calendar,
    scheduled_close,
)
from arena_kernel.schema.errors import SchemaError

_REPO = Path(__file__).resolve().parents[2]
CALENDAR_PATH = _REPO / "fixtures" / "golden" / "calendar" / "calendar.json"

REGULAR = date(2026, 11, 2)
EARLY_CLOSE = date(2026, 11, 3)
HOLIDAY = date(2026, 11, 4)
UNLISTED = date(2026, 8, 17)


def _calendar():
    return parse_calendar(CALENDAR_PATH.read_text(encoding="utf-8"))


def _payload(**overrides):
    body = {
        "schema_version": "1",
        "entries": [
            {
                "date": "2026-11-02",
                "kind": "regular",
                "scheduled_close": "16:00",
            },
            {
                "date": "2026-11-03",
                "kind": "early_close",
                "scheduled_close": "13:00",
            },
            {"date": "2026-11-04", "kind": "holiday"},
        ],
    }
    body.update(overrides)
    return body


def test_fixture_has_one_regular_one_early_close_and_one_holiday() -> None:
    calendar = _calendar()
    assert [entry.kind for entry in calendar.entries] == [
        "regular",
        "early_close",
        "holiday",
    ]
    assert [entry.date for entry in calendar.entries] == [
        REGULAR,
        EARLY_CLOSE,
        HOLIDAY,
    ]


def test_regular_day_is_a_trading_day() -> None:
    assert is_trading_day(_calendar(), REGULAR) is True


def test_early_close_day_is_a_trading_day() -> None:
    assert is_trading_day(_calendar(), EARLY_CLOSE) is True


def test_holiday_is_not_a_trading_day() -> None:
    assert is_trading_day(_calendar(), HOLIDAY) is False


def test_unlisted_2026_08_17_is_not_a_trading_day() -> None:
    assert is_trading_day(_calendar(), UNLISTED) is False


def test_regular_scheduled_close_is_1600() -> None:
    assert scheduled_close(_calendar(), REGULAR) == time(16, 0)


def test_early_close_scheduled_close_is_1300() -> None:
    assert scheduled_close(_calendar(), EARLY_CLOSE) == time(13, 0)


def test_holiday_scheduled_close_is_none() -> None:
    assert scheduled_close(_calendar(), HOLIDAY) is None


def test_unlisted_scheduled_close_is_none() -> None:
    assert scheduled_close(_calendar(), UNLISTED) is None


def test_unknown_kind_fails_with_field_path() -> None:
    payload = _payload()
    payload["entries"][0]["kind"] = "half_day"
    with pytest.raises(SchemaError) as exc:
        parse_calendar(payload)
    assert exc.value.path == "entries.0.kind"


def test_holiday_with_a_close_time_fails_with_field_path() -> None:
    payload = _payload()
    payload["entries"][2]["scheduled_close"] = "16:00"
    with pytest.raises(SchemaError) as exc:
        parse_calendar(payload)
    assert exc.value.path == "entries.2.scheduled_close"


def test_session_day_missing_close_fails_with_field_path() -> None:
    payload = _payload()
    del payload["entries"][0]["scheduled_close"]
    with pytest.raises(SchemaError) as exc:
        parse_calendar(payload)
    assert exc.value.path == "entries.0.scheduled_close"


def test_impossible_date_fails_with_field_path() -> None:
    payload = _payload()
    payload["entries"][0]["date"] = "2026-02-30"
    with pytest.raises(SchemaError) as exc:
        parse_calendar(payload)
    assert exc.value.path == "entries.0.date"


def test_duplicate_date_fails_with_field_path() -> None:
    payload = _payload()
    payload["entries"][1]["date"] = "2026-11-02"
    with pytest.raises(SchemaError) as exc:
        parse_calendar(payload)
    assert exc.value.path == "entries.1.date"
