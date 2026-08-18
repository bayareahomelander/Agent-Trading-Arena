"""decision.json — sealed trade or hold. Shape only; D8 adds business rules."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping

from arena_kernel.schema._parse import (
    as_mapping,
    join_path,
    require_cash,
    require_decimal,
    require_list,
    require_object,
    require_positive_int,
    require_quantity,
    require_schema_version,
    require_side,
    require_str,
)
from arena_kernel.schema.errors import SchemaError
from arena_kernel.schema.round_id import parse_round_id

ACTIONS = frozenset({"trade", "hold"})

_DECISION_REQUIRED = (
    "round_id",
    "action",
    "orders",
    "thesis",
    "confidence",
    "risk_note",
    "invalidation",
    "intended_horizon",
)
_ORDER_COMMON = ("priority", "symbol", "side")


@dataclass(frozen=True)
class Order:
    priority: int
    symbol: str
    side: str
    notional_usd: Decimal | None
    quantity: Decimal | None


@dataclass(frozen=True)
class Decision:
    round_id: str
    action: str
    orders: tuple[Order, ...]
    thesis: str
    confidence: Decimal
    risk_note: str
    invalidation: str
    intended_horizon: str
    schema_version: str | None


def parse_decision(data: Mapping[str, Any] | str | bytes) -> Decision:
    payload = as_mapping(data)
    require_object(
        payload,
        required=_DECISION_REQUIRED,
        optional=("schema_version",),
    )
    action = require_str(payload, "action")
    if action not in ACTIONS:
        raise SchemaError("action", "must be trade or hold")
    raw_orders = require_list(payload, "orders")
    if action == "hold" and raw_orders:
        raise SchemaError("orders", "hold decision must have an empty orders list")
    orders = tuple(_parse_order(item, index) for index, item in enumerate(raw_orders))
    schema_version = (
        require_schema_version(payload) if "schema_version" in payload else None
    )
    return Decision(
        round_id=parse_round_id(require_str(payload, "round_id")),
        action=action,
        orders=orders,
        thesis=require_str(payload, "thesis"),
        confidence=require_decimal(payload, "confidence"),
        risk_note=require_str(payload, "risk_note"),
        invalidation=require_str(payload, "invalidation"),
        intended_horizon=require_str(payload, "intended_horizon"),
        schema_version=schema_version,
    )


def _parse_order(item: Any, index: int) -> Order:
    path = join_path("orders", str(index))
    if not isinstance(item, dict):
        raise SchemaError(path, "expected an object")
    if "side" not in item:
        raise SchemaError(join_path(path, "side"), "missing")
    side = require_side(item, "side", path=path)
    if side == "buy":
        if "quantity" in item:
            raise SchemaError(join_path(path, "quantity"), "buy must not include quantity")
        require_object(
            item,
            required=(*_ORDER_COMMON, "notional_usd"),
            path=path,
        )
        return Order(
            priority=require_positive_int(item, "priority", path=path),
            symbol=require_str(item, "symbol", path=path),
            side=side,
            notional_usd=require_cash(item, "notional_usd", path=path),
            quantity=None,
        )
    if "notional_usd" in item:
        raise SchemaError(
            join_path(path, "notional_usd"),
            "sell must not include notional_usd",
        )
    require_object(
        item,
        required=(*_ORDER_COMMON, "quantity"),
        path=path,
    )
    return Order(
        priority=require_positive_int(item, "priority", path=path),
        symbol=require_str(item, "symbol", path=path),
        side=side,
        notional_usd=None,
        quantity=require_quantity(item, "quantity", path=path),
    )
