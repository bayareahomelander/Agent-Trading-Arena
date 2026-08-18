"""D4: decision.json shape only. No cash, universe, or max-order checks."""

from decimal import Decimal

import pytest

from arena_kernel.schema import SchemaError, parse_decision

from .conftest import read_fixture


def test_readme_trade_example_parses() -> None:
    decision = parse_decision(read_fixture("valid", "trade_readme.json"))
    assert decision.round_id == "2026-08-17-morning"
    assert decision.action == "trade"
    assert len(decision.orders) == 1
    order = decision.orders[0]
    assert order.priority == 1
    assert order.symbol == "SPY"
    assert order.side == "buy"
    assert order.notional_usd == Decimal("250.00")
    assert order.quantity is None
    assert decision.confidence == Decimal("0.62")
    assert decision.schema_version is None


def test_readme_hold_example_parses() -> None:
    decision = parse_decision(read_fixture("valid", "hold_readme.json"))
    assert decision.round_id == "2026-08-17-late"
    assert decision.action == "hold"
    assert decision.orders == ()
    assert decision.confidence == Decimal("0.70")


def test_buy_with_quantity_instead_of_notional_is_schema_error() -> None:
    with pytest.raises(SchemaError) as exc:
        parse_decision(read_fixture("invalid", "buy_with_quantity.json"))
    assert exc.value.path == "orders.0.quantity"


def test_hold_with_orders_is_schema_error() -> None:
    with pytest.raises(SchemaError) as exc:
        parse_decision(read_fixture("invalid", "hold_with_orders.json"))
    assert exc.value.path == "orders"


def test_sell_with_notional_instead_of_quantity_is_schema_error() -> None:
    with pytest.raises(SchemaError) as exc:
        parse_decision(read_fixture("invalid", "sell_with_notional.json"))
    assert exc.value.path == "orders.0.notional_usd"


def test_sell_with_quantity_parses() -> None:
    decision = parse_decision(
        {
            "round_id": "2026-08-17-morning",
            "action": "trade",
            "orders": [
                {
                    "priority": 1,
                    "symbol": "SPY",
                    "side": "sell",
                    "quantity": "1.500",
                }
            ],
            "thesis": "Reduce SPY.",
            "confidence": Decimal("0.40"),
            "risk_note": "May miss upside.",
            "invalidation": "Price drops through thesis.",
            "intended_horizon": "1-3 trading days",
        }
    )
    assert decision.orders[0].quantity == Decimal("1.500")
    assert decision.orders[0].notional_usd is None


def test_priority_zero_is_schema_error() -> None:
    with pytest.raises(SchemaError) as exc:
        parse_decision(
            {
                "round_id": "2026-08-17-morning",
                "action": "trade",
                "orders": [
                    {
                        "priority": 0,
                        "symbol": "SPY",
                        "side": "buy",
                        "notional_usd": Decimal("250.00"),
                    }
                ],
                "thesis": "Bad priority.",
                "confidence": Decimal("0.10"),
                "risk_note": "n/a",
                "invalidation": "n/a",
                "intended_horizon": "n/a",
            }
        )
    assert exc.value.path == "orders.0.priority"


def test_unknown_action_is_schema_error() -> None:
    with pytest.raises(SchemaError) as exc:
        parse_decision(
            {
                "round_id": "2026-08-17-morning",
                "action": "rebalance",
                "orders": [],
                "thesis": "n/a",
                "confidence": Decimal("0.10"),
                "risk_note": "n/a",
                "invalidation": "n/a",
                "intended_horizon": "n/a",
            }
        )
    assert exc.value.path == "action"


def test_twenty_one_orders_still_parse_in_d4() -> None:
    orders = [
        {
            "priority": index + 1,
            "symbol": "SPY",
            "side": "buy",
            "notional_usd": Decimal("1.00"),
        }
        for index in range(21)
    ]
    decision = parse_decision(
        {
            "round_id": "2026-08-17-morning",
            "action": "trade",
            "orders": orders,
            "thesis": "Max-20 is D8.",
            "confidence": Decimal("0.10"),
            "risk_note": "n/a",
            "invalidation": "n/a",
            "intended_horizon": "n/a",
        }
    )
    assert len(decision.orders) == 21
