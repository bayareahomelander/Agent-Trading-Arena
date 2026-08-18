"""Mark-to-close, final NLV, and median. Reporting only — does not trade."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Mapping

from arena_kernel.pricing import SELL_MULTIPLIER
from arena_kernel.schema.events import LedgerEvent, make_final_nlv, make_marked_to_close
from arena_kernel.schema.portfolio import Portfolio
from arena_kernel.types import round_cash, round_fill_price


class MissingCloseError(ValueError):
    """An open position has no official close. Do not invent a price."""

    def __init__(self, symbol: str) -> None:
        self.symbol = symbol
        super().__init__(f"missing official close for open position {symbol}")


def mark_to_close(
    portfolio: Portfolio,
    official_closes: Mapping[str, Decimal],
    *,
    timestamp: datetime,
    round_id: str | None = None,
) -> tuple[Decimal, LedgerEvent]:
    """equity = cash + Σ(quantity × official_close)."""
    equity = round_cash(portfolio.cash + _gross_market_value(portfolio, official_closes))
    event = make_marked_to_close(
        replica_id=portfolio.replica_id,
        timestamp=timestamp,
        equity=equity,
        cash=portfolio.cash,
        round_id=round_id,
    )
    return equity, event


def final_nlv(
    portfolio: Portfolio,
    official_closes: Mapping[str, Decimal],
    *,
    timestamp: datetime,
    round_id: str | None = None,
) -> tuple[Decimal, LedgerEvent]:
    """Cash plus a hypothetical 5 bp sell of every position. Not a trade."""
    liquidation = Decimal("0")
    for position in portfolio.positions:
        close = _require_close(position.symbol, official_closes)
        sell_fill = round_fill_price(close * SELL_MULTIPLIER)
        liquidation += position.quantity * sell_fill
    nlv = round_cash(portfolio.cash + liquidation)
    event = make_final_nlv(
        replica_id=portfolio.replica_id,
        timestamp=timestamp,
        nlv=nlv,
        round_id=round_id,
    )
    return nlv, event


def median_nlv(values: list[Decimal] | tuple[Decimal, ...]) -> Decimal:
    """Odd: middle of the sorted list. Even: mean of the two middles, then cash rounding."""
    if not values:
        raise ValueError("median_nlv requires at least one value")
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[mid]
    return round_cash((ordered[mid - 1] + ordered[mid]) / Decimal("2"))


def _gross_market_value(
    portfolio: Portfolio, official_closes: Mapping[str, Decimal]
) -> Decimal:
    total = Decimal("0")
    for position in portfolio.positions:
        close = _require_close(position.symbol, official_closes)
        total += position.quantity * close
    return total


def _require_close(symbol: str, official_closes: Mapping[str, Decimal]) -> Decimal:
    if symbol not in official_closes:
        raise MissingCloseError(symbol)
    return official_closes[symbol]
