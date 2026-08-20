"""Polygon/Massive aggregates → C5 records. Default tests inject recorded bytes."""

from __future__ import annotations

import hashlib
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Mapping, Sequence
from urllib.parse import quote

from arena_kernel.marketdata import CommonDataUnavailable
from arena_kernel.schema._parse import load_json_object
from arena_kernel.schema.errors import SchemaError
from arena_kernel.types import (
    EXCHANGE_TZ,
    as_decimal,
    format_et_timestamp,
    parse_et_timestamp,
)
from arena_runtime.vendors.transport import Get, fetch

DOCUMENTATION_URL = (
    "https://massive.com/docs/rest/stocks/aggregates/custom-bars"
)
DOCUMENTATION_RETRIEVED_ON = date(2026, 8, 19)

_OK = frozenset({"OK", "DELAYED"})


class AggregatesVendor:
    """One GET per symbol. Archives raw response bytes, never the API key."""

    def __init__(
        self,
        *,
        base_url: str,
        symbols: Sequence[str],
        timeout: float = 10,
        api_key: str | None = None,
        get: Get | None = None,
    ) -> None:
        if not isinstance(base_url, str) or not base_url.strip():
            raise CommonDataUnavailable("base_url", "must be a non-empty string")
        if not symbols:
            raise CommonDataUnavailable("symbols", "must list at least one symbol")
        self._base = base_url.rstrip("/")
        self._symbols = tuple(symbols)
        self._timeout = timeout
        self._api_key = api_key
        self._get = get
        self.raw_archive: list[tuple[str, bytes, str]] = []

    def minute_bars(
        self,
        symbols: Sequence[str],
        start: datetime,
        end: datetime,
    ) -> tuple[Mapping[str, Any], ...]:
        start_et = _aware(start, "start")
        end_et = _aware(end, "end")
        if start_et > end_et:
            raise ValueError("start must not be after end")
        if not symbols:
            return ()
        out: list[Mapping[str, Any]] = []
        for symbol in symbols:
            rows = _map_minute_results(
                symbol,
                self._results(symbol, "minute", start_et, end_et),
                start_et,
                end_et,
            )
            if not rows:
                raise CommonDataUnavailable(symbol, "missing")
            out.extend(rows)
        return tuple(out)

    def official_closes(self, session_date: date) -> dict[str, Decimal]:
        if type(session_date) is not date:
            raise TypeError("expected a datetime.date")
        start = datetime(
            session_date.year, session_date.month, session_date.day, tzinfo=timezone.utc
        )
        prices: dict[str, Decimal] = {}
        for symbol in self._symbols:
            prices[symbol] = _close_from_results(
                symbol,
                self._results(symbol, "day", start, start, day=session_date),
                session_date,
            )
        return prices

    def _results(
        self,
        symbol: str,
        timespan: str,
        start: datetime,
        end: datetime,
        *,
        day: date | None = None,
    ) -> tuple[Mapping[str, Any], ...]:
        _require_symbol(symbol)
        if timespan == "day":
            if day is None:
                raise CommonDataUnavailable(symbol, "missing")
            frm = to = day.isoformat()
        else:
            frm = str(int(start.timestamp() * 1000))
            to = str(int(end.timestamp() * 1000))
        url = (
            f"{self._base}/v2/aggs/ticker/{quote(symbol, safe='')}"
            f"/range/1/{timespan}/{frm}/{to}?adjusted=false&sort=asc"
        )
        headers: dict[str, str] = {}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        raw = fetch(url, timeout=self._timeout, headers=headers, get=self._get)
        digest = hashlib.sha256(raw).hexdigest()
        self.raw_archive.append((url, raw, digest))
        try:
            payload = load_json_object(raw)
        except SchemaError as exc:
            raise CommonDataUnavailable(symbol, exc.message) from exc
        if payload.get("status") not in _OK:
            raise CommonDataUnavailable(symbol, "missing")
        results = payload.get("results")
        if not isinstance(results, list):
            raise CommonDataUnavailable(symbol, "missing")
        mapped: list[Mapping[str, Any]] = []
        for index, item in enumerate(results):
            if not isinstance(item, dict):
                raise CommonDataUnavailable(
                    f"{symbol}.results.{index}", "expected an object"
                )
            mapped.append(item)
        return tuple(mapped)


def _require_symbol(symbol: str) -> None:
    if not isinstance(symbol, str) or not symbol or "/" in symbol or ".." in symbol:
        raise CommonDataUnavailable("symbol", "invalid")


def _aware(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"{name} must include an offset; do not assume UTC")
    return value.astimezone(EXCHANGE_TZ)


def _bar_start(ms: object) -> datetime:
    try:
        instant = datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc)
    except (TypeError, ValueError, OverflowError) as exc:
        raise CommonDataUnavailable("t", "invalid unix ms") from exc
    return parse_et_timestamp(format_et_timestamp(instant.astimezone(EXCHANGE_TZ)))


def _map_minute_results(
    symbol: str,
    results: Sequence[Mapping[str, Any]],
    start: datetime,
    end: datetime,
) -> tuple[dict[str, Any], ...]:
    out: list[dict[str, Any]] = []
    for index, item in enumerate(results):
        path = f"{symbol}.results.{index}"
        if "t" not in item:
            raise CommonDataUnavailable(f"{path}.t", "missing")
        bar_start = _bar_start(item["t"])
        if bar_start < start or bar_start > end:
            continue
        try:
            record: dict[str, Any] = {
                "symbol": symbol,
                "bar_start": format_et_timestamp(bar_start),
                "open": as_decimal(item["o"]),
                "high": as_decimal(item["h"]),
                "low": as_decimal(item["l"]),
                "close": as_decimal(item["c"]),
                "volume": as_decimal(item["v"]),
            }
        except (KeyError, TypeError, ValueError) as exc:
            raise CommonDataUnavailable(path, "invalid ohlcv") from exc
        if "vw" in item and item["vw"] is not None:
            try:
                record["vwap"] = as_decimal(item["vw"])
            except (TypeError, ValueError) as exc:
                raise CommonDataUnavailable(f"{path}.vw", "invalid") from exc
        out.append(record)
    return tuple(out)


def _close_from_results(
    symbol: str,
    results: Sequence[Mapping[str, Any]],
    session_date: date,
) -> Decimal:
    for index, item in enumerate(results):
        path = f"{symbol}.results.{index}"
        if "c" not in item:
            raise CommonDataUnavailable(f"{path}.c", "missing")
        if "t" in item:
            utc_day = datetime.fromtimestamp(
                int(item["t"]) / 1000, tz=timezone.utc
            ).date()
            if utc_day != session_date:
                continue
        try:
            return as_decimal(item["c"])
        except (TypeError, ValueError, OverflowError) as exc:
            raise CommonDataUnavailable(f"{path}.c", "invalid") from exc
    raise CommonDataUnavailable(symbol, "missing")
