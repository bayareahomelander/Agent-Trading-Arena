"""Market-data vendor adapter.

C1 records locked terms. C5 is the vendor protocol and fixture vendor.
C6 maps vendor records to D5 bars. C7/C8 publish snapshots.

Bar fetches live here. Do not compute session days or round times.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Final, Mapping, Protocol, Sequence, runtime_checkable

from arena_kernel.calendar import (
    Calendar,
    ScheduledRound,
    clock_for_round,
    is_trading_day,
    rounds_for_day,
    scheduled_close,
)
from arena_kernel.schema._dump import dump_json
from arena_kernel.schema._parse import (
    SCHEMA_VERSION,
    load_json_object,
    require_list,
    require_object,
    require_schema_version,
)
from arena_kernel.schema.clock import dump_clock
from arena_kernel.schema.errors import SchemaError
from arena_kernel.schema.fills import FillsFile
from arena_kernel.schema.market import Bar, Snapshot, bar_to_dict, parse_bar
from arena_kernel.schema.portfolio import Portfolio, dump_portfolio
from arena_kernel.types import (
    EXCHANGE_TZ,
    as_decimal,
    format_cash,
    format_et_timestamp,
    parse_et_timestamp,
)
from arena_kernel.workspace import write_replica_workspace

# Locked C1 terms. Meanings are names, not implementations.
MARKETDATA_TERMS: Final[tuple[str, ...]] = (
    "vendor",
    "common_data_unavailable",
)

MARKETDATA_MEANINGS: Final[Mapping[str, str]] = {
    "vendor": "The single frozen market-data source for a tape",
    "common_data_unavailable": (
        "Vendor cannot supply the common snapshot; no fills"
    ),
}

_BARS_FILE: Final[str] = "bars.json"
_CLOSES_FILE: Final[str] = "closes.json"
TAPE_ROUNDS_DIR: Final[str] = "rounds"
TAPE_REPLICAS_DIR: Final[str] = "replicas"
TAPE_RAW_DIR: Final[str] = "raw"
TAPE_CLOCK_FILE: Final[str] = "clock.json"
TAPE_BARS_FILE: Final[str] = "bars.json"


class CommonDataUnavailable(ValueError):
    """Vendor cannot supply the common snapshot; no fills."""

    def __init__(self, path: str, message: str) -> None:
        self.path = path
        self.message = message
        super().__init__(f"{path}: {message}")


@runtime_checkable
class Vendor(Protocol):
    """Single frozen market-data source for a tape. No HTTP in tests."""

    def minute_bars(
        self,
        symbols: Sequence[str],
        start: datetime,
        end: datetime,
    ) -> tuple[Mapping[str, Any], ...]: ...

    def official_closes(self, session_date: date) -> Mapping[str, Decimal]: ...


class FixtureVendor:
    """Reads canned JSON under a local directory. Does not map to D5 bars."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)

    def minute_bars(
        self,
        symbols: Sequence[str],
        start: datetime,
        end: datetime,
    ) -> tuple[Mapping[str, Any], ...]:
        start_et = _require_aware(start, name="start")
        end_et = _require_aware(end, name="end")
        if start_et > end_et:
            raise ValueError("start must not be after end")
        if not symbols:
            return ()
        records = self._load_bar_records()
        known = {str(item["symbol"]) for item in records}
        for symbol in symbols:
            if symbol not in known:
                raise CommonDataUnavailable(symbol, "missing")
        wanted = set(symbols)
        out: list[Mapping[str, Any]] = []
        for item in records:
            if item["symbol"] not in wanted:
                continue
            bar_start = parse_et_timestamp(str(item["bar_start"]))
            if start_et <= bar_start <= end_et:
                out.append(item)
        return tuple(out)

    def official_closes(self, session_date: date) -> dict[str, Decimal]:
        if type(session_date) is not date:
            raise TypeError("expected a datetime.date")
        payload = self._load_object(_CLOSES_FILE)
        try:
            require_object(payload, required=("schema_version", "closes"))
            require_schema_version(payload)
            raw_closes = payload["closes"]
        except SchemaError as exc:
            raise CommonDataUnavailable(exc.path, exc.message) from exc
        if not isinstance(raw_closes, dict):
            raise CommonDataUnavailable("closes", "expected an object")
        key = session_date.isoformat()
        if key not in raw_closes:
            raise CommonDataUnavailable(key, "missing")
        day = raw_closes[key]
        if not isinstance(day, dict) or not day:
            raise CommonDataUnavailable(key, "missing")
        prices: dict[str, Decimal] = {}
        for symbol, raw in day.items():
            try:
                prices[str(symbol)] = as_decimal(raw)
            except (TypeError, ValueError) as exc:
                raise CommonDataUnavailable(f"{key}.{symbol}", str(exc)) from exc
        return prices

    def _load_bar_records(self) -> list[dict[str, Any]]:
        payload = self._load_object(_BARS_FILE)
        try:
            require_object(payload, required=("schema_version", "bars"))
            require_schema_version(payload)
            raw_bars = require_list(payload, "bars")
        except SchemaError as exc:
            raise CommonDataUnavailable(exc.path, exc.message) from exc
        records: list[dict[str, Any]] = []
        for index, item in enumerate(raw_bars):
            path = f"bars.{index}"
            if not isinstance(item, dict):
                raise CommonDataUnavailable(path, "expected an object")
            symbol = item.get("symbol")
            if not isinstance(symbol, str) or not symbol:
                raise CommonDataUnavailable(f"{path}.symbol", "missing")
            if "bar_start" not in item:
                raise CommonDataUnavailable(f"{path}.bar_start", "missing")
            try:
                parse_et_timestamp(str(item["bar_start"]))
            except (TypeError, ValueError) as exc:
                raise CommonDataUnavailable(f"{path}.bar_start", str(exc)) from exc
            records.append(item)
        return records

    def _load_object(self, name: str) -> dict[str, Any]:
        path = self._root / name
        if not path.is_file():
            raise CommonDataUnavailable(name, "missing")
        try:
            return load_json_object(path.read_text(encoding="utf-8"))
        except SchemaError as exc:
            raise CommonDataUnavailable(name, exc.message) from exc


def bars_at_reference(
    vendor: Vendor,
    symbols: Sequence[str],
    reference_minute: datetime,
) -> tuple[Bar, ...]:
    """One D5 bar per symbol at the reference minute, sorted by name.

    A missing minute or an explicit halt is an ineligible bar, not a
    guessed print. ``high < low`` is an error; fields are not swapped.
    """
    minute = _require_aware(reference_minute, name="reference_minute")
    ordered = tuple(sorted(set(symbols)))
    if not ordered:
        return ()
    records = vendor.minute_bars(ordered, minute, minute)
    by_symbol: dict[str, Mapping[str, Any]] = {}
    for item in records:
        symbol = str(item["symbol"])
        if symbol not in by_symbol:
            by_symbol[symbol] = item
    return tuple(
        _bar_for_symbol(symbol, by_symbol.get(symbol), minute) for symbol in ordered
    )


def _bar_for_symbol(
    symbol: str,
    raw: Mapping[str, Any] | None,
    minute: datetime,
) -> Bar:
    if raw is None:
        return parse_bar(
            {
                "symbol": symbol,
                "bar_start": format_et_timestamp(minute),
                "eligible": False,
            },
            path=symbol,
        )
    return parse_bar(raw, path=symbol)


def publish_round(
    root: Path | str,
    *,
    scheduled: ScheduledRound,
    bars: Sequence[Bar],
    portfolios: Sequence[Portfolio],
    raw_vendor_bytes: bytes,
    fills: Mapping[str, FillsFile] | None = None,
    exchange_timestamp: datetime | None = None,
    rules_md: str = "",
    prompt_md: str = "",
) -> None:
    """Write tape files, replica workspaces, and the raw vendor archive.

    Does not apply decisions. Does not author prompt text. Input books
    are not mutated.
    """
    books = _portfolio_map(portfolios)
    if not books:
        raise ValueError("portfolios must not be empty")
    clock = clock_for_round(
        scheduled,
        exchange_timestamp=scheduled.start
        if exchange_timestamp is None
        else exchange_timestamp,
    )
    bar_list = tuple(bars)
    empty_fills = FillsFile(schema_version=SCHEMA_VERSION, fills=())
    fill_map = fills if fills is not None else {}
    base = Path(root)
    round_dir = base / TAPE_ROUNDS_DIR / scheduled.round_id
    round_dir.mkdir(parents=True, exist_ok=True)
    (round_dir / TAPE_CLOCK_FILE).write_text(
        dump_clock(clock), encoding="utf-8", newline="\n"
    )
    (round_dir / TAPE_BARS_FILE).write_text(
        dump_json({"bars": [bar_to_dict(bar) for bar in bar_list]}),
        encoding="utf-8",
        newline="\n",
    )
    raw_dir = base / TAPE_RAW_DIR
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / f"{scheduled.round_id}.bin").write_bytes(raw_vendor_bytes)
    (raw_dir / f"{scheduled.round_id}.sha256").write_text(
        hashlib.sha256(raw_vendor_bytes).hexdigest() + "\n",
        encoding="ascii",
        newline="\n",
    )
    for replica_id in sorted(books):
        book = books[replica_id]
        snapshot = Snapshot(
            schema_version=SCHEMA_VERSION,
            clock=clock,
            bars=bar_list,
            portfolio=book,
        )
        write_replica_workspace(
            base / TAPE_REPLICAS_DIR / replica_id,
            rules_md=rules_md,
            prompt_md=prompt_md,
            clock=clock,
            portfolio=book,
            fills=fill_map.get(replica_id, empty_fills),
            snapshot=snapshot,
        )


def build_tape(
    out_dir: Path | str,
    calendar: Calendar,
    vendor: Vendor,
    universe: Sequence[str],
    session_dates: Sequence[date],
    starter_portfolio: Portfolio,
    *,
    rules_md: str,
    prompt_md: str,
) -> Path:
    """Write a D13-shaped tape from a frozen calendar and one vendor.

    Hold decisions are placeholders so ``replay_tape`` can load the tape.
    They are not a strategy. Caller supplies RULES.md / PROMPT.md text.
    """
    symbols = _universe_symbols(universe)
    days = _session_dates(session_dates)
    scheduled_rounds = _scheduled_rounds(calendar, days)
    last_session = _last_trading_day(calendar, days)
    replica_id = starter_portfolio.replica_id
    books = (_clone_starter(starter_portfolio, replica_id),)
    base = Path(out_dir)
    base.mkdir(parents=True, exist_ok=True)
    for scheduled in scheduled_rounds:
        records = vendor.minute_bars(symbols, scheduled.reference_minute, scheduled.reference_minute)
        bars = bars_at_reference(vendor, symbols, scheduled.reference_minute)
        _require_eligible_set(bars)
        publish_round(
            base,
            scheduled=scheduled,
            bars=bars,
            portfolios=books,
            raw_vendor_bytes=_raw_fetch_bytes(records),
            rules_md=rules_md,
            prompt_md=prompt_md,
        )
        _write_hold_decisions(base, scheduled.round_id, (replica_id,))
    (base / "rounds.json").write_text(
        _dump_list([item.round_id for item in scheduled_rounds]),
        encoding="utf-8",
        newline="\n",
    )
    (base / "replicas.json").write_text(
        _dump_list([replica_id]),
        encoding="utf-8",
        newline="\n",
    )
    (base / "universe.json").write_text(
        _dump_list(list(symbols)),
        encoding="utf-8",
        newline="\n",
    )
    (base / "starting_portfolio.json").write_text(
        dump_portfolio(starter_portfolio),
        encoding="utf-8",
        newline="\n",
    )
    (base / "close.json").write_text(
        _close_json(calendar, vendor, last_session, symbols),
        encoding="utf-8",
        newline="\n",
    )
    (base / "RULES.md").write_text(rules_md, encoding="utf-8", newline="\n")
    (base / "PROMPT.md").write_text(prompt_md, encoding="utf-8", newline="\n")
    return base.resolve()


def _universe_symbols(universe: Sequence[str]) -> tuple[str, ...]:
    if not universe:
        raise ValueError("universe must list at least one symbol")
    if len(set(universe)) != len(universe):
        raise ValueError("universe must not contain duplicate symbols")
    return tuple(sorted(universe))


def _session_dates(session_dates: Sequence[date]) -> tuple[date, ...]:
    if not session_dates:
        raise ValueError("session_dates must list at least one date")
    days: list[date] = []
    for day in session_dates:
        if type(day) is not date:
            raise TypeError("session_dates must be datetime.date values")
        days.append(day)
    return tuple(days)


def _scheduled_rounds(
    calendar: Calendar, days: Sequence[date]
) -> tuple[ScheduledRound, ...]:
    scheduled: list[ScheduledRound] = []
    for day in days:
        scheduled.extend(rounds_for_day(calendar, day))
    if not scheduled:
        raise ValueError("session_dates has no trading day")
    return tuple(scheduled)


def _last_trading_day(calendar: Calendar, days: Sequence[date]) -> date:
    trading = [day for day in days if is_trading_day(calendar, day)]
    if not trading:
        raise ValueError("session_dates has no trading day")
    return trading[-1]


def _require_eligible_set(bars: Sequence[Bar]) -> None:
    for bar in bars:
        if not bar.eligible:
            raise CommonDataUnavailable(bar.symbol, "no eligible reference bar")


def _raw_fetch_bytes(records: Sequence[Mapping[str, Any]]) -> bytes:
    return dump_json({"bars": [dict(item) for item in records]}).encode("utf-8")


def _write_hold_decisions(
    root: Path, round_id: str, replica_ids: Sequence[str]
) -> None:
    folder = root / TAPE_ROUNDS_DIR / round_id / "decisions"
    folder.mkdir(parents=True, exist_ok=True)
    text = dump_json(
        {
            "round_id": round_id,
            "action": "hold",
            "orders": [],
            "thesis": "No sufficiently attractive risk-reward opportunity.",
            "confidence": "0.70",
            "risk_note": "Cash may underperform a rising market.",
            "invalidation": "A material change in price or public information.",
            "intended_horizon": "Until the next round",
        }
    )
    for replica_id in replica_ids:
        (folder / f"{replica_id}.json").write_text(
            text, encoding="utf-8", newline="\n"
        )


def _close_json(
    calendar: Calendar,
    vendor: Vendor,
    session_date: date,
    symbols: Sequence[str],
) -> str:
    close = scheduled_close(calendar, session_date)
    if close is None:
        raise CommonDataUnavailable(session_date.isoformat(), "no session")
    prices = vendor.official_closes(session_date)
    out: dict[str, str] = {}
    for symbol in symbols:
        if symbol not in prices:
            raise CommonDataUnavailable(symbol, "missing")
        out[symbol] = format_cash(prices[symbol])
    close_at = datetime.combine(session_date, close, tzinfo=EXCHANGE_TZ)
    return dump_json(
        {
            "timestamp": format_et_timestamp(close_at),
            "prices": out,
        }
    )


def _dump_list(items: list[str]) -> str:
    return json.dumps(items, indent=2) + "\n"


def _clone_starter(starter: Portfolio, replica_id: str) -> Portfolio:
    return Portfolio(
        schema_version=starter.schema_version,
        replica_id=replica_id,
        product_id=starter.product_id,
        cash=starter.cash,
        positions=starter.positions,
        reported_equity=starter.reported_equity,
    )


def _portfolio_map(portfolios: Sequence[Portfolio]) -> dict[str, Portfolio]:
    books: dict[str, Portfolio] = {}
    for book in portfolios:
        if book.replica_id in books:
            raise ValueError(f"duplicate replica_id {book.replica_id!r}")
        books[book.replica_id] = book
    return books


def _require_aware(value: datetime, *, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"{name} must include an offset; do not assume UTC")
    return value.astimezone(EXCHANGE_TZ)
