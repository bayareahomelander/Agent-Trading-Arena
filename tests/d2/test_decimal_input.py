"""D2: no IEEE floats; only finite decimals."""

from decimal import Decimal

import pytest

from arena_kernel.types import as_decimal


def test_as_decimal_accepts_int_str_and_decimal() -> None:
    assert as_decimal(10) == Decimal("10")
    assert as_decimal("10.5") == Decimal("10.5")
    assert as_decimal(Decimal("10.5")) == Decimal("10.5")


def test_as_decimal_rejects_ieee_float() -> None:
    with pytest.raises(TypeError, match="IEEE floats"):
        as_decimal(10.5)  # type: ignore[arg-type]


def test_as_decimal_rejects_bool() -> None:
    with pytest.raises(TypeError, match="bool"):
        as_decimal(True)  # type: ignore[arg-type]


def test_as_decimal_rejects_nan() -> None:
    with pytest.raises(ValueError, match="finite"):
        as_decimal(Decimal("NaN"))


def test_as_decimal_rejects_empty_string() -> None:
    with pytest.raises(ValueError, match="empty"):
        as_decimal("  ")
