"""E2: round-start snapshot bars are not fill bars."""

import hashlib
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from arena_kernel.calendar import parse_calendar, rounds_for_day
from arena_kernel.marketdata import (
    bars_at_reference,
    last_complete_minute,
    publish_round,
)
from arena_kernel.matching import apply_decision
from arena_kernel.schema.decision import parse_decision
from arena_kernel.schema.events import OrderFilledPayload
from arena_kernel.schema.market import Snapshot, parse_snapshot
from arena_kernel.schema.portfolio import Portfolio
from arena_kernel.types import parse_et_timestamp
from arena_kernel.workspace import SNAPSHOT_FILE

_REPO = Path(__file__).resolve().parents[2]
CALENDAR = _REPO / "fixtures" / "golden" / "calendar" / "calendar.json"
SESSION = date(2026, 11, 2)
START_PRINT = "9.00"
FILL_PRINT = "10.00"
START_BAR = "2026-11-02T09:59:00-05:00"
FILL_BAR = "2026-11-02T10:16:00-05:00"


def _bar(symbol: str, bar_start: str, vwap: str) -> dict[str, str]:
    return {
        "symbol": symbol,
        "bar_start": bar_start,
        "open": vwap,
        "high": vwap,
        "low": vwap,
        "close": vwap,
        "volume": "1000",
        "vwap": vwap,
    }


class _SplitVendor:
    def minute_bars(self, symbols, start, end):
        wanted = set(symbols)
        out = []
        for item in (
            _bar("AAA", START_BAR, START_PRINT),
            _bar("AAA", FILL_BAR, FILL_PRINT),
        ):
            if item["symbol"] not in wanted:
                continue
            bar_start = parse_et_timestamp(item["bar_start"])
            if start <= bar_start <= end:
                out.append(item)
        return tuple(out)

    def official_closes(self, session_date):
        return {"AAA": Decimal("10.50")}


def _morning():
    calendar = parse_calendar(CALENDAR.read_text(encoding="utf-8"))
    morning, _late = rounds_for_day(calendar, SESSION)
    return morning


def _book() -> Portfolio:
    return Portfolio(
        schema_version="1",
        replica_id="product-a-1",
        product_id="product-a",
        cash=Decimal("1000.00"),
        positions=(),
        reported_equity=None,
    )


def _buy() -> object:
    return parse_decision(
        {
            "round_id": "2026-11-02-morning",
            "action": "trade",
            "orders": [
                {
                    "priority": 1,
                    "symbol": "AAA",
                    "side": "buy",
                    "notional_usd": "100.00",
                }
            ],
            "thesis": "e2",
            "confidence": "0.5",
            "risk_note": "e2",
            "invalidation": "e2",
            "intended_horizon": "e2",
        }
    )


def test_last_complete_minute_floors_in_progress_and_exact_start() -> None:
    assert last_complete_minute(
        parse_et_timestamp("2026-11-02T10:00:07-05:00")
    ) == parse_et_timestamp("2026-11-02T09:59:00-05:00")
    assert last_complete_minute(
        parse_et_timestamp("2026-11-02T10:00:00-05:00")
    ) == parse_et_timestamp("2026-11-02T09:59:00-05:00")


def test_naive_instant_is_rejected() -> None:
    with pytest.raises(ValueError, match="offset"):
        last_complete_minute(datetime(2026, 11, 2, 10, 0, 7))


def test_publish_uses_round_start_bars_and_fill_uses_reference_minute(
    tmp_path: Path,
) -> None:
    vendor = _SplitVendor()
    scheduled = _morning()
    book = _book()
    start_bars = bars_at_reference(
        vendor, ("AAA",), last_complete_minute(scheduled.start)
    )
    publish_round(
        tmp_path,
        scheduled=scheduled,
        bars=start_bars,
        portfolios=(book,),
        raw_vendor_bytes=b"{}",
        rules_md="# rules\n",
        prompt_md="prompt\n",
    )
    snapshot_path = tmp_path / "replicas" / "product-a-1" / SNAPSHOT_FILE
    before = snapshot_path.read_bytes()
    workspace = parse_snapshot(before.decode("utf-8"))
    assert workspace.bars[0].vwap == Decimal(START_PRINT)
    assert workspace.bars[0].bar_start == parse_et_timestamp(START_BAR)

    fill_bars = bars_at_reference(vendor, ("AAA",), scheduled.reference_minute)
    after = snapshot_path.read_bytes()
    assert hashlib.sha256(after).digest() == hashlib.sha256(before).digest()
    assert after == before
    assert fill_bars[0].vwap == Decimal(FILL_PRINT)
    assert fill_bars[0].bar_start == parse_et_timestamp(FILL_BAR)

    fill_snapshot = Snapshot(
        schema_version=workspace.schema_version,
        clock=workspace.clock,
        bars=fill_bars,
        portfolio=book,
    )
    events, _after = apply_decision(book, _buy(), fill_snapshot)
    fills = [
        event.payload
        for event in events
        if isinstance(event.payload, OrderFilledPayload)
    ]
    assert len(fills) == 1
    assert fills[0].fill_price == Decimal("10.0050")
    assert fills[0].bar_start == parse_et_timestamp(FILL_BAR)
