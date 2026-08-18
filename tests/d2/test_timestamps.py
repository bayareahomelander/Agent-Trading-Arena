"""D2: ET timestamps require an offset and never assume UTC."""

from datetime import datetime, timezone

import pytest

from arena_kernel.types import (
    EXCHANGE_TIMEZONE_NAME,
    format_et_timestamp,
    parse_et_timestamp,
)


def test_parse_et_timestamp_keeps_explicit_eastern_offset() -> None:
    parsed = parse_et_timestamp("2026-08-17T10:00:00-04:00")
    assert parsed.tzinfo is not None
    assert parsed.tzinfo.key == EXCHANGE_TIMEZONE_NAME  # type: ignore[attr-defined]
    assert format_et_timestamp(parsed) == "2026-08-17T10:00:00-04:00"


def test_parse_utc_z_converts_to_eastern_and_does_not_keep_utc_wall_time() -> None:
    parsed = parse_et_timestamp("2026-08-17T14:00:00Z")
    assert format_et_timestamp(parsed) == "2026-08-17T10:00:00-04:00"


def test_parse_winter_utc_uses_est_offset() -> None:
    parsed = parse_et_timestamp("2026-01-15T15:00:00+00:00")
    assert format_et_timestamp(parsed) == "2026-01-15T10:00:00-05:00"


def test_parse_et_timestamp_rejects_missing_offset() -> None:
    with pytest.raises(ValueError, match="offset"):
        parse_et_timestamp("2026-08-17T10:00:00")


def test_format_et_timestamp_rejects_naive_datetime() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        format_et_timestamp(datetime(2026, 8, 17, 10, 0, 0))


def test_format_converts_aware_utc_to_et_offset() -> None:
    utc = datetime(2026, 8, 17, 14, 0, 0, tzinfo=timezone.utc)
    assert format_et_timestamp(utc) == "2026-08-17T10:00:00-04:00"
