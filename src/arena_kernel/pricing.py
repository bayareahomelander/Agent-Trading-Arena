"""Reference price and slippage.

Fill price lives here. Matching (D10) applies it; validate does not.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from arena_kernel.schema.market import Bar
from arena_kernel.types import round_fill_price

SOURCE_VWAP = "vwap"
SOURCE_MIDPOINT = "midpoint_fallback"

BUY_MULTIPLIER = Decimal("1.0005")
SELL_MULTIPLIER = Decimal("0.9995")

REASON_INELIGIBLE = "ineligible_bar"
REASON_NO_REFERENCE = "non_positive_reference"
REASON_NO_MIDPOINT = "missing_midpoint"


@dataclass(frozen=True)
class FillQuote:
    reference: Decimal
    source: str
    raw_fill: Decimal
    fill: Decimal
    side: str


@dataclass(frozen=True)
class CannotFill:
    reason: str


def reference_and_fill_price(bar: Bar, side: str) -> FillQuote | CannotFill:
    """VWAP if usable, else midpoint. Then 5 bp adverse slip, 4 d.p. half even."""
    if side not in {"buy", "sell"}:
        raise ValueError("side must be buy or sell")
    if not bar.eligible:
        return CannotFill(reason=REASON_INELIGIBLE)
    picked = _reference(bar)
    if isinstance(picked, CannotFill):
        return picked
    reference, source = picked
    multiplier = BUY_MULTIPLIER if side == "buy" else SELL_MULTIPLIER
    raw_fill = reference * multiplier
    return FillQuote(
        reference=reference,
        source=source,
        raw_fill=raw_fill,
        fill=round_fill_price(raw_fill),
        side=side,
    )


def _reference(bar: Bar) -> tuple[Decimal, str] | CannotFill:
    if bar.vwap is not None and _usable_price(bar.vwap):
        return bar.vwap, SOURCE_VWAP
    if bar.high is None or bar.low is None:
        return CannotFill(reason=REASON_NO_MIDPOINT)
    midpoint = (bar.high + bar.low) / Decimal("2")
    if not _usable_price(midpoint):
        return CannotFill(reason=REASON_NO_REFERENCE)
    return midpoint, SOURCE_MIDPOINT


def _usable_price(value: Decimal | None) -> bool:
    return value is not None and value.is_finite() and value > 0
