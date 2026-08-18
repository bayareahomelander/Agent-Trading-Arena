"""D2: quantity construction and buy-side floor."""

from decimal import Decimal

import pytest

from arena_kernel.types import floor_to_0_001, parse_quantity


def test_ten_divided_by_three_floors_to_0_001() -> None:
    assert floor_to_0_001(Decimal("10") / Decimal("3")) == Decimal("3.333")


def test_floor_to_0_001_does_not_round_half_up() -> None:
    assert floor_to_0_001("1.2009") == Decimal("1.200")


def test_floor_to_0_001_rejects_negative() -> None:
    with pytest.raises(ValueError, match="negative"):
        floor_to_0_001("-0.001")


def test_parse_quantity_rejects_negative() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        parse_quantity("-1")


def test_parse_quantity_rejects_more_than_3_decimal_places() -> None:
    with pytest.raises(ValueError, match="3 decimal places"):
        parse_quantity("1.0001")


def test_parse_quantity_allows_trailing_zeros_beyond_3_places() -> None:
    assert parse_quantity("1.2000") == Decimal("1.2000")


def test_parse_quantity_accepts_zero() -> None:
    assert parse_quantity("0") == Decimal("0")
