"""B5: equal notionals at the first window. Leftover cash is D10 floors, not a rebalance."""

from decimal import Decimal

import pytest

from arena_kernel.baselines import (
    EqualWeightError,
    FirstWindowError,
    equal_weight_notionals,
    run_equal_weight,
)
from arena_kernel.schema import Position
from arena_kernel.schema.events import OrderFilledPayload

from .conftest import CLOSE_TS, CLOSES, LATE, MORNING, priced_bar, snapshot_for, starter


def _run(rounds: dict, universe: tuple[str, ...], book=None):
    return run_equal_weight(
        starter() if book is None else book,
        tuple(rounds),
        rounds,
        CLOSES,
        CLOSE_TS,
        universe,
    )


def _fills(result):
    return [
        event
        for event in result.events
        if isinstance(event.payload, OrderFilledPayload)
    ]


def test_two_symbol_universe_splits_1000_into_500_and_500() -> None:
    assert equal_weight_notionals(Decimal("1000.00"), ("SPY", "AAA")) == (
        ("AAA", Decimal("500.00")),
        ("SPY", Decimal("500.00")),
    )


def test_three_symbol_last_name_gets_the_remainder() -> None:
    assert equal_weight_notionals(Decimal("1000.00"), ("CCC", "AAA", "BBB")) == (
        ("AAA", Decimal("333.33")),
        ("BBB", Decimal("333.33")),
        ("CCC", Decimal("333.34")),
    )


def test_empty_universe_is_an_error() -> None:
    with pytest.raises(EqualWeightError) as exc:
        equal_weight_notionals(Decimal("1000.00"), ())
    assert exc.value.path == "universe"


def test_duplicate_universe_symbol_is_an_error() -> None:
    with pytest.raises(EqualWeightError) as exc:
        equal_weight_notionals(Decimal("1000.00"), ("AAA", "AAA"))
    assert exc.value.path == "universe"


def test_two_symbol_equal_weight_leaves_floor_leftover_cash() -> None:
    # Each 500 / 100.0500 floors to 4.997; cost 499.95; leftover 0.10.
    result = _run(
        {
            MORNING: snapshot_for(
                MORNING, priced_bar("AAA", vwap="100"), priced_bar("SPY", vwap="100")
            )
        },
        ("SPY", "AAA"),
    )
    fills = _fills(result)
    assert [event.payload.symbol for event in fills] == ["AAA", "SPY"]
    assert [event.payload.quantity for event in fills] == [
        Decimal("4.997"),
        Decimal("4.997"),
    ]
    assert [event.payload.notional_usd for event in fills] == [
        Decimal("499.95"),
        Decimal("499.95"),
    ]
    assert result.final_portfolio.cash == Decimal("0.10")


def test_one_symbol_equal_weight_matches_all_in_except_d10_floor() -> None:
    result = _run(
        {MORNING: snapshot_for(MORNING, priced_bar("SPY", vwap="100"))},
        ("SPY",),
    )
    fills = _fills(result)
    assert len(fills) == 1
    assert fills[0].payload.symbol == "SPY"
    assert fills[0].payload.quantity == Decimal("9.995")
    assert fills[0].payload.notional_usd == Decimal("1000.00")
    assert result.final_portfolio.cash == Decimal("0.00")


def test_second_window_does_not_emit_another_buy() -> None:
    result = _run(
        {
            MORNING: snapshot_for(
                MORNING, priced_bar("AAA", vwap="100"), priced_bar("SPY", vwap="100")
            ),
            LATE: snapshot_for(
                LATE,
                priced_bar("AAA", vwap="200", bar_start="2026-08-17T15:46:00-04:00"),
                priced_bar("SPY", vwap="200", bar_start="2026-08-17T15:46:00-04:00"),
            ),
        },
        ("AAA", "SPY"),
    )
    fills = _fills(result)
    assert len(fills) == 2
    assert {event.round_id for event in fills} == {MORNING}
    assert [event.event_type for event in result.events].count("decision_accepted") == 1


def test_missing_eligible_bar_for_a_universe_symbol_is_an_error() -> None:
    with pytest.raises(EqualWeightError) as exc:
        _run(
            {MORNING: snapshot_for(MORNING, priced_bar("AAA", vwap="100"))},
            ("AAA", "SPY"),
        )
    assert exc.value.path == "universe"
    assert "eligible bar" in exc.value.message


def test_equal_weight_uses_locked_replica_id() -> None:
    result = _run(
        {MORNING: snapshot_for(MORNING, priced_bar("SPY", vwap="100"))},
        ("SPY",),
    )
    assert result.replica_id == "baseline:equal_weight"
    assert result.final_portfolio.replica_id == "baseline:equal_weight"
    assert result.final_portfolio.product_id == "baseline"


def test_equal_weight_does_not_mutate_input_portfolio() -> None:
    book = starter()
    result = run_equal_weight(
        book,
        (MORNING,),
        {MORNING: snapshot_for(MORNING, priced_bar("SPY"))},
        CLOSES,
        CLOSE_TS,
        ("SPY",),
    )
    assert book.replica_id == "product-a-1"
    assert book.cash == Decimal("1000.00")
    assert book.positions == ()
    assert result.final_portfolio is not book


def test_equal_weight_rejects_starting_positions() -> None:
    book = starter(
        positions=(
            Position(
                symbol="AAA",
                quantity=Decimal("1.000"),
                cost_basis=Decimal("10.0000"),
            ),
        )
    )
    with pytest.raises(EqualWeightError) as exc:
        _run(
            {MORNING: snapshot_for(MORNING, priced_bar("SPY"))},
            ("SPY",),
            book=book,
        )
    assert exc.value.path == "positions"


def test_empty_rounds_still_names_rounds_json() -> None:
    with pytest.raises(FirstWindowError) as exc:
        run_equal_weight(starter(), (), {}, CLOSES, CLOSE_TS, ("SPY",))
    assert exc.value.path == "rounds.json"
