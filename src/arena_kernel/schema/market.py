"""One-minute bars and a round snapshot. Pricing (D9) consumes these as-is."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Mapping

from arena_kernel.schema._parse import (
    as_mapping,
    join_path,
    require_non_negative_decimal,
    require_object,
    require_positive_decimal,
    require_schema_version,
    require_str,
    require_timestamp,
)
from arena_kernel.schema._dump import dump_json
from arena_kernel.schema.clock import Clock, clock_to_dict, parse_clock
from arena_kernel.schema.errors import SchemaError
from arena_kernel.schema.portfolio import Portfolio, parse_portfolio, portfolio_to_dict
from arena_kernel.types import format_et_timestamp

_BAR_ALWAYS = ("symbol", "bar_start")
_BAR_OHLCV = ("open", "high", "low", "close", "volume")
_SNAPSHOT_REQUIRED = ("schema_version", "clock", "bars", "portfolio")


@dataclass(frozen=True)
class Bar:
    symbol: str
    bar_start: datetime
    eligible: bool
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal | None
    volume: Decimal | None
    vwap: Decimal | None


@dataclass(frozen=True)
class Snapshot:
    schema_version: str
    clock: Clock
    bars: tuple[Bar, ...]
    portfolio: Portfolio


def parse_bar(data: Mapping[str, Any] | str | bytes, *, path: str = "$") -> Bar:
    payload = as_mapping(data)
    eligible = _read_eligible(payload, path=path)
    if eligible:
        require_object(
            payload,
            required=(*_BAR_ALWAYS, *_BAR_OHLCV),
            optional=("eligible", "vwap"),
            path=path,
        )
        high = require_positive_decimal(payload, "high", path=path)
        low = require_positive_decimal(payload, "low", path=path)
        open_ = require_positive_decimal(payload, "open", path=path)
        close = require_positive_decimal(payload, "close", path=path)
        volume = require_non_negative_decimal(payload, "volume", path=path)
    else:
        require_object(
            payload,
            required=_BAR_ALWAYS,
            optional=("eligible", "vwap", *_BAR_OHLCV),
            path=path,
        )
        high = _optional_positive(payload, "high", path=path)
        low = _optional_positive(payload, "low", path=path)
        open_ = _optional_positive(payload, "open", path=path)
        close = _optional_positive(payload, "close", path=path)
        volume = _optional_non_negative(payload, "volume", path=path)
    if high is not None and low is not None and high < low:
        raise SchemaError(join_path(path, "high"), "must be >= low")
    return Bar(
        symbol=require_str(payload, "symbol", path=path),
        bar_start=require_timestamp(payload, "bar_start", path=path),
        eligible=eligible,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
        vwap=_optional_positive(payload, "vwap", path=path),
    )


def parse_snapshot(data: Mapping[str, Any] | str | bytes) -> Snapshot:
    payload = as_mapping(data)
    require_object(payload, required=_SNAPSHOT_REQUIRED)
    if not isinstance(payload["clock"], dict):
        raise SchemaError("clock", "expected an object")
    if not isinstance(payload["portfolio"], dict):
        raise SchemaError("portfolio", "expected an object")
    raw_bars = payload["bars"]
    if not isinstance(raw_bars, list):
        raise SchemaError("bars", "expected a list")
    bars: list[Bar] = []
    seen: set[str] = set()
    for index, item in enumerate(raw_bars):
        path = join_path("bars", str(index))
        if not isinstance(item, dict):
            raise SchemaError(path, "expected an object")
        bar = parse_bar(item, path=path)
        if bar.symbol in seen:
            raise SchemaError(join_path(path, "symbol"), "duplicate symbol")
        seen.add(bar.symbol)
        bars.append(bar)
    return Snapshot(
        schema_version=require_schema_version(payload),
        clock=parse_clock(payload["clock"], path="clock"),
        bars=tuple(bars),
        portfolio=parse_portfolio(payload["portfolio"], path="portfolio"),
    )


def bar_to_dict(bar: Bar) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "symbol": bar.symbol,
        "bar_start": format_et_timestamp(bar.bar_start),
    }
    if not bar.eligible:
        payload["eligible"] = False
    for key in ("open", "high", "low", "close", "volume", "vwap"):
        value = getattr(bar, key)
        if value is not None:
            payload[key] = format(value, "f")
    return payload


def snapshot_to_dict(snapshot: Snapshot) -> dict[str, Any]:
    return {
        "schema_version": snapshot.schema_version,
        "clock": clock_to_dict(snapshot.clock),
        "bars": [bar_to_dict(bar) for bar in snapshot.bars],
        "portfolio": portfolio_to_dict(snapshot.portfolio),
    }


def dump_snapshot(snapshot: Snapshot) -> str:
    return dump_json(snapshot_to_dict(snapshot))


def _read_eligible(payload: Mapping[str, Any], *, path: str) -> bool:
    if "eligible" not in payload:
        return True
    value = payload["eligible"]
    if not isinstance(value, bool):
        raise SchemaError(join_path(path, "eligible"), "expected a boolean")
    return value


def _optional_positive(
    payload: Mapping[str, Any], key: str, *, path: str
) -> Decimal | None:
    if key not in payload or payload[key] is None:
        return None
    return require_positive_decimal(payload, key, path=path)


def _optional_non_negative(
    payload: Mapping[str, Any], key: str, *, path: str
) -> Decimal | None:
    if key not in payload or payload[key] is None:
        return None
    return require_non_negative_decimal(payload, key, path=path)
