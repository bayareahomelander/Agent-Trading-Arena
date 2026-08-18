"""Apply one order (D10) or a sealed batch (D11) to a portfolio.

Cash and positions change here. Facts are emitted as D6 ledger events.
"""

from __future__ import annotations

from datetime import datetime
from decimal import ROUND_HALF_EVEN, Decimal

from arena_kernel.pricing import CannotFill, reference_and_fill_price
from arena_kernel.schema.decision import Decision, Order
from arena_kernel.schema.events import (
    LedgerEvent,
    make_decision_accepted,
    make_decision_missing,
    make_order_filled,
    make_order_rejected,
)
from arena_kernel.schema.market import Bar, Snapshot
from arena_kernel.schema.portfolio import Portfolio, Position
from arena_kernel.types import FILL_PRICE_QUANTUM, floor_to_0_001, round_cash
from arena_kernel.validate import validate_decision

REASON_INSUFFICIENT_CASH = "insufficient_cash"
REASON_INSUFFICIENT_HOLDINGS = "insufficient_holdings"
REASON_BUY_QTY_ZERO = "buy_quantity_zero"
REASON_BUY_NOTIONAL = "buy_notional_not_positive"
REASON_SELL_QUANTITY = "sell_quantity_not_positive"
REASON_SYMBOL_MISMATCH = "symbol_mismatch"


def apply_decision(
    portfolio: Portfolio,
    decision: Decision,
    snapshot: Snapshot,
) -> tuple[tuple[LedgerEvent, ...], Portfolio]:
    """Apply a sealed batch. Sells first, then buys; one reject does not stop later orders."""
    universe = frozenset(bar.symbol for bar in snapshot.bars)
    round_id = snapshot.clock.round_id
    timestamp = snapshot.clock.deadline
    report = validate_decision(portfolio=portfolio, decision=decision, universe=universe, expected_round_id=round_id)
    if not report.file_accepted:
        reason = report.issues[0].code if report.issues else "invalid_decision"
        missing = make_decision_missing(
            replica_id=portfolio.replica_id,
            round_id=round_id,
            timestamp=timestamp,
            reason=reason,
        )
        return (missing,), portfolio

    events: list[LedgerEvent] = [
        make_decision_accepted(
            replica_id=portfolio.replica_id,
            round_id=round_id,
            timestamp=timestamp,
            action=decision.action,
            order_count=len(report.accepted_orders),
        )
    ]
    for issue in report.issues:
        order = (
            decision.orders[issue.order_index]
            if issue.order_index is not None
            else None
        )
        events.append(
            make_order_rejected(
                replica_id=portfolio.replica_id,
                round_id=round_id,
                timestamp=timestamp,
                reason=issue.code,
                symbol=order.symbol if order else None,
                side=order.side if order else None,
                priority=order.priority if order else None,
            )
        )

    bars = {bar.symbol: bar for bar in snapshot.bars}
    sells = sorted(
        (order for order in report.accepted_orders if order.side == "sell"),
        key=lambda order: order.priority,
    )
    buys = sorted(
        (order for order in report.accepted_orders if order.side == "buy"),
        key=lambda order: order.priority,
    )
    current = portfolio
    for sequence, order in enumerate((*sells, *buys), start=1):
        event, current = apply_order(
            current,
            order,
            bars[order.symbol],
            round_id=round_id,
            timestamp=timestamp,
            fill_id=f"{round_id}:{sequence}",
        )
        events.append(event)
    return tuple(events), current


def apply_order(
    portfolio: Portfolio,
    order: Order,
    bar: Bar,
    *,
    round_id: str,
    timestamp: datetime,
    fill_id: str,
) -> tuple[LedgerEvent, Portfolio]:
    """Apply one order. Never mutates `portfolio`."""
    rejected = _precheck(order, bar)
    if rejected is not None:
        return _reject(portfolio, order, round_id, timestamp, rejected), portfolio

    quote = reference_and_fill_price(bar, order.side)
    if isinstance(quote, CannotFill):
        return _reject(portfolio, order, round_id, timestamp, quote.reason), portfolio

    if order.side == "buy":
        return _apply_buy(portfolio, order, bar, quote, round_id, timestamp, fill_id)
    return _apply_sell(portfolio, order, bar, quote, round_id, timestamp, fill_id)


def _precheck(order: Order, bar: Bar) -> str | None:
    if bar.symbol != order.symbol:
        return REASON_SYMBOL_MISMATCH
    if order.side == "buy":
        if order.notional_usd is None or order.notional_usd <= 0:
            return REASON_BUY_NOTIONAL
        return None
    if order.quantity is None or order.quantity <= 0:
        return REASON_SELL_QUANTITY
    return None


def _apply_buy(
    portfolio: Portfolio,
    order: Order,
    bar: Bar,
    quote,
    round_id: str,
    timestamp: datetime,
    fill_id: str,
) -> tuple[LedgerEvent, Portfolio]:
    assert order.notional_usd is not None
    quantity = floor_to_0_001(order.notional_usd / quote.fill)
    if quantity == 0:
        return _reject(portfolio, order, round_id, timestamp, REASON_BUY_QTY_ZERO), portfolio
    cost = round_cash(quantity * quote.fill)
    if cost > portfolio.cash:
        return (
            _reject(portfolio, order, round_id, timestamp, REASON_INSUFFICIENT_CASH),
            portfolio,
        )
    new_cash = round_cash(portfolio.cash - cost)
    new_positions = _add_shares(portfolio.positions, order.symbol, quantity, quote.fill)
    updated = _replace_book(portfolio, new_cash, new_positions)
    return (
        _fill(
            portfolio,
            updated,
            order,
            bar,
            quote,
            quantity,
            cost,
            round_id,
            timestamp,
            fill_id,
        ),
        updated,
    )


def _apply_sell(
    portfolio: Portfolio,
    order: Order,
    bar: Bar,
    quote,
    round_id: str,
    timestamp: datetime,
    fill_id: str,
) -> tuple[LedgerEvent, Portfolio]:
    assert order.quantity is not None
    held = _held(portfolio, order.symbol)
    if order.quantity > held:
        return (
            _reject(portfolio, order, round_id, timestamp, REASON_INSUFFICIENT_HOLDINGS),
            portfolio,
        )
    proceeds = round_cash(order.quantity * quote.fill)
    new_cash = round_cash(portfolio.cash + proceeds)
    new_positions = _remove_shares(portfolio.positions, order.symbol, order.quantity)
    updated = _replace_book(portfolio, new_cash, new_positions)
    return (
        _fill(
            portfolio,
            updated,
            order,
            bar,
            quote,
            order.quantity,
            proceeds,
            round_id,
            timestamp,
            fill_id,
        ),
        updated,
    )


def realized_pnl(sell_fill: Decimal, average_cost: Decimal, quantity: Decimal) -> Decimal:
    """(sell_fill − average_cost) × quantity. Not written on the D6 fill event."""
    return (sell_fill - average_cost) * quantity


def _add_shares(
    positions: tuple[Position, ...],
    symbol: str,
    quantity: Decimal,
    fill: Decimal,
) -> tuple[Position, ...]:
    updated: list[Position] = []
    found = False
    for position in positions:
        if position.symbol != symbol:
            updated.append(position)
            continue
        found = True
        new_qty = position.quantity + quantity
        new_basis = (
            (position.quantity * position.cost_basis) + (quantity * fill)
        ) / new_qty
        updated.append(
            Position(
                symbol=symbol,
                quantity=new_qty,
                cost_basis=new_basis.quantize(
                    FILL_PRICE_QUANTUM, rounding=ROUND_HALF_EVEN
                ),
            )
        )
    if not found:
        updated.append(
            Position(
                symbol=symbol,
                quantity=quantity,
                cost_basis=fill.quantize(FILL_PRICE_QUANTUM, rounding=ROUND_HALF_EVEN),
            )
        )
    return tuple(updated)


def _remove_shares(
    positions: tuple[Position, ...],
    symbol: str,
    quantity: Decimal,
) -> tuple[Position, ...]:
    updated: list[Position] = []
    for position in positions:
        if position.symbol != symbol:
            updated.append(position)
            continue
        remaining = position.quantity - quantity
        if remaining == 0:
            continue
        updated.append(
            Position(
                symbol=symbol,
                quantity=remaining,
                cost_basis=position.cost_basis,
            )
        )
    return tuple(updated)


def _held(portfolio: Portfolio, symbol: str) -> Decimal:
    for position in portfolio.positions:
        if position.symbol == symbol:
            return position.quantity
    return Decimal("0")


def _replace_book(
    portfolio: Portfolio, cash: Decimal, positions: tuple[Position, ...]
) -> Portfolio:
    return Portfolio(
        schema_version=portfolio.schema_version,
        replica_id=portfolio.replica_id,
        product_id=portfolio.product_id,
        cash=cash,
        positions=positions,
        reported_equity=None,
    )


def _reject(
    portfolio: Portfolio,
    order: Order,
    round_id: str,
    timestamp: datetime,
    reason: str,
) -> LedgerEvent:
    return make_order_rejected(
        replica_id=portfolio.replica_id,
        round_id=round_id,
        timestamp=timestamp,
        reason=reason,
        symbol=order.symbol,
        side=order.side,
        priority=order.priority,
    )


def _fill(
    before: Portfolio,
    after: Portfolio,
    order: Order,
    bar: Bar,
    quote,
    quantity: Decimal,
    notional: Decimal,
    round_id: str,
    timestamp: datetime,
    fill_id: str,
) -> LedgerEvent:
    return make_order_filled(
        replica_id=before.replica_id,
        round_id=round_id,
        timestamp=timestamp,
        fill_id=fill_id,
        symbol=order.symbol,
        side=order.side,
        quantity=quantity,
        notional_usd=notional,
        reference_source=quote.source,
        bar_start=bar.bar_start,
        raw_fill=quote.raw_fill,
        fill_price=quote.fill,
        cash_before=before.cash,
        cash_after=after.cash,
    )
