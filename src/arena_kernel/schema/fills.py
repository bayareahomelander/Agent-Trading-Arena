"""fills.json — authoritative prior executions. Empty list is valid."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Mapping

from arena_kernel.schema._parse import (
    as_mapping,
    join_path,
    require_cash,
    require_fill_price,
    require_object,
    require_quantity,
    require_schema_version,
    require_side,
    require_str,
    require_timestamp,
)
from arena_kernel.schema._dump import dump_json
from arena_kernel.schema.errors import SchemaError
from arena_kernel.schema.round_id import parse_round_id
from arena_kernel.types import format_cash, format_et_timestamp, format_fill_price, format_quantity

_FILLS_REQUIRED = ("schema_version", "fills")
_FILL_REQUIRED = (
    "fill_id",
    "round_id",
    "symbol",
    "side",
    "quantity",
    "fill_price",
    "notional_usd",
    "filled_at",
)


@dataclass(frozen=True)
class PriorFill:
    fill_id: str
    round_id: str
    symbol: str
    side: str
    quantity: Decimal
    fill_price: Decimal
    notional_usd: Decimal
    filled_at: datetime


@dataclass(frozen=True)
class FillsFile:
    schema_version: str
    fills: tuple[PriorFill, ...]


def parse_fills(data: Mapping[str, Any] | str | bytes) -> FillsFile:
    payload = as_mapping(data)
    require_object(payload, required=_FILLS_REQUIRED)
    raw_fills = payload["fills"]
    if not isinstance(raw_fills, list):
        raise SchemaError("fills", "expected a list")
    fills: list[PriorFill] = []
    seen: set[str] = set()
    for index, item in enumerate(raw_fills):
        path = join_path("fills", str(index))
        if not isinstance(item, dict):
            raise SchemaError(path, "expected an object")
        require_object(item, required=_FILL_REQUIRED, path=path)
        fill_id = require_str(item, "fill_id", path=path)
        if fill_id in seen:
            raise SchemaError(join_path(path, "fill_id"), "duplicate fill_id")
        seen.add(fill_id)
        quantity = require_quantity(item, "quantity", path=path)
        if quantity <= 0:
            raise SchemaError(join_path(path, "quantity"), "fill quantity must be positive")
        fills.append(
            PriorFill(
                fill_id=fill_id,
                round_id=parse_round_id(
                    require_str(item, "round_id", path=path),
                    path=join_path(path, "round_id"),
                ),
                symbol=require_str(item, "symbol", path=path),
                side=require_side(item, "side", path=path),
                quantity=quantity,
                fill_price=require_fill_price(item, "fill_price", path=path),
                notional_usd=require_cash(item, "notional_usd", path=path),
                filled_at=require_timestamp(item, "filled_at", path=path),
            )
        )
    return FillsFile(
        schema_version=require_schema_version(payload),
        fills=tuple(fills),
    )


def fills_to_dict(book: FillsFile) -> dict[str, Any]:
    return {
        "schema_version": book.schema_version,
        "fills": [
            {
                "fill_id": fill.fill_id,
                "round_id": fill.round_id,
                "symbol": fill.symbol,
                "side": fill.side,
                "quantity": format_quantity(fill.quantity),
                "fill_price": format_fill_price(fill.fill_price),
                "notional_usd": format_cash(fill.notional_usd),
                "filled_at": format_et_timestamp(fill.filled_at),
            }
            for fill in book.fills
        ],
    }


def dump_fills(book: FillsFile) -> str:
    return dump_json(fills_to_dict(book))
