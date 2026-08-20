"""E1: Vendor protocol is the kernel seam. FixtureVendor is one implementation."""

from decimal import Decimal
from pathlib import Path
from typing import get_type_hints

from arena_kernel.marketdata import (
    FixtureVendor,
    Vendor,
    _close_json,
    bars_at_reference,
    build_tape,
)
from arena_kernel.types import parse_et_timestamp

_REPO = Path(__file__).resolve().parents[2]
VENDOR_DIR = _REPO / "fixtures" / "golden" / "calendar" / "vendor"
REF = parse_et_timestamp("2026-11-02T10:16:00-05:00")


class _MemoryVendor:
    def minute_bars(self, symbols, start, end):
        return (
            {
                "symbol": "AAA",
                "bar_start": "2026-11-02T10:16:00-05:00",
                "open": "10.00",
                "high": "10.20",
                "low": "9.80",
                "close": "10.00",
                "volume": "1000",
                "vwap": "10.00",
            },
        )

    def official_closes(self, session_date):
        return {"AAA": Decimal("10.50")}


def test_fixture_vendor_satisfies_vendor() -> None:
    assert issubclass(FixtureVendor, Vendor)
    assert isinstance(FixtureVendor(VENDOR_DIR), Vendor)


def test_helpers_are_typed_to_vendor() -> None:
    assert get_type_hints(bars_at_reference)["vendor"] is Vendor
    assert get_type_hints(build_tape)["vendor"] is Vendor
    assert get_type_hints(_close_json)["vendor"] is Vendor


def test_bars_at_reference_accepts_a_non_fixture_vendor() -> None:
    bars = bars_at_reference(_MemoryVendor(), ("AAA",), REF)
    assert len(bars) == 1
    assert bars[0].symbol == "AAA"
    assert bars[0].vwap == Decimal("10.00")


def test_matching_and_pricing_do_not_import_vendor() -> None:
    matching = (_REPO / "src" / "arena_kernel" / "matching.py").read_text(
        encoding="utf-8"
    )
    pricing = (_REPO / "src" / "arena_kernel" / "pricing.py").read_text(
        encoding="utf-8"
    )
    for source in (matching, pricing):
        assert "FixtureVendor" not in source
        assert "marketdata" not in source
