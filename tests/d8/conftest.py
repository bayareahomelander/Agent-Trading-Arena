from decimal import Decimal

from arena_kernel.schema import Decision, Order, Portfolio

UNIVERSE = frozenset({"AAA", "SPY"})
ROUND_ID = "2026-08-17-morning"

EMPTY_PORTFOLIO = Portfolio(
    schema_version="1",
    replica_id="product-a-1",
    product_id="product-a",
    cash=Decimal("1000.00"),
    positions=(),
    reported_equity=None,
)


def buy(symbol: str = "SPY", *, priority: int = 1, notional: str = "250.00") -> Order:
    return Order(
        priority=priority,
        symbol=symbol,
        side="buy",
        notional_usd=Decimal(notional),
        quantity=None,
    )


def sell(symbol: str = "SPY", *, priority: int = 1, quantity: str = "1.000") -> Order:
    return Order(
        priority=priority,
        symbol=symbol,
        side="sell",
        notional_usd=None,
        quantity=Decimal(quantity),
    )


def decision(
    *orders: Order,
    action: str = "trade",
    round_id: str = ROUND_ID,
    confidence: str = "0.50",
) -> Decision:
    return Decision(
        round_id=round_id,
        action=action,
        orders=orders,
        thesis="test",
        confidence=Decimal(confidence),
        risk_note="test",
        invalidation="test",
        intended_horizon="test",
        schema_version=None,
    )
