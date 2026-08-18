from decimal import Decimal

from arena_kernel.schema import Order, Portfolio, Position
from arena_kernel.schema.market import Bar
from arena_kernel.types import parse_et_timestamp

ROUND_ID = "2026-08-17-morning"
TS = parse_et_timestamp("2026-08-17T10:16:00-04:00")
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


def buy(symbol: str = "SPY", *, notional: str, priority: int = 1) -> Order:
    return Order(
        priority=priority,
        symbol=symbol,
        side="buy",
        notional_usd=Decimal(notional),
        quantity=None,
    )


def sell(symbol: str = "SPY", *, quantity: str, priority: int = 1) -> Order:
    return Order(
        priority=priority,
        symbol=symbol,
        side="sell",
        notional_usd=None,
        quantity=Decimal(quantity),
    )


def priced_bar(symbol: str = "SPY", *, vwap: str = "100") -> Bar:
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
