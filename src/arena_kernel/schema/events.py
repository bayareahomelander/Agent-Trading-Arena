"""Append-only ledger events. Facts only; matching (D10+) emits these."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Mapping

from arena_kernel.schema._parse import (
    SCHEMA_VERSION,
    as_mapping,
    join_path,
    require_cash,
    require_decimal,
    require_fill_price,
    require_object,
    require_positive_int,
    require_quantity,
    require_schema_version,
    require_side,
    require_str,
    require_timestamp,
)
from arena_kernel.schema.errors import SchemaError
from arena_kernel.schema.round_id import parse_round_id
from arena_kernel.schema._dump import dump_json
from arena_kernel.types import (
    as_decimal,
    format_cash,
    format_et_timestamp,
    format_fill_price,
    format_quantity,
    parse_et_timestamp,
    parse_quantity,
    round_cash,
    round_fill_price,
)

EVENT_TYPES = (
    "decision_accepted",
    "decision_missing",
    "order_rejected",
    "order_filled",
    "marked_to_close",
    "final_nlv",
)

REFERENCE_SOURCES = ("vwap", "midpoint_fallback")

_ROUND_REQUIRED = frozenset(
    {
        "decision_accepted",
        "decision_missing",
        "order_rejected",
        "order_filled",
    }
)

_EVENT_KEYS = (
    "schema_version",
    "type",
    "replica_id",
    "round_id",
    "timestamp",
    "payload",
)

FILL_PAYLOAD_KEYS = (
    "fill_id",
    "symbol",
    "side",
    "quantity",
    "notional_usd",
    "reference_source",
    "bar_id",
    "bar_start",
    "raw_fill",
    "fill_price",
    "cash_before",
    "cash_after",
)

REJECT_PAYLOAD_KEYS = ("reason", "symbol", "side", "priority")


@dataclass(frozen=True)
class DecisionAcceptedPayload:
    action: str
    order_count: int


@dataclass(frozen=True)
class DecisionMissingPayload:
    reason: str


@dataclass(frozen=True)
class OrderRejectedPayload:
    reason: str
    symbol: str | None
    side: str | None
    priority: int | None


@dataclass(frozen=True)
class OrderFilledPayload:
    fill_id: str
    symbol: str
    side: str
    quantity: Decimal
    notional_usd: Decimal
    reference_source: str
    bar_id: str
    bar_start: datetime
    raw_fill: Decimal
    fill_price: Decimal
    cash_before: Decimal
    cash_after: Decimal


@dataclass(frozen=True)
class MarkedToClosePayload:
    equity: Decimal
    cash: Decimal


@dataclass(frozen=True)
class FinalNlvPayload:
    nlv: Decimal


Payload = (
    DecisionAcceptedPayload
    | DecisionMissingPayload
    | OrderRejectedPayload
    | OrderFilledPayload
    | MarkedToClosePayload
    | FinalNlvPayload
)


@dataclass(frozen=True)
class LedgerEvent:
    schema_version: str
    event_type: str
    replica_id: str
    timestamp: datetime
    round_id: str | None
    payload: Payload


def make_order_filled(
    *,
    replica_id: str,
    round_id: str,
    timestamp: datetime,
    fill_id: str,
    symbol: str,
    side: str,
    quantity: Decimal,
    notional_usd: Decimal,
    reference_source: str,
    bar_start: datetime,
    raw_fill: Decimal,
    fill_price: Decimal,
    cash_before: Decimal,
    cash_after: Decimal,
    bar_id: str | None = None,
) -> LedgerEvent:
    if reference_source not in REFERENCE_SOURCES:
        raise SchemaError("payload.reference_source", "must be vwap or midpoint_fallback")
    resolved_bar_id = bar_id or f"{symbol}@{format_et_timestamp(bar_start)}"
    return LedgerEvent(
        schema_version=SCHEMA_VERSION,
        event_type="order_filled",
        replica_id=_identity(replica_id, "replica_id"),
        timestamp=_aware(timestamp, "timestamp"),
        round_id=parse_round_id(round_id),
        payload=OrderFilledPayload(
            fill_id=_identity(fill_id, "payload.fill_id"),
            symbol=_identity(symbol, "payload.symbol"),
            side=_side(side),
            quantity=_positive_quantity(quantity),
            notional_usd=_cash(notional_usd, "payload.notional_usd"),
            reference_source=reference_source,
            bar_id=_identity(resolved_bar_id, "payload.bar_id"),
            bar_start=_aware(bar_start, "payload.bar_start"),
            raw_fill=_positive_raw(raw_fill),
            fill_price=_fill_price(fill_price),
            cash_before=_cash(cash_before, "payload.cash_before"),
            cash_after=_signed_cash(cash_after, "payload.cash_after"),
        ),
    )


def make_order_rejected(
    *,
    replica_id: str,
    round_id: str,
    timestamp: datetime,
    reason: str,
    symbol: str | None = None,
    side: str | None = None,
    priority: int | None = None,
) -> LedgerEvent:
    return LedgerEvent(
        schema_version=SCHEMA_VERSION,
        event_type="order_rejected",
        replica_id=_identity(replica_id, "replica_id"),
        timestamp=_aware(timestamp, "timestamp"),
        round_id=parse_round_id(round_id),
        payload=OrderRejectedPayload(
            reason=_identity(reason, "payload.reason"),
            symbol=_optional_identity(symbol, "payload.symbol"),
            side=_side(side) if side is not None else None,
            priority=_optional_priority(priority),
        ),
    )


def make_decision_accepted(
    *,
    replica_id: str,
    round_id: str,
    timestamp: datetime,
    action: str,
    order_count: int,
) -> LedgerEvent:
    if action not in {"trade", "hold"}:
        raise SchemaError("payload.action", "must be trade or hold")
    if order_count < 0:
        raise SchemaError("payload.order_count", "must be non-negative")
    return _simple_event(
        "decision_accepted",
        replica_id=replica_id,
        round_id=round_id,
        timestamp=timestamp,
        payload=DecisionAcceptedPayload(action=action, order_count=order_count),
    )


def make_decision_missing(
    *, replica_id: str, round_id: str, timestamp: datetime, reason: str
) -> LedgerEvent:
    return _simple_event(
        "decision_missing",
        replica_id=replica_id,
        round_id=round_id,
        timestamp=timestamp,
        payload=DecisionMissingPayload(reason=_identity(reason, "payload.reason")),
    )


def make_marked_to_close(
    *,
    replica_id: str,
    timestamp: datetime,
    equity: Decimal,
    cash: Decimal,
    round_id: str | None = None,
) -> LedgerEvent:
    return LedgerEvent(
        schema_version=SCHEMA_VERSION,
        event_type="marked_to_close",
        replica_id=_identity(replica_id, "replica_id"),
        timestamp=_aware(timestamp, "timestamp"),
        round_id=parse_round_id(round_id) if round_id is not None else None,
        payload=MarkedToClosePayload(
            equity=_cash(equity, "payload.equity"),
            cash=_signed_cash(cash, "payload.cash"),
        ),
    )


def make_final_nlv(
    *,
    replica_id: str,
    timestamp: datetime,
    nlv: Decimal,
    round_id: str | None = None,
) -> LedgerEvent:
    return LedgerEvent(
        schema_version=SCHEMA_VERSION,
        event_type="final_nlv",
        replica_id=_identity(replica_id, "replica_id"),
        timestamp=_aware(timestamp, "timestamp"),
        round_id=parse_round_id(round_id) if round_id is not None else None,
        payload=FinalNlvPayload(nlv=_cash(nlv, "payload.nlv")),
    )


def ledger_event_to_dict(event: LedgerEvent) -> dict[str, Any]:
    return {
        "schema_version": event.schema_version,
        "type": event.event_type,
        "replica_id": event.replica_id,
        "round_id": event.round_id,
        "timestamp": format_et_timestamp(event.timestamp),
        "payload": _payload_to_dict(event.payload),
    }


def dump_ledger_event(event: LedgerEvent) -> str:
    """Stable JSON: fixed key order, decimal strings, ET offsets, trailing newline."""
    return dump_json(ledger_event_to_dict(event))


def parse_ledger_event(data: Mapping[str, Any] | str | bytes) -> LedgerEvent:
    payload_root = as_mapping(data)
    require_object(payload_root, required=_EVENT_KEYS)
    event_type = require_str(payload_root, "type")
    if event_type not in EVENT_TYPES:
        raise SchemaError("type", f"unknown event type {event_type!r}")
    raw_round = payload_root["round_id"]
    if raw_round is None:
        if event_type in _ROUND_REQUIRED:
            raise SchemaError("round_id", "required for this event type")
        round_id = None
    else:
        if not isinstance(raw_round, str):
            raise SchemaError("round_id", "expected a string or null")
        round_id = parse_round_id(raw_round)
    raw_payload = payload_root["payload"]
    if not isinstance(raw_payload, dict):
        raise SchemaError("payload", "expected an object")
    return LedgerEvent(
        schema_version=require_schema_version(payload_root),
        event_type=event_type,
        replica_id=require_str(payload_root, "replica_id"),
        timestamp=require_timestamp(payload_root, "timestamp"),
        round_id=round_id,
        payload=_parse_payload(event_type, raw_payload),
    )


def _simple_event(
    event_type: str,
    *,
    replica_id: str,
    round_id: str,
    timestamp: datetime,
    payload: Payload,
) -> LedgerEvent:
    return LedgerEvent(
        schema_version=SCHEMA_VERSION,
        event_type=event_type,
        replica_id=_identity(replica_id, "replica_id"),
        timestamp=_aware(timestamp, "timestamp"),
        round_id=parse_round_id(round_id),
        payload=payload,
    )


def _payload_to_dict(payload: Payload) -> dict[str, Any]:
    if isinstance(payload, DecisionAcceptedPayload):
        return {"action": payload.action, "order_count": payload.order_count}
    if isinstance(payload, DecisionMissingPayload):
        return {"reason": payload.reason}
    if isinstance(payload, OrderRejectedPayload):
        return {
            "reason": payload.reason,
            "symbol": payload.symbol,
            "side": payload.side,
            "priority": payload.priority,
        }
    if isinstance(payload, OrderFilledPayload):
        return {
            "fill_id": payload.fill_id,
            "symbol": payload.symbol,
            "side": payload.side,
            "quantity": format_quantity(payload.quantity),
            "notional_usd": format_cash(payload.notional_usd),
            "reference_source": payload.reference_source,
            "bar_id": payload.bar_id,
            "bar_start": format_et_timestamp(payload.bar_start),
            "raw_fill": format(payload.raw_fill, "f"),
            "fill_price": format_fill_price(payload.fill_price),
            "cash_before": format_cash(payload.cash_before),
            "cash_after": format_cash(payload.cash_after),
        }
    if isinstance(payload, MarkedToClosePayload):
        return {
            "equity": format_cash(payload.equity),
            "cash": format_cash(payload.cash),
        }
    return {"nlv": format_cash(payload.nlv)}


def _parse_payload(event_type: str, data: Mapping[str, Any]) -> Payload:
    path = "payload"
    if event_type == "decision_accepted":
        require_object(data, required=("action", "order_count"), path=path)
        action = require_str(data, "action", path=path)
        if action not in {"trade", "hold"}:
            raise SchemaError(join_path(path, "action"), "must be trade or hold")
        count = data["order_count"]
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise SchemaError(join_path(path, "order_count"), "must be a non-negative integer")
        return DecisionAcceptedPayload(action=action, order_count=count)
    if event_type == "decision_missing":
        require_object(data, required=("reason",), path=path)
        return DecisionMissingPayload(reason=require_str(data, "reason", path=path))
    if event_type == "order_rejected":
        require_object(
            data,
            required=REJECT_PAYLOAD_KEYS,
            path=path,
        )
        symbol = data["symbol"]
        side = data["side"]
        priority = data["priority"]
        return OrderRejectedPayload(
            reason=require_str(data, "reason", path=path),
            symbol=None if symbol is None else require_str(data, "symbol", path=path),
            side=None if side is None else require_side(data, "side", path=path),
            priority=None if priority is None else require_positive_int(data, "priority", path=path),
        )
    if event_type == "order_filled":
        require_object(data, required=FILL_PAYLOAD_KEYS, path=path)
        source = require_str(data, "reference_source", path=path)
        if source not in REFERENCE_SOURCES:
            raise SchemaError(
                join_path(path, "reference_source"),
                "must be vwap or midpoint_fallback",
            )
        quantity = require_quantity(data, "quantity", path=path)
        if quantity <= 0:
            raise SchemaError(join_path(path, "quantity"), "fill quantity must be positive")
        return OrderFilledPayload(
            fill_id=require_str(data, "fill_id", path=path),
            symbol=require_str(data, "symbol", path=path),
            side=require_side(data, "side", path=path),
            quantity=quantity,
            notional_usd=require_cash(data, "notional_usd", path=path),
            reference_source=source,
            bar_id=require_str(data, "bar_id", path=path),
            bar_start=require_timestamp(data, "bar_start", path=path),
            raw_fill=_parse_raw_fill(data, path),
            fill_price=require_fill_price(data, "fill_price", path=path),
            cash_before=require_cash(data, "cash_before", path=path),
            cash_after=_parse_signed_cash(data, "cash_after", path),
        )
    if event_type == "marked_to_close":
        require_object(data, required=("equity", "cash"), path=path)
        return MarkedToClosePayload(
            equity=require_cash(data, "equity", path=path),
            cash=_parse_signed_cash(data, "cash", path),
        )
    require_object(data, required=("nlv",), path=path)
    return FinalNlvPayload(nlv=require_cash(data, "nlv", path=path))


def _parse_raw_fill(data: Mapping[str, Any], path: str) -> Decimal:
    field = join_path(path, "raw_fill")
    try:
        amount = require_decimal(data, "raw_fill", path=path)
    except SchemaError:
        raise
    if amount <= 0:
        raise SchemaError(field, "must be positive")
    return amount


def _parse_signed_cash(data: Mapping[str, Any], key: str, path: str) -> Decimal:
    """Cash after a fill is a recorded fact and may theoretically be signed."""
    field = join_path(path, key)
    try:
        amount = as_decimal(data[key])
    except (TypeError, ValueError) as exc:
        raise SchemaError(field, str(exc)) from exc
    rounded = round_cash(amount)
    if amount != rounded:
        raise SchemaError(field, "cash must have at most 2 decimal places")
    return rounded


def _identity(value: str, path: str) -> str:
    if not isinstance(value, str) or value != value.strip() or not value:
        raise SchemaError(path, "must be a non-empty string without padding")
    return value


def _optional_identity(value: str | None, path: str) -> str | None:
    if value is None:
        return None
    return _identity(value, path)


def _aware(value: datetime, path: str) -> datetime:
    try:
        return parse_et_timestamp(format_et_timestamp(value))
    except ValueError as exc:
        raise SchemaError(path, str(exc)) from exc


def _side(value: str) -> str:
    if value not in {"buy", "sell"}:
        raise SchemaError("payload.side", "side must be buy or sell")
    return value


def _optional_priority(value: int | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise SchemaError("payload.priority", "must be a positive integer")
    return value


def _positive_quantity(value: Decimal) -> Decimal:
    try:
        quantity = parse_quantity(value)
    except (TypeError, ValueError) as exc:
        raise SchemaError("payload.quantity", str(exc)) from exc
    if quantity <= 0:
        raise SchemaError("payload.quantity", "fill quantity must be positive")
    return quantity


def _fill_price(value: Decimal) -> Decimal:
    try:
        raw = as_decimal(value)
        rounded = round_fill_price(raw)
    except (TypeError, ValueError) as exc:
        raise SchemaError("payload.fill_price", str(exc)) from exc
    if raw != rounded:
        raise SchemaError("payload.fill_price", "fill price must have at most 4 decimal places")
    return rounded


def _positive_raw(value: Decimal) -> Decimal:
    try:
        amount = as_decimal(value)
    except (TypeError, ValueError) as exc:
        raise SchemaError("payload.raw_fill", str(exc)) from exc
    if amount <= 0:
        raise SchemaError("payload.raw_fill", "must be positive")
    return amount


def _cash(value: Decimal, path: str) -> Decimal:
    try:
        amount = as_decimal(value)
    except (TypeError, ValueError) as exc:
        raise SchemaError(path, str(exc)) from exc
    if amount < 0:
        raise SchemaError(path, "cash must be non-negative")
    rounded = round_cash(amount)
    if amount != rounded:
        raise SchemaError(path, "cash must have at most 2 decimal places")
    return rounded


def _signed_cash(value: Decimal, path: str) -> Decimal:
    try:
        amount = as_decimal(value)
    except (TypeError, ValueError) as exc:
        raise SchemaError(path, str(exc)) from exc
    rounded = round_cash(amount)
    if amount != rounded:
        raise SchemaError(path, "cash must have at most 2 decimal places")
    return rounded
