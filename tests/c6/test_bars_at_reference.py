"""C6: vendor records become D5 bars. Missing minute is ineligible, not a guess."""

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping, Sequence

import pytest

from arena_kernel.marketdata import (
    CommonDataUnavailable,
    FixtureVendor,
    bars_at_reference,
)
from arena_kernel.schema.errors import SchemaError
from arena_kernel.schema.market import bar_to_dict, parse_bar
from arena_kernel.types import parse_et_timestamp

_REPO = Path(__file__).resolve().parents[2]
VENDOR_DIR = _REPO / "fixtures" / "golden" / "calendar" / "vendor"
MORNING_REF = parse_et_timestamp("2026-11-02T10:16:00-05:00")
MISSING_MINUTE = parse_et_timestamp("2026-11-02T10:17:00-05:00")


class _MapVendor:
    def __init__(
        self,
        records: Sequence[Mapping[str, Any]],
        *,
        known: Sequence[str] | None = None,
    ) -> None:
        self._records = tuple(records)
        self._known = (
            set(known) if known is not None else {str(item["symbol"]) for item in records}
        )

    def minute_bars(
        self,
        symbols: Sequence[str],
        start: datetime,
        end: datetime,
    ) -> tuple[Mapping[str, Any], ...]:
        for symbol in symbols:
            if symbol not in self._known:
                raise CommonDataUnavailable(symbol, "missing")
        wanted = set(symbols)
        return tuple(
            item
            for item in self._records
            if item["symbol"] in wanted
            and start <= parse_et_timestamp(str(item["bar_start"])) <= end
        )

    def official_closes(self, session_date: date) -> dict:
        return {}


def _vendor() -> FixtureVendor:
    return FixtureVendor(VENDOR_DIR)


def test_two_symbol_fixture_returns_aaa_and_spy_sorted() -> None:
    bars = bars_at_reference(_vendor(), ("SPY", "AAA"), MORNING_REF)
    assert [bar.symbol for bar in bars] == ["AAA", "SPY"]
    assert all(bar.eligible for bar in bars)
    assert all(bar.bar_start == MORNING_REF for bar in bars)
    assert bars[0].vwap == Decimal("10.00")
    assert bars[1].vwap == Decimal("100.00")


def test_parse_bar_accepts_every_emitted_bar() -> None:
    bars = bars_at_reference(_vendor(), ("SPY", "AAA"), MORNING_REF)
    for bar in bars:
        assert parse_bar(bar_to_dict(bar)) == bar


def test_vwap_omitted_is_valid() -> None:
    vendor = _MapVendor(
        (
            {
                "symbol": "AAA",
                "bar_start": "2026-11-02T10:16:00-05:00",
                "open": "10.00",
                "high": "10.20",
                "low": "9.80",
                "close": "10.00",
                "volume": "1000",
            },
        )
    )
    (bar,) = bars_at_reference(vendor, ("AAA",), MORNING_REF)
    assert bar.eligible is True
    assert bar.vwap is None
    assert parse_bar(bar_to_dict(bar)) == bar


def test_missing_minute_is_ineligible_and_has_no_ohlc() -> None:
    (bar,) = bars_at_reference(_vendor(), ("AAA",), MISSING_MINUTE)
    assert bar.symbol == "AAA"
    assert bar.eligible is False
    assert bar.open is None
    assert bar.high is None
    assert bar.low is None
    assert bar.close is None
    assert bar.volume is None
    assert bar.vwap is None
    assert bar.bar_start == MISSING_MINUTE
    assert parse_bar(bar_to_dict(bar)) == bar


def test_halt_record_is_ineligible_not_a_guessed_print() -> None:
    vendor = _MapVendor(
        (
            {
                "symbol": "HALT",
                "bar_start": "2026-11-02T10:16:00-05:00",
                "eligible": False,
            },
        )
    )
    (bar,) = bars_at_reference(vendor, ("HALT",), MORNING_REF)
    assert bar.eligible is False
    assert bar.open is None
    assert bar.vwap is None
    assert parse_bar(bar_to_dict(bar)) == bar


def test_high_less_than_low_is_an_error_not_a_swap() -> None:
    vendor = _MapVendor(
        (
            {
                "symbol": "AAA",
                "bar_start": "2026-11-02T10:16:00-05:00",
                "open": "10.00",
                "high": "9.00",
                "low": "9.50",
                "close": "9.80",
                "volume": "1000",
            },
        )
    )
    with pytest.raises(SchemaError) as exc:
        bars_at_reference(vendor, ("AAA",), MORNING_REF)
    assert exc.value.path == "AAA.high"


def test_missing_symbol_still_raises_common_data_unavailable() -> None:
    with pytest.raises(CommonDataUnavailable) as exc:
        bars_at_reference(_vendor(), ("QQQ",), MORNING_REF)
    assert exc.value.path == "QQQ"


def test_naive_reference_minute_is_rejected() -> None:
    with pytest.raises(ValueError, match="offset"):
        bars_at_reference(_vendor(), ("AAA",), datetime(2026, 11, 2, 10, 16))
