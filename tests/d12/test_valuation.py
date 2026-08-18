"""D12: reporting math. Do not change matching if these fail."""

from decimal import Decimal

import pytest

from arena_kernel.ledger import MissingCloseError, final_nlv, mark_to_close, median_nlv
from arena_kernel.schema import Portfolio, Position
from arena_kernel.schema.events import FinalNlvPayload, MarkedToClosePayload
from arena_kernel.types import parse_et_timestamp

TS = parse_et_timestamp("2026-08-17T16:00:00-04:00")


def book(cash: str, *positions: Position) -> Portfolio:
    return Portfolio(
        schema_version="1",
        replica_id="product-a-1",
        product_id="product-a",
        cash=Decimal(cash),
        positions=positions,
        reported_equity=None,
    )


def test_readme_50_shares_at_15_marks_equity_1250() -> None:
    # Didactic README path uses a $10 fill with no slip in the story.
    # Mark uses official close only: 500 cash + 50 × 15 = 1250.
    portfolio = book(
        "500.00",
        Position(symbol="AAA", quantity=Decimal("50"), cost_basis=Decimal("10.0000")),
    )
    equity, event = mark_to_close(
        portfolio, {"AAA": Decimal("15")}, timestamp=TS
    )
    assert equity == Decimal("1250.00")
    assert isinstance(event.payload, MarkedToClosePayload)
    assert event.payload.equity == Decimal("1250.00")
    assert event.payload.cash == Decimal("500.00")


def test_final_nlv_after_5bp_on_50_shares_at_15_is_1249_62() -> None:
    # 15 × 0.9995 = 14.9925. 50 × 14.9925 = 749.625. + 500 cash → 1249.625 → 1249.62
    portfolio = book(
        "500.00",
        Position(symbol="AAA", quantity=Decimal("50"), cost_basis=Decimal("10.0000")),
    )
    nlv, event = final_nlv(portfolio, {"AAA": Decimal("15")}, timestamp=TS)
    assert nlv == Decimal("1249.62")
    assert isinstance(event.payload, FinalNlvPayload)
    assert event.payload.nlv == Decimal("1249.62")


def test_missing_official_close_is_an_error_not_a_guess() -> None:
    portfolio = book(
        "500.00",
        Position(symbol="AAA", quantity=Decimal("50"), cost_basis=Decimal("10.0000")),
    )
    with pytest.raises(MissingCloseError) as exc:
        mark_to_close(portfolio, {}, timestamp=TS)
    assert exc.value.symbol == "AAA"


def test_cash_only_mark_and_nlv_equal_cash() -> None:
    portfolio = book("1000.00")
    equity, _ = mark_to_close(portfolio, {}, timestamp=TS)
    nlv, _ = final_nlv(portfolio, {}, timestamp=TS)
    assert equity == Decimal("1000.00")
    assert nlv == Decimal("1000.00")


def test_median_nlv_odd_count_is_the_middle() -> None:
    assert median_nlv(
        [Decimal("900.00"), Decimal("1100.00"), Decimal("1000.00")]
    ) == Decimal("1000.00")


def test_median_nlv_even_count_means_the_two_middles_then_cash_round() -> None:
    assert median_nlv([Decimal("1000.00"), Decimal("1100.00")]) == Decimal("1050.00")
    assert median_nlv([Decimal("1000.01"), Decimal("1000.02")]) == Decimal("1000.02")


def test_median_nlv_rejects_empty() -> None:
    with pytest.raises(ValueError, match="at least one"):
        median_nlv([])
