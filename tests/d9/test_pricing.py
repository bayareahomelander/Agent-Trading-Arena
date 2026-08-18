"""D9: reference price and 5 bp slip. No portfolio."""

from decimal import Decimal

import pytest

from arena_kernel.pricing import (
    CannotFill,
    FillQuote,
    REASON_INELIGIBLE,
    REASON_NO_MIDPOINT,
    REASON_NO_REFERENCE,
    SOURCE_MIDPOINT,
    SOURCE_VWAP,
    reference_and_fill_price,
)

from .conftest import bar


def test_vwap_present_uses_source_vwap() -> None:
    quote = reference_and_fill_price(bar(vwap=Decimal("100")), "buy")
    assert isinstance(quote, FillQuote)
    assert quote.source == SOURCE_VWAP
    assert quote.reference == Decimal("100")


def test_vwap_missing_uses_midpoint_fallback() -> None:
    quote = reference_and_fill_price(
        bar(vwap=None, high=Decimal("101"), low=Decimal("99")),
        "buy",
    )
    assert isinstance(quote, FillQuote)
    assert quote.source == SOURCE_MIDPOINT
    assert quote.reference == Decimal("100")


def test_reference_100_buy_fill_rounds_to_100_0500() -> None:
    quote = reference_and_fill_price(bar(vwap=Decimal("100")), "buy")
    assert isinstance(quote, FillQuote)
    assert quote.raw_fill == Decimal("100.0500")
    assert quote.fill == Decimal("100.0500")


def test_reference_100_sell_fill_rounds_to_99_9500() -> None:
    quote = reference_and_fill_price(bar(vwap=Decimal("100")), "sell")
    assert isinstance(quote, FillQuote)
    assert quote.raw_fill == Decimal("99.9500")
    assert quote.fill == Decimal("99.9500")


def test_high_plus_low_zero_cannot_fill() -> None:
    result = reference_and_fill_price(
        bar(vwap=None, high=Decimal("0"), low=Decimal("0")),
        "buy",
    )
    assert isinstance(result, CannotFill)
    assert result.reason == REASON_NO_REFERENCE


def test_non_positive_midpoint_cannot_fill() -> None:
    result = reference_and_fill_price(
        bar(vwap=None, high=Decimal("1"), low=Decimal("-3")),
        "buy",
    )
    assert isinstance(result, CannotFill)
    assert result.reason == REASON_NO_REFERENCE


def test_ineligible_bar_cannot_fill() -> None:
    result = reference_and_fill_price(
        bar(eligible=False, vwap=None, high=None, low=None, open_=None, close=None),
        "buy",
    )
    assert isinstance(result, CannotFill)
    assert result.reason == REASON_INELIGIBLE


def test_missing_high_and_low_without_vwap_cannot_fill() -> None:
    result = reference_and_fill_price(
        bar(vwap=None, high=None, low=None, eligible=True, open_=Decimal("1"), close=Decimal("1")),
        "sell",
    )
    assert isinstance(result, CannotFill)
    assert result.reason == REASON_NO_MIDPOINT


def test_non_positive_vwap_falls_back_to_midpoint() -> None:
    quote = reference_and_fill_price(
        bar(vwap=Decimal("0"), high=Decimal("101"), low=Decimal("99")),
        "buy",
    )
    assert isinstance(quote, FillQuote)
    assert quote.source == SOURCE_MIDPOINT
    assert quote.reference == Decimal("100")


def test_unknown_side_is_caller_error() -> None:
    with pytest.raises(ValueError, match="buy or sell"):
        reference_and_fill_price(bar(vwap=Decimal("100")), "hold")
