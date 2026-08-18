"""D5: one-minute bar schema. Missing VWAP is valid; high < low is not."""

from decimal import Decimal

import pytest

from arena_kernel.schema import SchemaError, parse_bar

from .conftest import read_fixture


def test_bar_without_vwap_is_valid() -> None:
    bar = parse_bar(read_fixture("valid", "bar_no_vwap.json"))
    assert bar.symbol == "AAA"
    assert bar.eligible is True
    assert bar.vwap is None
    assert bar.high == Decimal("10.20")
    assert bar.low == Decimal("9.90")


def test_ineligible_bar_does_not_need_ohlc() -> None:
    bar = parse_bar(read_fixture("valid", "bar_ineligible.json"))
    assert bar.symbol == "HALT"
    assert bar.eligible is False
    assert bar.open is None
    assert bar.vwap is None


def test_bar_high_less_than_low_fails_with_field_path() -> None:
    with pytest.raises(SchemaError) as exc:
        parse_bar(read_fixture("invalid", "bar_high_lt_low.json"))
    assert exc.value.path == "high"


def test_eligible_bar_missing_close_fails() -> None:
    with pytest.raises(SchemaError) as exc:
        parse_bar(
            {
                "symbol": "AAA",
                "bar_start": "2026-08-17T10:15:00-04:00",
                "open": Decimal("10.00"),
                "high": Decimal("10.20"),
                "low": Decimal("9.90"),
                "volume": Decimal("1000"),
            }
        )
    assert exc.value.path == "close"
