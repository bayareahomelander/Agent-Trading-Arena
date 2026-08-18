"""Helpers for candidate kernel-evaluation fixtures."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from arena_kernel.schema.clock import Clock
from arena_kernel.schema.fills import FillsFile
from arena_kernel.schema.market import Bar, Snapshot
from arena_kernel.schema.portfolio import Portfolio
from arena_kernel.types import EXCHANGE_TIMEZONE_NAME, parse_et_timestamp
from arena_runtime.orchestrator import evaluate_candidates
from tests.r20.conftest import ROUND_ID, collect, make_result

START = parse_et_timestamp("2026-08-17T10:00:00-04:00")
DEADLINE = parse_et_timestamp("2026-08-17T10:15:00-04:00")
BAR_START = parse_et_timestamp("2026-08-17T10:16:00-04:00")


def decision_bytes(*, action: str = "hold", orders: list[dict] | None = None) -> bytes:
    payload = {
        "round_id": ROUND_ID,
        "action": action,
        "orders": [] if orders is None else orders,
        "thesis": "placeholder thesis",
        "confidence": 0.5,
        "risk_note": "placeholder risk",
        "invalidation": "placeholder invalidation",
        "intended_horizon": "placeholder horizon",
    }
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


HOLD_DECISION = decision_bytes()
SPY_BUY = decision_bytes(
    action="trade",
    orders=[
        {
            "priority": 1,
            "symbol": "SPY",
            "side": "buy",
            "notional_usd": "500.00",
        }
    ],
)
MIXED_ORDERS = decision_bytes(
    action="trade",
    orders=[
        {
            "priority": 1,
            "symbol": "QQQ",
            "side": "buy",
            "notional_usd": "100.00",
        },
        {
            "priority": 2,
            "symbol": "SPY",
            "side": "buy",
            "notional_usd": "100.05",
        },
    ],
)
MALFORMED_DECISION = b" {not valid json so R21 must use the missing path \r\n"


def cash_book(
    replica_id: str = "product-a-1",
    *,
    product_id: str = "product-a",
    cash: str = "1000.00",
) -> Portfolio:
    return Portfolio(
        schema_version="1",
        replica_id=replica_id,
        product_id=product_id,
        cash=Decimal(cash),
        positions=(),
        reported_equity=None,
    )


def priced_bar(symbol: str, *, vwap: str = "100") -> Bar:
    price = Decimal(vwap)
    return Bar(
        symbol=symbol,
        bar_start=BAR_START,
        eligible=True,
        open=price,
        high=price,
        low=price,
        close=price,
        volume=Decimal("1000"),
        vwap=price,
    )


def evaluation_snapshot(*books: Portfolio, symbols: tuple[str, ...] = ("SPY",)) -> Snapshot:
    book = books[0] if books else cash_book()
    return Snapshot(
        schema_version="1",
        clock=Clock(
            schema_version="1",
            exchange_timestamp=DEADLINE,
            timezone=EXCHANGE_TIMEZONE_NAME,
            session_status="open",
            round_id=ROUND_ID,
            round_start=START,
            deadline=DEADLINE,
        ),
        bars=tuple(priced_bar(symbol) for symbol in symbols),
        portfolio=book,
    )


def empty_fills() -> FillsFile:
    return FillsFile(schema_version="1", fills=())


def evaluate(
    root: Path,
    results,
    *,
    payloads: dict[str, bytes | None],
    books: dict[str, Portfolio],
    fills: dict[str, FillsFile] | None = None,
    snapshot: Snapshot | None = None,
):
    collection = collect(root, results, payloads=payloads)
    return evaluate_candidates(
        collection=collection,
        snapshot=snapshot or evaluation_snapshot(*books.values()),
        books=books,
        fills=fills,
    ), collection
