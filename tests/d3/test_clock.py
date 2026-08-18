"""D3: clock.json schema."""

import pytest

from arena_kernel.schema import SchemaError, parse_clock
from arena_kernel.types import EXCHANGE_TIMEZONE_NAME, format_et_timestamp

from .conftest import read_fixture


def test_valid_clock_fixture_parses() -> None:
    clock = parse_clock(read_fixture("valid", "clock.json"))
    assert clock.schema_version == "1"
    assert clock.timezone == EXCHANGE_TIMEZONE_NAME
    assert clock.session_status == "open"
    assert clock.round_id == "2026-08-17-morning"
    assert format_et_timestamp(clock.round_start) == "2026-08-17T10:00:00-04:00"
    assert format_et_timestamp(clock.deadline) == "2026-08-17T10:15:00-04:00"


def test_clock_missing_round_id_fails_with_field_path() -> None:
    with pytest.raises(SchemaError) as exc:
        parse_clock(read_fixture("invalid", "clock_missing_round_id.json"))
    assert exc.value.path == "round_id"


def test_clock_naive_timestamp_fails_on_exchange_timestamp() -> None:
    with pytest.raises(SchemaError) as exc:
        parse_clock(read_fixture("invalid", "clock_naive_timestamp.json"))
    assert exc.value.path == "exchange_timestamp"


def test_clock_rejects_wrong_timezone() -> None:
    with pytest.raises(SchemaError) as exc:
        parse_clock(
            {
                "schema_version": "1",
                "exchange_timestamp": "2026-08-17T10:00:00-04:00",
                "timezone": "UTC",
                "session_status": "open",
                "round_id": "2026-08-17-morning",
                "round_start": "2026-08-17T10:00:00-04:00",
                "deadline": "2026-08-17T10:15:00-04:00",
            }
        )
    assert exc.value.path == "timezone"


def test_clock_deadline_must_be_after_round_start() -> None:
    with pytest.raises(SchemaError) as exc:
        parse_clock(
            {
                "schema_version": "1",
                "exchange_timestamp": "2026-08-17T10:00:00-04:00",
                "timezone": "America/New_York",
                "session_status": "open",
                "round_id": "2026-08-17-morning",
                "round_start": "2026-08-17T10:15:00-04:00",
                "deadline": "2026-08-17T10:15:00-04:00",
            }
        )
    assert exc.value.path == "deadline"


def test_clock_rejects_unknown_field() -> None:
    with pytest.raises(SchemaError) as exc:
        parse_clock(
            {
                "schema_version": "1",
                "exchange_timestamp": "2026-08-17T10:00:00-04:00",
                "timezone": "America/New_York",
                "session_status": "open",
                "round_id": "2026-08-17-morning",
                "round_start": "2026-08-17T10:00:00-04:00",
                "deadline": "2026-08-17T10:15:00-04:00",
                "extra": True,
            }
        )
    assert exc.value.path == "extra"
