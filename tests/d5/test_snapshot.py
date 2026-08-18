"""D5: snapshot with a tiny universe and a replica portfolio handle."""

import json
from decimal import Decimal

import pytest

from arena_kernel.schema import SchemaError, parse_snapshot

from .conftest import read_fixture


def test_snapshot_with_two_symbols_parses() -> None:
    snapshot = parse_snapshot(read_fixture("valid", "snapshot_two_symbols.json"))
    assert snapshot.clock.round_id == "2026-08-17-morning"
    assert snapshot.portfolio.replica_id == "product-a-1"
    assert [bar.symbol for bar in snapshot.bars] == ["AAA", "SPY"]
    assert snapshot.bars[0].vwap == Decimal("10.05")
    assert snapshot.bars[1].vwap is None
    assert snapshot.portfolio.cash == Decimal("1000.00")


def test_snapshot_prefixes_nested_clock_errors() -> None:
    payload = json.loads(
        read_fixture("valid", "snapshot_two_symbols.json"),
        parse_float=Decimal,
    )
    payload["clock"]["timezone"] = "UTC"
    with pytest.raises(SchemaError) as exc:
        parse_snapshot(payload)
    assert exc.value.path == "clock.timezone"


def test_snapshot_rejects_duplicate_bar_symbols() -> None:
    snapshot = {
        "schema_version": "1",
        "clock": {
            "schema_version": "1",
            "exchange_timestamp": "2026-08-17T10:15:00-04:00",
            "timezone": "America/New_York",
            "session_status": "open",
            "round_id": "2026-08-17-morning",
            "round_start": "2026-08-17T10:00:00-04:00",
            "deadline": "2026-08-17T10:15:00-04:00",
        },
        "bars": [
            {
                "symbol": "AAA",
                "bar_start": "2026-08-17T10:15:00-04:00",
                "open": Decimal("10.00"),
                "high": Decimal("10.20"),
                "low": Decimal("9.90"),
                "close": Decimal("10.10"),
                "volume": Decimal("1"),
            },
            {
                "symbol": "AAA",
                "bar_start": "2026-08-17T10:15:00-04:00",
                "open": Decimal("10.00"),
                "high": Decimal("10.20"),
                "low": Decimal("9.90"),
                "close": Decimal("10.10"),
                "volume": Decimal("1"),
            },
        ],
        "portfolio": {
            "schema_version": "1",
            "replica_id": "product-a-1",
            "product_id": "product-a",
            "cash": Decimal("1000.00"),
            "positions": [],
        },
    }
    with pytest.raises(SchemaError) as exc:
        parse_snapshot(snapshot)
    assert exc.value.path == "bars.1.symbol"
