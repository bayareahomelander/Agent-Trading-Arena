"""E4: recorded aggregates map to C5 records. No live network."""

from __future__ import annotations

import hashlib
from datetime import date
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlparse

import pytest

from arena_kernel.marketdata import CommonDataUnavailable, Vendor, bars_at_reference
from arena_kernel.schema.market import bar_to_dict, parse_bar
from arena_kernel.types import parse_et_timestamp
from arena_runtime.vendors.aggregates import (
    DOCUMENTATION_URL,
    AggregatesVendor,
)

_REPO = Path(__file__).resolve().parents[2]
FIXTURES = _REPO / "fixtures" / "golden" / "vendor"
REF = parse_et_timestamp("2026-11-02T10:16:00-05:00")
SESSION = date(2026, 11, 2)
BASE = "https://example.test"


def _recorded(url: str, *, timeout: float, headers: dict[str, str]) -> bytes:
    path = urlparse(url).path
    parts = path.split("/")
    ticker = parts[4]
    timespan = parts[7]
    if ticker == "QQQ":
        return (FIXTURES / "unknown-ticker.json").read_bytes()
    if ticker == "BAD":
        return (FIXTURES / "not-json.txt").read_bytes()
    return (FIXTURES / f"{ticker.lower()}-{timespan}.json").read_bytes()


def _vendor() -> AggregatesVendor:
    return AggregatesVendor(
        base_url=BASE,
        symbols=("AAA", "SPY"),
        get=_recorded,
    )


def test_aggregates_vendor_satisfies_vendor() -> None:
    assert isinstance(_vendor(), Vendor)
    assert "massive.com/docs" in DOCUMENTATION_URL


def test_recorded_minute_bars_are_d5_parseable_and_byte_stable() -> None:
    vendor = _vendor()
    bars = bars_at_reference(vendor, ("SPY", "AAA"), REF)
    assert [bar.symbol for bar in bars] == ["AAA", "SPY"]
    assert bars[0].vwap == Decimal("10.00")
    assert bars[1].vwap == Decimal("100.00")
    assert bars[0].bar_start == REF
    dumped = [bar_to_dict(bar) for bar in bars]
    again = [parse_bar(item) for item in dumped]
    assert [bar_to_dict(bar) for bar in again] == dumped
    second = bars_at_reference(_vendor(), ("SPY", "AAA"), REF)
    assert [bar_to_dict(bar) for bar in second] == dumped


def test_unknown_ticker_raises_and_is_not_an_empty_universe() -> None:
    vendor = AggregatesVendor(
        base_url=BASE, symbols=("QQQ",), get=_recorded
    )
    with pytest.raises(CommonDataUnavailable) as exc:
        vendor.minute_bars(("QQQ",), REF, REF)
    assert exc.value.path == "QQQ"
    with pytest.raises(CommonDataUnavailable):
        vendor.minute_bars(("QQQ",), REF, REF)


def test_unparseable_payload_raises() -> None:
    vendor = AggregatesVendor(
        base_url=BASE, symbols=("BAD",), get=_recorded
    )
    with pytest.raises(CommonDataUnavailable) as exc:
        vendor.minute_bars(("BAD",), REF, REF)
    assert exc.value.path == "BAD"


def test_official_closes_are_unadjusted_daily_close() -> None:
    closes = _vendor().official_closes(SESSION)
    assert closes["AAA"] == Decimal("10.50")
    assert closes["SPY"] == Decimal("112.00")


def test_raw_archive_checksums_and_contains_no_api_key() -> None:
    seen_headers: list[dict[str, str]] = []

    def get(url: str, *, timeout: float, headers: dict[str, str]) -> bytes:
        seen_headers.append(headers)
        return _recorded(url, timeout=timeout, headers=headers)

    vendor = AggregatesVendor(
        base_url=BASE,
        symbols=("AAA",),
        api_key="secret-live-key-1234567890",
        get=get,
    )
    vendor.minute_bars(("AAA",), REF, REF)
    assert vendor.raw_archive
    for url, raw, digest in vendor.raw_archive:
        assert "secret-live-key-1234567890" not in url
        assert "apiKey" not in url
        assert b"secret-live-key-1234567890" not in raw
        assert hashlib.sha256(raw).hexdigest() == digest
        assert url.startswith(f"{BASE}/v2/aggs/ticker/AAA/range/1/minute/")
        assert "adjusted=false" in url
    assert seen_headers[0]["Authorization"] == "Bearer secret-live-key-1234567890"
