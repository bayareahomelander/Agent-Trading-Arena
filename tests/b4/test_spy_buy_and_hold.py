"""B4: one SPY buy at the first window through apply_decision, then D12."""

from decimal import Decimal

import pytest

from arena_kernel.baselines import FirstWindowError, SpyBaselineError, run_spy_buy_and_hold
from arena_kernel.schema import Position
from arena_kernel.schema.events import OrderFilledPayload
from arena_kernel.types import round_cash, round_fill_price

from .conftest import CLOSE_TS, CLOSES, LATE, MORNING, priced_bar, snapshot_for, starter


def _run(rounds: dict, book=None):
    return run_spy_buy_and_hold(
        starter() if book is None else book,
        tuple(rounds),
        rounds,
        CLOSES,
        CLOSE_TS,
    )


def test_spy_buy_and_hold_1000_cash_vwap_100_is_qty_9_995_cost_1000() -> None:
    # Same D10 hand-calc: 100 × 1.0005 = 100.0500; floor(1000/100.0500) = 9.995;
    # cost 9.995 × 100.0500 = 999.99975 → 1000.00.
    result = _run({MORNING: snapshot_for(MORNING, priced_bar("SPY", vwap="100"))})
    fills = [
        event.payload
        for event in result.events
        if isinstance(event.payload, OrderFilledPayload)
    ]
    assert len(fills) == 1
    assert fills[0].symbol == "SPY"
    assert fills[0].side == "buy"
    assert fills[0].quantity == Decimal("9.995")
    assert fills[0].notional_usd == Decimal("1000.00")
    assert fills[0].fill_price == Decimal("100.0500")
    assert result.final_portfolio.cash == Decimal("0.00")
    assert result.final_portfolio.positions[0].symbol == "SPY"
    assert result.final_portfolio.positions[0].quantity == Decimal("9.995")
    assert result.final_portfolio.positions[0].cost_basis == Decimal("100.0500")


def test_spy_buy_and_hold_nlv_is_d12_hypothetical_liquidation() -> None:
    # 112 × 0.9995 = 111.9440. 9.995 × 111.9440 = 1118.88028 → 1118.88
    result = _run({MORNING: snapshot_for(MORNING, priced_bar("SPY", vwap="100"))})
    assert result.marked_equity == Decimal("1119.44")
    assert result.nlv == round_cash(Decimal("9.995") * round_fill_price(Decimal("112") * Decimal("0.9995")))
    assert result.nlv == Decimal("1118.88")


def test_spy_buy_and_hold_missing_spy_bar_at_first_window_is_an_error() -> None:
    with pytest.raises(SpyBaselineError) as exc:
        _run({MORNING: snapshot_for(MORNING, priced_bar("AAA"))})
    assert exc.value.path == "SPY"
    assert "SPY" in exc.value.message
    assert "AAA" not in exc.value.message


def test_spy_buy_and_hold_does_not_trade_later_rounds() -> None:
    result = _run(
        {
            MORNING: snapshot_for(MORNING, priced_bar("SPY", vwap="100")),
            LATE: snapshot_for(
                LATE, priced_bar("SPY", vwap="200", bar_start="2026-08-17T15:46:00-04:00")
            ),
        }
    )
    fills = [
        event
        for event in result.events
        if isinstance(event.payload, OrderFilledPayload)
    ]
    assert len(fills) == 1
    assert fills[0].round_id == MORNING
    assert fills[0].payload.fill_price == Decimal("100.0500")
    assert [event.event_type for event in result.events].count("decision_accepted") == 1


def test_spy_buy_and_hold_skips_ineligible_morning_and_buys_at_late() -> None:
    result = _run(
        {
            MORNING: snapshot_for(MORNING, priced_bar("SPY", eligible=False)),
            LATE: snapshot_for(
                LATE, priced_bar("SPY", vwap="100", bar_start="2026-08-17T15:46:00-04:00")
            ),
        }
    )
    fills = [
        event
        for event in result.events
        if isinstance(event.payload, OrderFilledPayload)
    ]
    assert len(fills) == 1
    assert fills[0].round_id == LATE
    assert fills[0].payload.quantity == Decimal("9.995")


def test_spy_buy_and_hold_uses_locked_replica_id() -> None:
    result = _run({MORNING: snapshot_for(MORNING, priced_bar("SPY"))})
    assert result.replica_id == "baseline:spy_buy_and_hold"
    assert result.final_portfolio.replica_id == "baseline:spy_buy_and_hold"
    assert result.final_portfolio.product_id == "baseline"


def test_spy_buy_and_hold_does_not_mutate_input_portfolio() -> None:
    book = starter()
    result = run_spy_buy_and_hold(
        book,
        (MORNING,),
        {MORNING: snapshot_for(MORNING, priced_bar("SPY"))},
        CLOSES,
        CLOSE_TS,
    )
    assert book.replica_id == "product-a-1"
    assert book.product_id == "product-a"
    assert book.cash == Decimal("1000.00")
    assert book.positions == ()
    assert result.final_portfolio is not book


def test_spy_buy_and_hold_rejects_starting_positions() -> None:
    book = starter(
        positions=(
            Position(
                symbol="AAA",
                quantity=Decimal("1.000"),
                cost_basis=Decimal("10.0000"),
            ),
        )
    )
    with pytest.raises(SpyBaselineError) as exc:
        _run({MORNING: snapshot_for(MORNING, priced_bar("SPY"))}, book=book)
    assert exc.value.path == "positions"
    assert book.positions[0].symbol == "AAA"


def test_empty_rounds_still_names_rounds_json() -> None:
    with pytest.raises(FirstWindowError) as exc:
        run_spy_buy_and_hold(starter(), (), {}, CLOSES, CLOSE_TS)
    assert exc.value.path == "rounds.json"
