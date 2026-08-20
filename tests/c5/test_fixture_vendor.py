"""C5: FixtureVendor reads local files. Missing symbol raises. No HTTP."""

import ast
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from arena_kernel import marketdata
from arena_kernel.marketdata import (
    CommonDataUnavailable,
    FixtureVendor,
)
from arena_kernel.types import parse_et_timestamp

_REPO = Path(__file__).resolve().parents[2]
VENDOR_DIR = _REPO / "fixtures" / "golden" / "calendar" / "vendor"

MORNING_REF = parse_et_timestamp("2026-11-02T10:16:00-05:00")
LATE_REF = parse_et_timestamp("2026-11-02T15:46:00-05:00")
SESSION = date(2026, 11, 2)


def _vendor() -> FixtureVendor:
    return FixtureVendor(VENDOR_DIR)


def test_minute_bars_returns_requested_symbols_in_the_window() -> None:
    records = _vendor().minute_bars(("AAA", "SPY"), MORNING_REF, MORNING_REF)
    assert [item["symbol"] for item in records] == ["AAA", "SPY"]
    assert all(item["bar_start"] == "2026-11-02T10:16:00-05:00" for item in records)


def test_minute_bars_does_not_include_minutes_outside_the_window() -> None:
    records = _vendor().minute_bars(("AAA",), MORNING_REF, MORNING_REF)
    assert len(records) == 1
    assert records[0]["bar_start"] == "2026-11-02T10:16:00-05:00"


def test_minute_bars_returns_raw_records_not_d5_bars() -> None:
    records = _vendor().minute_bars(("SPY",), LATE_REF, LATE_REF)
    assert len(records) == 1
    assert isinstance(records[0], dict)
    assert "vwap" in records[0]
    assert not hasattr(records[0], "eligible")


def test_missing_symbol_raises_common_data_unavailable() -> None:
    with pytest.raises(CommonDataUnavailable) as exc:
        _vendor().minute_bars(("QQQ",), MORNING_REF, MORNING_REF)
    assert exc.value.path == "QQQ"


def test_missing_symbol_does_not_return_an_empty_list() -> None:
    with pytest.raises(CommonDataUnavailable) as exc:
        _vendor().minute_bars(("AAA", "QQQ"), MORNING_REF, MORNING_REF)
    assert exc.value.path == "QQQ"


def test_missing_bars_file_raises_with_path() -> None:
    vendor = FixtureVendor(VENDOR_DIR / "does-not-exist")
    with pytest.raises(CommonDataUnavailable) as exc:
        vendor.minute_bars(("AAA",), MORNING_REF, MORNING_REF)
    assert exc.value.path == "bars.json"


def test_official_closes_returns_fixture_prices() -> None:
    closes = _vendor().official_closes(SESSION)
    assert closes["AAA"] == Decimal("10.50")
    assert closes["SPY"] == Decimal("112.00")


def test_missing_close_date_raises_common_data_unavailable() -> None:
    with pytest.raises(CommonDataUnavailable) as exc:
        _vendor().official_closes(date(2026, 11, 4))
    assert exc.value.path == "2026-11-04"


def test_missing_closes_file_raises_with_path() -> None:
    vendor = FixtureVendor(VENDOR_DIR / "does-not-exist")
    with pytest.raises(CommonDataUnavailable) as exc:
        vendor.official_closes(SESSION)
    assert exc.value.path == "closes.json"


def test_naive_start_is_rejected() -> None:
    with pytest.raises(ValueError, match="offset"):
        _vendor().minute_bars(
            ("AAA",),
            datetime(2026, 11, 2, 10, 16),
            MORNING_REF,
        )


def test_start_after_end_is_rejected() -> None:
    with pytest.raises(ValueError, match="after"):
        _vendor().minute_bars(("AAA",), LATE_REF, MORNING_REF)


def test_marketdata_module_does_not_import_http_or_sockets() -> None:
    source = Path(marketdata.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    banned = ("urllib", "httpx", "requests", "aiohttp", "socket")
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module.split(".", 1)[0])
    assert not any(name in banned for name in names)
