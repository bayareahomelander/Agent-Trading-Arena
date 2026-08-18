"""B3: cash baseline is starting cash. Failures are D12 on an empty book."""

from decimal import Decimal

import pytest

from arena_kernel.baselines import CashBaselineError, run_cash_baseline
from arena_kernel.schema import Position

from .conftest import CLOSE_TS, CLOSES, starter


def test_cash_baseline_nlv_is_starting_cash() -> None:
    result = run_cash_baseline(starter(), CLOSES, CLOSE_TS)
    assert result.marked_equity == Decimal("1000.00")
    assert result.nlv == Decimal("1000.00")
    assert result.final_portfolio.cash == Decimal("1000.00")
    assert result.final_portfolio.positions == ()


def test_cash_baseline_equity_and_nlv_ignore_official_closes() -> None:
    empty = run_cash_baseline(starter(), {}, CLOSE_TS)
    priced = run_cash_baseline(starter(), CLOSES, CLOSE_TS)
    assert empty.marked_equity == priced.marked_equity == Decimal("1000.00")
    assert empty.nlv == priced.nlv == Decimal("1000.00")


def test_cash_baseline_emits_zero_fill_events() -> None:
    result = run_cash_baseline(starter(), CLOSES, CLOSE_TS)
    assert [event.event_type for event in result.events] == [
        "marked_to_close",
        "final_nlv",
    ]
    assert all(event.event_type != "order_filled" for event in result.events)


def test_cash_baseline_uses_locked_replica_id() -> None:
    result = run_cash_baseline(starter(), CLOSES, CLOSE_TS)
    assert result.replica_id == "baseline:cash"
    assert result.final_portfolio.replica_id == "baseline:cash"
    assert result.final_portfolio.product_id == "baseline"


def test_cash_baseline_does_not_mutate_input_portfolio() -> None:
    book = starter()
    result = run_cash_baseline(book, CLOSES, CLOSE_TS)
    assert book.replica_id == "product-a-1"
    assert book.product_id == "product-a"
    assert book.cash == Decimal("1000.00")
    assert book.positions == ()
    assert result.final_portfolio is not book


def test_cash_baseline_rejects_starting_positions() -> None:
    book = starter(
        positions=(
            Position(
                symbol="SPY",
                quantity=Decimal("1.000"),
                cost_basis=Decimal("100.0000"),
            ),
        )
    )
    with pytest.raises(CashBaselineError, match="starting positions"):
        run_cash_baseline(book, CLOSES, CLOSE_TS)
    assert book.positions[0].symbol == "SPY"
