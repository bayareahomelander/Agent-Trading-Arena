from decimal import Decimal

from arena_kernel.schema import Decision, Order, Portfolio, Position, Snapshot
from arena_kernel.schema.clock import Clock
from arena_kernel.schema.market import Bar
from arena_kernel.types import EXCHANGE_TIMEZONE_NAME, parse_et_timestamp

ROUND_ID = "2026-08-17-morning"
TS = parse_et_timestamp("2026-08-17T10:16:00-04:00")
START = parse_et_timestamp("2026-08-17T10:00:00-04:00")
BAR_START = parse_et_timestamp("2026-08-17T10:15:00-04:00")


def cash_book(cash: str = "1000.00", *positions: Position) -> Portfolio:
    return Portfolio(
        schema_version="1",
        replica_id="product-a-1",
        product_id="product-a",
        cash=Decimal(cash),
        positions=positions,
        reported_equity=None,
    )


def position(symbol: str, quantity: str, cost_basis: str) -> Position:
    return Position(
        symbol=symbol,
        quantity=Decimal(quantity),
        cost_basis=Decimal(cost_basis),
    )


def buy(symbol: str, *, notional: str, priority: int) -> Order:
    return Order(
        priority=priority,
        symbol=symbol,
        side="buy",
        notional_usd=Decimal(notional),
        quantity=None,
    )


def sell(symbol: str, *, quantity: str, priority: int) -> Order:
    return Order(
        priority=priority,
        symbol=symbol,
        side="sell",
        notional_usd=None,
        quantity=Decimal(quantity),
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


def snapshot(book: Portfolio, *bars: Bar) -> Snapshot:
    return Snapshot(
        schema_version="1",
        clock=Clock(
            schema_version="1",
            exchange_timestamp=TS,
            timezone=EXCHANGE_TIMEZONE_NAME,
            session_status="open",
            round_id=ROUND_ID,
            round_start=START,
            deadline=TS,
        ),
        bars=bars,
        portfolio=book,
    )


def decision(*orders: Order, action: str = "trade", confidence: str = "0.50") -> Decision:
    return Decision(
        round_id=ROUND_ID,
        action=action,
        orders=orders,
        thesis="test",
        confidence=Decimal(confidence),
        risk_note="test",
        invalidation="test",
        intended_horizon="test",
        schema_version=None,
    )
