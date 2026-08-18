"""D8: business rules only. Cash and holdings wait for D10."""

from arena_kernel.validate import (
    CODE_ACTION,
    CODE_BUY_NOTIONAL,
    CODE_CONFIDENCE,
    CODE_CONTRADICTION,
    CODE_HOLD_ORDERS,
    CODE_MAX_ORDERS,
    CODE_ROUND_ID,
    CODE_SELL_QUANTITY,
    CODE_UNIVERSE,
    validate_decision,
)

from .conftest import EMPTY_PORTFOLIO, ROUND_ID, UNIVERSE, buy, decision, sell


def _validate(dec, *, universe=UNIVERSE, round_id=ROUND_ID):
    return validate_decision(dec, EMPTY_PORTFOLIO, universe, round_id)


def test_round_id_must_match_expected_round() -> None:
    result = _validate(decision(buy()), round_id="2026-08-17-late")
    assert result.file_accepted is False
    assert result.accepted_orders == ()
    assert result.issues[0].code == CODE_ROUND_ID
    assert result.issues[0].path == "round_id"


def test_unknown_action_rejects_the_whole_file() -> None:
    result = _validate(decision(action="rebalance"))
    assert result.file_accepted is False
    assert result.issues[0].code == CODE_ACTION
    assert result.issues[0].path == "action"


def test_hold_with_orders_rejects_the_whole_file() -> None:
    result = _validate(decision(buy(), action="hold"))
    assert result.file_accepted is False
    assert result.issues[0].code == CODE_HOLD_ORDERS
    assert result.issues[0].path == "orders"


def test_confidence_must_be_between_0_and_1() -> None:
    result = _validate(decision(buy(), confidence="1.01"))
    assert result.file_accepted is False
    assert result.issues[0].code == CODE_CONFIDENCE
    assert result.issues[0].path == "confidence"


def test_symbol_outside_universe_rejects_only_that_order() -> None:
    result = _validate(decision(buy("QQQ"), buy("SPY", priority=2)))
    assert result.file_accepted is True
    assert [order.symbol for order in result.accepted_orders] == ["SPY"]
    assert result.issues[0].code == CODE_UNIVERSE
    assert result.issues[0].path == "orders.0.symbol"


def test_buy_notional_must_be_greater_than_zero() -> None:
    result = _validate(decision(buy(notional="0.00")))
    assert result.file_accepted is True
    assert result.accepted_orders == ()
    assert result.issues[0].code == CODE_BUY_NOTIONAL
    assert result.issues[0].path == "orders.0.notional_usd"


def test_sell_quantity_must_be_greater_than_zero() -> None:
    result = _validate(decision(sell(quantity="0")))
    assert result.file_accepted is True
    assert result.accepted_orders == ()
    assert result.issues[0].code == CODE_SELL_QUANTITY
    assert result.issues[0].path == "orders.0.quantity"


def test_twenty_first_order_is_rejected_first_twenty_remain() -> None:
    universe = frozenset(f"S{i:02d}" for i in range(21))
    orders = [buy(f"S{i:02d}", priority=i + 1, notional="1.00") for i in range(21)]
    result = _validate(decision(*orders), universe=universe)
    assert result.file_accepted is True
    assert len(result.accepted_orders) == 20
    assert [order.symbol for order in result.accepted_orders] == [
        f"S{i:02d}" for i in range(20)
    ]
    assert result.issues[0].code == CODE_MAX_ORDERS
    assert result.issues[0].order_index == 20
    assert result.issues[0].path == "orders.20"


def test_two_buys_same_symbol_keeps_earlier_priority() -> None:
    result = _validate(
        decision(
            buy("SPY", priority=2, notional="10.00"),
            buy("SPY", priority=1, notional="20.00"),
        )
    )
    assert result.file_accepted is True
    assert len(result.accepted_orders) == 1
    assert result.accepted_orders[0].priority == 1
    assert result.accepted_orders[0].notional_usd is not None
    assert result.issues[0].code == CODE_CONTRADICTION
    assert result.issues[0].order_index == 0


def test_two_sells_same_symbol_keeps_first_by_priority() -> None:
    result = _validate(
        decision(
            sell("SPY", priority=1, quantity="1.000"),
            sell("SPY", priority=2, quantity="2.000"),
        )
    )
    assert result.accepted_orders[0].quantity is not None
    assert result.accepted_orders[0].priority == 1
    assert result.issues[0].code == CODE_CONTRADICTION
    assert result.issues[0].order_index == 1


def test_buy_and_sell_same_symbol_are_contradictory() -> None:
    result = _validate(
        decision(
            buy("SPY", priority=1, notional="10.00"),
            sell("SPY", priority=2, quantity="1.000"),
        )
    )
    assert len(result.accepted_orders) == 1
    assert result.accepted_orders[0].side == "buy"
    assert result.issues[0].code == CODE_CONTRADICTION


def test_same_priority_same_symbol_keeps_earlier_file_order() -> None:
    result = _validate(
        decision(
            buy("SPY", priority=1, notional="10.00"),
            buy("SPY", priority=1, notional="20.00"),
        )
    )
    assert result.accepted_orders[0].notional_usd is not None
    assert str(result.accepted_orders[0].notional_usd) == "10.00"
    assert result.issues[0].order_index == 1


def test_valid_hold_has_no_issues() -> None:
    result = _validate(decision(action="hold"))
    assert result.file_accepted is True
    assert result.accepted_orders == ()
    assert result.issues == ()
