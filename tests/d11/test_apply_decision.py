"""D11: sealed batch. If D10 tests pass, bugs here are sort order or sequential cash."""

from arena_kernel.matching import REASON_INSUFFICIENT_CASH, apply_decision
from arena_kernel.schema.events import (
    DecisionAcceptedPayload,
    DecisionMissingPayload,
    OrderFilledPayload,
    OrderRejectedPayload,
)
from arena_kernel.validate import CODE_CONFIDENCE, CODE_UNIVERSE

from .conftest import buy, cash_book, decision, position, priced_bar, sell, snapshot


def test_rebalance_sell_funds_a_buy_that_could_not_afford_before() -> None:
    book = cash_book("50.00", position("AAA", "10.000", "10.0000"))
    tape = snapshot(book, priced_bar("AAA"), priced_bar("SPY"))
    # Buy SPY needs ~500 cash; only 50 until AAA is sold.
    events, after = apply_decision(
        book,
        decision(
            buy("SPY", notional="500.00", priority=1),
            sell("AAA", quantity="10.000", priority=1),
        ),
        tape,
    )
    kinds = [event.event_type for event in events]
    assert kinds[0] == "decision_accepted"
    assert isinstance(events[1].payload, OrderFilledPayload)
    assert events[1].payload.side == "sell"
    assert events[1].payload.symbol == "AAA"
    assert isinstance(events[2].payload, OrderFilledPayload)
    assert events[2].payload.side == "buy"
    assert events[2].payload.symbol == "SPY"
    assert after.cash < book.cash or after.positions
    assert any(pos.symbol == "SPY" for pos in after.positions)
    assert not any(pos.symbol == "AAA" for pos in after.positions)


def test_first_buy_rejected_for_cash_second_smaller_buy_accepted() -> None:
    book = cash_book("100.00")
    tape = snapshot(book, priced_bar("SPY"), priced_bar("AAA"))
    events, after = apply_decision(
        book,
        decision(
            buy("SPY", notional="1000.00", priority=1),
            buy("AAA", notional="50.00", priority=2),
        ),
        tape,
    )
    order_events = [event for event in events if event.event_type != "decision_accepted"]
    assert isinstance(order_events[0].payload, OrderRejectedPayload)
    assert order_events[0].payload.reason == REASON_INSUFFICIENT_CASH
    assert order_events[0].payload.symbol == "SPY"
    assert isinstance(order_events[1].payload, OrderFilledPayload)
    assert order_events[1].payload.symbol == "AAA"
    assert after.positions[0].symbol == "AAA"


def test_priority_2_sell_runs_before_priority_10_sell() -> None:
    book = cash_book(
        "0.00",
        position("AAA", "1.000", "10.0000"),
        position("SPY", "1.000", "10.0000"),
    )
    tape = snapshot(book, priced_bar("AAA"), priced_bar("SPY"))
    events, _after = apply_decision(
        book,
        decision(
            sell("SPY", quantity="1.000", priority=10),
            sell("AAA", quantity="1.000", priority=2),
        ),
        tape,
    )
    fills = [event.payload for event in events if isinstance(event.payload, OrderFilledPayload)]
    assert [fill.symbol for fill in fills] == ["AAA", "SPY"]


def test_file_level_invalid_emits_decision_missing_and_does_not_trade() -> None:
    book = cash_book("1000.00")
    tape = snapshot(book, priced_bar("SPY"))
    events, after = apply_decision(
        book,
        decision(buy("SPY", notional="100.00", priority=1), confidence="1.50"),
        tape,
    )
    assert len(events) == 1
    assert isinstance(events[0].payload, DecisionMissingPayload)
    assert events[0].payload.reason == CODE_CONFIDENCE
    assert after is book
    assert after.cash == book.cash


def test_d8_universe_reject_does_not_stop_later_valid_order() -> None:
    book = cash_book("1000.00")
    tape = snapshot(book, priced_bar("SPY"))
    events, after = apply_decision(
        book,
        decision(
            buy("QQQ", notional="100.00", priority=1),
            buy("SPY", notional="100.05", priority=2),
        ),
        tape,
    )
    assert isinstance(events[0].payload, DecisionAcceptedPayload)
    assert events[0].payload.order_count == 1
    assert isinstance(events[1].payload, OrderRejectedPayload)
    assert events[1].payload.reason == CODE_UNIVERSE
    assert isinstance(events[2].payload, OrderFilledPayload)
    assert events[2].payload.symbol == "SPY"
    assert after.positions[0].symbol == "SPY"


def test_hold_emits_decision_accepted_and_does_not_trade() -> None:
    book = cash_book("1000.00")
    tape = snapshot(book, priced_bar("SPY"))
    events, after = apply_decision(book, decision(action="hold"), tape)
    assert len(events) == 1
    assert isinstance(events[0].payload, DecisionAcceptedPayload)
    assert events[0].payload.action == "hold"
    assert events[0].payload.order_count == 0
    assert after.cash == book.cash
    assert after.positions == ()
