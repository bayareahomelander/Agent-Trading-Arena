"""Numeric and time primitives.

D2: decimal money, quantity, fill-price rounding, and ET timestamps.
No IEEE floats. No orders, bars, or files.
"""

from __future__ import annotations

from datetime import datetime
from decimal import ROUND_FLOOR, ROUND_HALF_EVEN, Decimal, InvalidOperation
from typing import Final
from zoneinfo import ZoneInfo

DecimalInput = Decimal | int | str

EXCHANGE_TIMEZONE_NAME: Final[str] = "America/New_York"
EXCHANGE_TZ: Final[ZoneInfo] = ZoneInfo(EXCHANGE_TIMEZONE_NAME)

QUANTITY_QUANTUM: Final[Decimal] = Decimal("0.001")
FILL_PRICE_QUANTUM: Final[Decimal] = Decimal("0.0001")
CASH_QUANTUM: Final[Decimal] = Decimal("0.01")
STARTING_CASH: Final[Decimal] = Decimal("1000.00")


def as_decimal(value: DecimalInput) -> Decimal:
    """Convert int, str, or Decimal to a finite Decimal. Reject floats."""
    if isinstance(value, bool):
        raise TypeError("bool is not a decimal input")
    if isinstance(value, float):
        raise TypeError("IEEE floats are not allowed")
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, int):
        result = Decimal(value)
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValueError("empty decimal string")
        try:
            result = Decimal(text)
        except InvalidOperation as exc:
            raise ValueError(f"invalid decimal string: {value!r}") from exc
    else:
        raise TypeError(f"unsupported decimal input: {type(value).__name__}")
    if not result.is_finite():
        raise ValueError("decimal must be finite")
    return result


def floor_to_0_001(value: DecimalInput) -> Decimal:
    """Floor a non-negative amount to 0.001 (buy quantity)."""
    amount = as_decimal(value)
    if amount < 0:
        raise ValueError("cannot floor a negative amount to a quantity")
    return amount.quantize(QUANTITY_QUANTUM, rounding=ROUND_FLOOR)


def parse_quantity(value: DecimalInput) -> Decimal:
    """Accept a non-negative quantity with at most 3 decimal places."""
    quantity = as_decimal(value)
    if quantity < 0:
        raise ValueError("quantity must be non-negative")
    if quantity != quantity.quantize(QUANTITY_QUANTUM, rounding=ROUND_FLOOR):
        raise ValueError("quantity may have at most 3 decimal places")
    return quantity


def round_fill_price(value: DecimalInput) -> Decimal:
    """Round a positive fill price to 4 decimal places, half even."""
    price = as_decimal(value)
    if price <= 0:
        raise ValueError("fill price must be positive")
    return price.quantize(FILL_PRICE_QUANTUM, rounding=ROUND_HALF_EVEN)


def round_cash(value: DecimalInput) -> Decimal:
    """Round cash to 2 decimal places, half even."""
    return as_decimal(value).quantize(CASH_QUANTUM, rounding=ROUND_HALF_EVEN)


def parse_et_timestamp(value: str) -> datetime:
    """Parse ISO-8601 with a required offset; return America/New_York."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("timestamp must be a non-empty string")
    raw = value.strip()
    if raw.endswith("Z") or raw.endswith("z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError(f"invalid ISO-8601 timestamp: {value!r}") from exc
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include an offset; do not assume UTC")
    return parsed.astimezone(EXCHANGE_TZ)


def format_et_timestamp(value: datetime) -> str:
    """Format an aware datetime as ISO-8601 seconds with the ET offset."""
    if value.tzinfo is None:
        raise ValueError("datetime must be timezone-aware; do not assume UTC")
    return value.astimezone(EXCHANGE_TZ).isoformat(timespec="seconds")


def format_cash(value: Decimal) -> str:
    """Cash as a 2-decimal string (half-even already applied by callers)."""
    return format(value.quantize(CASH_QUANTUM), "f")


def format_fill_price(value: Decimal) -> str:
    """Fill price as a 4-decimal string."""
    return format(value.quantize(FILL_PRICE_QUANTUM), "f")


def format_quantity(value: Decimal) -> str:
    """Share quantity as a 3-decimal string."""
    return format(value.quantize(QUANTITY_QUANTUM), "f")
