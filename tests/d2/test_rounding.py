"""D2: fill-price and cash rounding locks."""

from decimal import Decimal

import pytest

from arena_kernel.types import STARTING_CASH, round_cash, round_fill_price


def test_100_times_1_0005_rounds_fill_price_to_4_dp() -> None:
    raw = Decimal("100") * Decimal("1.0005")
    assert raw == Decimal("100.0500")
    assert round_fill_price(raw) == Decimal("100.0500")


def test_fill_price_1_23425_half_even_stays_1_2342() -> None:
    assert round_fill_price("1.23425") == Decimal("1.2342")


def test_fill_price_1_23435_half_even_goes_to_1_2344() -> None:
    assert round_fill_price("1.23435") == Decimal("1.2344")


def test_round_fill_price_rejects_non_positive() -> None:
    with pytest.raises(ValueError, match="positive"):
        round_fill_price("0")


def test_cash_1_225_half_even_rounds_to_1_22() -> None:
    assert round_cash("1.225") == Decimal("1.22")


def test_cash_1_235_half_even_rounds_to_1_24() -> None:
    assert round_cash("1.235") == Decimal("1.24")


def test_starting_cash_is_exactly_1000_00() -> None:
    assert STARTING_CASH == Decimal("1000.00")
    assert round_cash(STARTING_CASH) == STARTING_CASH
