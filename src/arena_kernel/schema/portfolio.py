"""portfolio.json — replica cash and positions. Kernel recomputes equity."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping

from arena_kernel.schema._parse import (
    as_mapping,
    join_path,
    require_cash,
    require_cost_basis,
    require_object,
    require_quantity,
    require_schema_version,
    require_str,
)
from arena_kernel.schema._dump import dump_json
from arena_kernel.schema.errors import SchemaError
from arena_kernel.types import format_cash, format_fill_price, format_quantity

_PORTFOLIO_REQUIRED = (
    "schema_version",
    "replica_id",
    "product_id",
    "cash",
    "positions",
)
_POSITION_REQUIRED = ("symbol", "quantity", "cost_basis")


@dataclass(frozen=True)
class Position:
    symbol: str
    quantity: Decimal
    cost_basis: Decimal


@dataclass(frozen=True)
class Portfolio:
    schema_version: str
    replica_id: str
    product_id: str
    cash: Decimal
    positions: tuple[Position, ...]
    reported_equity: Decimal | None


def parse_portfolio(
    data: Mapping[str, Any] | str | bytes, *, path: str = "$"
) -> Portfolio:
    payload = as_mapping(data)
    require_object(
        payload,
        required=_PORTFOLIO_REQUIRED,
        optional=("reported_equity",),
        path=path,
    )
    raw_positions = payload["positions"]
    positions_path = join_path(path, "positions")
    if not isinstance(raw_positions, list):
        raise SchemaError(positions_path, "expected a list")
    positions: list[Position] = []
    seen: set[str] = set()
    for index, item in enumerate(raw_positions):
        item_path = join_path(positions_path, str(index))
        if not isinstance(item, dict):
            raise SchemaError(item_path, "expected an object")
        require_object(item, required=_POSITION_REQUIRED, path=item_path)
        symbol = require_str(item, "symbol", path=item_path)
        if symbol in seen:
            raise SchemaError(join_path(item_path, "symbol"), "duplicate symbol")
        seen.add(symbol)
        positions.append(
            Position(
                symbol=symbol,
                quantity=require_quantity(item, "quantity", path=item_path),
                cost_basis=require_cost_basis(item, "cost_basis", path=item_path),
            )
        )
    reported_equity: Decimal | None = None
    if "reported_equity" in payload and payload["reported_equity"] is not None:
        reported_equity = require_cash(payload, "reported_equity", path=path)
    return Portfolio(
        schema_version=require_schema_version(payload, path=path),
        replica_id=require_str(payload, "replica_id", path=path),
        product_id=require_str(payload, "product_id", path=path),
        cash=require_cash(payload, "cash", path=path),
        positions=tuple(positions),
        reported_equity=reported_equity,
    )


def portfolio_to_dict(portfolio: Portfolio) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": portfolio.schema_version,
        "replica_id": portfolio.replica_id,
        "product_id": portfolio.product_id,
        "cash": format_cash(portfolio.cash),
        "positions": [
            {
                "symbol": position.symbol,
                "quantity": format_quantity(position.quantity),
                "cost_basis": format_fill_price(position.cost_basis),
            }
            for position in portfolio.positions
        ],
    }
    if portfolio.reported_equity is not None:
        payload["reported_equity"] = format_cash(portfolio.reported_equity)
    return payload


def dump_portfolio(portfolio: Portfolio) -> str:
    return dump_json(portfolio_to_dict(portfolio))

