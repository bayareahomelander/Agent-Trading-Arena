"""Decision business rules. Does not move cash or look up fill prices."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from arena_kernel.schema.decision import Decision, Order
from arena_kernel.schema.portfolio import Portfolio

MAX_ORDERS = 20

CODE_ROUND_ID = "round_id_mismatch"
CODE_ACTION = "unknown_action"
CODE_HOLD_ORDERS = "hold_has_orders"
CODE_CONFIDENCE = "confidence_out_of_range"
CODE_MAX_ORDERS = "max_orders"
CODE_UNIVERSE = "symbol_not_in_universe"
CODE_BUY_NOTIONAL = "buy_notional_not_positive"
CODE_SELL_QUANTITY = "sell_quantity_not_positive"
CODE_CONTRADICTION = "contradictory_order"


@dataclass(frozen=True)
class ValidationIssue:
    path: str
    code: str
    message: str
    order_index: int | None = None


@dataclass(frozen=True)
class DecisionValidation:
    file_accepted: bool
    accepted_orders: tuple[Order, ...]
    issues: tuple[ValidationIssue, ...]


def validate_decision(
    decision: Decision,
    portfolio: Portfolio,
    universe: frozenset[str] | set[str] | tuple[str, ...],
    expected_round_id: str,
) -> DecisionValidation:
    """Return which orders may proceed. `portfolio` is unused until D10."""
    del portfolio
    symbols = frozenset(universe)
    file_issues = list(_file_issues(decision, expected_round_id))
    if file_issues:
        return DecisionValidation(
            file_accepted=False,
            accepted_orders=(),
            issues=tuple(file_issues),
        )

    order_issues: list[ValidationIssue] = []
    candidates: list[tuple[int, Order]] = []
    for index, order in enumerate(decision.orders):
        if index >= MAX_ORDERS:
            order_issues.append(
                ValidationIssue(
                    path=f"orders.{index}",
                    code=CODE_MAX_ORDERS,
                    message=f"order index {index} exceeds the {MAX_ORDERS} order cap",
                    order_index=index,
                )
            )
            continue
        issue = _independent_order_issue(order, index, symbols)
        if issue is not None:
            order_issues.append(issue)
            continue
        candidates.append((index, order))

    kept_indexes, contradiction_issues = _drop_later_same_symbol(candidates)
    order_issues.extend(contradiction_issues)
    accepted = tuple(
        order for index, order in candidates if index in kept_indexes
    )
    return DecisionValidation(
        file_accepted=True,
        accepted_orders=accepted,
        issues=tuple(order_issues),
    )


def _file_issues(decision: Decision, expected_round_id: str) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if decision.round_id != expected_round_id:
        issues.append(
            ValidationIssue(
                path="round_id",
                code=CODE_ROUND_ID,
                message=(
                    f"round_id {decision.round_id!r} does not match "
                    f"{expected_round_id!r}"
                ),
            )
        )
    if decision.action not in {"trade", "hold"}:
        issues.append(
            ValidationIssue(
                path="action",
                code=CODE_ACTION,
                message=f"unknown action {decision.action!r}",
            )
        )
    if decision.action == "hold" and decision.orders:
        issues.append(
            ValidationIssue(
                path="orders",
                code=CODE_HOLD_ORDERS,
                message="hold decision must not include orders",
            )
        )
    if not Decimal("0") <= decision.confidence <= Decimal("1"):
        issues.append(
            ValidationIssue(
                path="confidence",
                code=CODE_CONFIDENCE,
                message="confidence must be between 0 and 1 inclusive",
            )
        )
    return issues


def _independent_order_issue(
    order: Order, index: int, universe: frozenset[str]
) -> ValidationIssue | None:
    path = f"orders.{index}"
    if order.symbol not in universe:
        return ValidationIssue(
            path=f"{path}.symbol",
            code=CODE_UNIVERSE,
            message=f"{order.symbol!r} is not in the frozen universe",
            order_index=index,
        )
    if order.side == "buy":
        notional = order.notional_usd
        if notional is None or notional <= 0:
            return ValidationIssue(
                path=f"{path}.notional_usd",
                code=CODE_BUY_NOTIONAL,
                message="buy notional_usd must be > 0",
                order_index=index,
            )
        return None
    quantity = order.quantity
    if quantity is None or quantity <= 0:
        return ValidationIssue(
            path=f"{path}.quantity",
            code=CODE_SELL_QUANTITY,
            message="sell quantity must be > 0",
            order_index=index,
        )
    return None


def _drop_later_same_symbol(
    candidates: list[tuple[int, Order]],
) -> tuple[set[int], list[ValidationIssue]]:
    """Keep the first order per symbol by ascending priority, then file order."""
    kept: set[int] = set()
    winner_index: dict[str, int] = {}
    issues: list[ValidationIssue] = []
    ranked = sorted(candidates, key=lambda item: (item[1].priority, item[0]))
    for index, order in ranked:
        previous = winner_index.get(order.symbol)
        if previous is None:
            winner_index[order.symbol] = index
            kept.add(index)
            continue
        issues.append(
            ValidationIssue(
                path=f"orders.{index}",
                code=CODE_CONTRADICTION,
                message=(
                    f"contradicts earlier {order.symbol} order at "
                    f"orders.{previous}; later order by priority is rejected"
                ),
                order_index=index,
            )
        )
    return kept, issues
