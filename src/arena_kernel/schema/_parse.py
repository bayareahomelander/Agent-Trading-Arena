"""Shared JSON object and field helpers for D3+ schemas."""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from typing import Any, Mapping

from arena_kernel.schema.errors import SchemaError
from arena_kernel.types import (
    FILL_PRICE_QUANTUM,
    as_decimal,
    parse_et_timestamp,
    parse_quantity,
    round_cash,
    round_fill_price,
)

SCHEMA_VERSION: str = "1"

_ALLOWED_SIDES = frozenset({"buy", "sell"})


def join_path(parent: str, child: str) -> str:
    if parent == "$":
        return child
    return f"{parent}.{child}"


def load_json_object(raw: str | bytes) -> dict[str, Any]:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    try:
        data = json.loads(raw, parse_float=Decimal)
    except json.JSONDecodeError as exc:
        raise SchemaError("$", f"invalid JSON: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise SchemaError("$", "expected a JSON object")
    return data


def as_mapping(data: Mapping[str, Any] | str | bytes) -> dict[str, Any]:
    if isinstance(data, (str, bytes)):
        return load_json_object(data)
    if isinstance(data, dict):
        return data
    raise SchemaError("$", "expected a JSON object")


def require_object(
    data: Mapping[str, Any],
    *,
    required: tuple[str, ...],
    optional: tuple[str, ...] = (),
    path: str = "$",
) -> None:
    allowed = set(required) | set(optional)
    for key in required:
        if key not in data:
            raise SchemaError(join_path(path, key), "missing")
    extras = [key for key in data if key not in allowed]
    if extras:
        raise SchemaError(join_path(path, extras[0]), "unknown field")


def require_str(data: Mapping[str, Any], key: str, *, path: str = "$") -> str:
    value = data[key]
    field = join_path(path, key)
    if not isinstance(value, str):
        raise SchemaError(field, "expected a string")
    if value != value.strip() or not value:
        raise SchemaError(field, "must be a non-empty string without padding")
    return value


def require_list(data: Mapping[str, Any], key: str, *, path: str = "$") -> list[Any]:
    value = data[key]
    field = join_path(path, key)
    if not isinstance(value, list):
        raise SchemaError(field, "expected a list")
    return value


def require_schema_version(data: Mapping[str, Any], *, path: str = "$") -> str:
    version = require_str(data, "schema_version", path=path)
    if version != SCHEMA_VERSION:
        raise SchemaError(
            join_path(path, "schema_version"),
            f"unsupported schema_version {version!r}",
        )
    return version


def require_timestamp(data: Mapping[str, Any], key: str, *, path: str = "$") -> datetime:
    field = join_path(path, key)
    value = data[key]
    if not isinstance(value, str):
        raise SchemaError(field, "expected an ISO-8601 string")
    try:
        return parse_et_timestamp(value)
    except ValueError as exc:
        raise SchemaError(field, str(exc)) from exc


def require_cash(data: Mapping[str, Any], key: str, *, path: str = "$") -> Decimal:
    field = join_path(path, key)
    try:
        amount = as_decimal(data[key])
    except (TypeError, ValueError) as exc:
        raise SchemaError(field, str(exc)) from exc
    if amount < 0:
        raise SchemaError(field, "cash must be non-negative")
    rounded = round_cash(amount)
    if amount != rounded:
        raise SchemaError(field, "cash must have at most 2 decimal places")
    return rounded


def require_quantity(data: Mapping[str, Any], key: str, *, path: str = "$") -> Decimal:
    field = join_path(path, key)
    try:
        return parse_quantity(data[key])
    except (TypeError, ValueError) as exc:
        raise SchemaError(field, str(exc)) from exc


def require_fill_price(data: Mapping[str, Any], key: str, *, path: str = "$") -> Decimal:
    field = join_path(path, key)
    try:
        raw = as_decimal(data[key])
        rounded = round_fill_price(raw)
    except (TypeError, ValueError) as exc:
        raise SchemaError(field, str(exc)) from exc
    if raw != rounded:
        raise SchemaError(field, "fill price must have at most 4 decimal places")
    return rounded


def require_cost_basis(data: Mapping[str, Any], key: str, *, path: str = "$") -> Decimal:
    field = join_path(path, key)
    try:
        amount = as_decimal(data[key])
    except (TypeError, ValueError) as exc:
        raise SchemaError(field, str(exc)) from exc
    if amount < 0:
        raise SchemaError(field, "cost basis must be non-negative")
    fitted = amount.quantize(FILL_PRICE_QUANTUM)
    if amount != fitted:
        raise SchemaError(field, "cost basis must have at most 4 decimal places")
    return fitted


def require_side(data: Mapping[str, Any], key: str, *, path: str = "$") -> str:
    side = require_str(data, key, path=path)
    if side not in _ALLOWED_SIDES:
        raise SchemaError(join_path(path, key), "side must be buy or sell")
    return side


def require_positive_int(data: Mapping[str, Any], key: str, *, path: str = "$") -> int:
    field = join_path(path, key)
    value = data[key]
    if isinstance(value, bool):
        raise SchemaError(field, "expected a positive integer")
    if isinstance(value, int):
        number = value
    elif isinstance(value, Decimal) and value == value.to_integral_value():
        number = int(value)
    else:
        raise SchemaError(field, "expected a positive integer")
    if number <= 0:
        raise SchemaError(field, "must be a positive integer")
    return number


def require_decimal(data: Mapping[str, Any], key: str, *, path: str = "$") -> Decimal:
    field = join_path(path, key)
    try:
        return as_decimal(data[key])
    except (TypeError, ValueError) as exc:
        raise SchemaError(field, str(exc)) from exc


def require_positive_decimal(
    data: Mapping[str, Any], key: str, *, path: str = "$"
) -> Decimal:
    field = join_path(path, key)
    amount = require_decimal(data, key, path=path)
    if amount <= 0:
        raise SchemaError(field, "must be positive")
    return amount


def require_non_negative_decimal(
    data: Mapping[str, Any], key: str, *, path: str = "$"
) -> Decimal:
    field = join_path(path, key)
    amount = require_decimal(data, key, path=path)
    if amount < 0:
        raise SchemaError(field, "must be non-negative")
    return amount

