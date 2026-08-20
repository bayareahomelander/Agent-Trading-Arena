"""Non-agent baselines.

B1 records locked ids. B2 adds the result shape and the first scored
fill window. B3 is the cash hold. B4 is SPY buy-and-hold. B5 is
equal-weight. B6 is seeded random. B7 runs all four on a tape.

Baselines are not contestants. They share product_id ``baseline`` and
are not registered in a season manifest as products.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from random import Random
from typing import Final, Mapping, Sequence

from arena_kernel.ledger import final_nlv, mark_to_close
from arena_kernel.matching import apply_decision
from arena_kernel.schema._dump import dump_json
from arena_kernel.schema._parse import SCHEMA_VERSION, load_json_object
from arena_kernel.schema.clock import parse_clock
from arena_kernel.schema.decision import Decision, Order
from arena_kernel.schema.events import LedgerEvent, ledger_event_to_dict
from arena_kernel.schema.market import Bar, Snapshot, parse_bar
from arena_kernel.schema.portfolio import Portfolio, parse_portfolio
from arena_kernel.schema.round_id import parse_round_id
from arena_kernel.schema.errors import FieldError
from arena_kernel.types import CASH_QUANTUM, as_decimal, format_cash, parse_et_timestamp, round_cash

BASELINE_PRODUCT_ID: Final[str] = "baseline"

# Locked replica_id strings. Meanings are names, not implementations.
BASELINE_REPLICA_IDS: Final[tuple[str, ...]] = (
    "baseline:cash",
    "baseline:spy_buy_and_hold",
    "baseline:equal_weight",
    "baseline:seeded_random",
)

_ROUNDS_PATH: Final[str] = "rounds.json"
_SPY: Final[str] = "SPY"
_SPY_REPLICA_ID: Final[str] = "baseline:spy_buy_and_hold"
_EQUAL_WEIGHT_REPLICA_ID: Final[str] = "baseline:equal_weight"
_SEEDED_RANDOM_REPLICA_ID: Final[str] = "baseline:seeded_random"
DEFAULT_RANDOM_SEED: Final[int] = 20260817
_BASELINES_FILE: Final[str] = "baselines.json"


@dataclass(frozen=True)
class BaselineResult:
    replica_id: str
    events: tuple[LedgerEvent, ...]
    final_portfolio: Portfolio
    marked_equity: Decimal
    nlv: Decimal


class FirstWindowError(FieldError):
    """No first scored fill window. ``path`` names the tape field."""

    def __init__(
        self,
        path: str,
        message: str,
        *,
        required_symbols: tuple[str, ...] = (),
    ) -> None:
        super().__init__(path, message)
        self.required_symbols = required_symbols


def first_scored_round_id(
    round_ids: Sequence[str],
    snapshots_or_bars: Mapping[str, Snapshot | Sequence[Bar]],
    *,
    required_symbols: Sequence[str] | None = None,
    path: str = _ROUNDS_PATH,
) -> str:
    """First ``rounds.json`` entry with an eligible bar for every needed symbol.

    Order is tape order only. Do not consult a live calendar.

    When ``required_symbols`` is omitted, every symbol that appears in
    ``snapshots_or_bars`` is required (the tape universe). An empty
    sequence means the baseline needs no bars; the first listed round
    is returned.
    """
    if not isinstance(snapshots_or_bars, Mapping):
        raise TypeError("snapshots_or_bars must be a mapping keyed by round_id")
    if not round_ids:
        raise FirstWindowError(path, "must list at least one round")
    needed = (
        tuple(required_symbols)
        if required_symbols is not None
        else _symbols_in(snapshots_or_bars)
    )
    for round_id in round_ids:
        bars = _bars_for_round(snapshots_or_bars.get(round_id))
        if _has_eligible_bar_for_each(bars, needed):
            return round_id
    raise FirstWindowError(
        path,
        "no round has an eligible bar for every required symbol",
        required_symbols=needed,
    )


def _bars_for_round(item: Snapshot | Sequence[Bar] | None) -> tuple[Bar, ...]:
    if item is None:
        return ()
    if isinstance(item, Snapshot):
        return item.bars
    return tuple(item)


def _symbols_in(
    snapshots_or_bars: Mapping[str, Snapshot | Sequence[Bar]],
) -> tuple[str, ...]:
    seen: list[str] = []
    for item in snapshots_or_bars.values():
        for bar in _bars_for_round(item):
            if bar.symbol not in seen:
                seen.append(bar.symbol)
    return tuple(seen)


def _has_eligible_bar_for_each(
    bars: Sequence[Bar], required_symbols: Sequence[str]
) -> bool:
    eligible = {bar.symbol for bar in bars if bar.eligible}
    return all(symbol in eligible for symbol in required_symbols)


class CashBaselineError(ValueError):
    """Cash baseline cannot run on this book."""


def run_cash_baseline(
    starting_portfolio: Portfolio,
    official_closes: Mapping[str, Decimal],
    close_timestamp: datetime,
) -> BaselineResult:
    """Hold cash. No orders. D12 mark and NLV on the starting book."""
    if starting_portfolio.positions:
        raise CashBaselineError(
            "cash baseline holds cash only; starting positions are not allowed"
        )
    book = replace(
        starting_portfolio,
        replica_id="baseline:cash",
        product_id=BASELINE_PRODUCT_ID,
    )
    return _close_baseline(book, (), official_closes, close_timestamp)


class SpyBaselineError(FieldError):
    """SPY buy-and-hold cannot run. Do not guess another ticker."""


def run_spy_buy_and_hold(
    starting_portfolio: Portfolio,
    round_ids: Sequence[str],
    snapshots_or_bars: Mapping[str, Snapshot | Sequence[Bar]],
    official_closes: Mapping[str, Decimal],
    close_timestamp: datetime,
) -> BaselineResult:
    """Buy SPY with all cash at the first scored window. Do not trade later."""
    if starting_portfolio.positions:
        raise SpyBaselineError(
            "positions",
            "SPY buy-and-hold starts from cash only",
        )
    book = replace(
        starting_portfolio,
        replica_id=_SPY_REPLICA_ID,
        product_id=BASELINE_PRODUCT_ID,
    )
    try:
        first = first_scored_round_id(
            round_ids,
            snapshots_or_bars,
            required_symbols=(_SPY,),
        )
    except FirstWindowError as exc:
        if not round_ids:
            raise
        raise SpyBaselineError(
            _SPY,
            "missing eligible SPY bar at the first scored window",
        ) from exc
    snapshot = _snapshot_for_first_window(first, snapshots_or_bars, book)
    if not any(bar.symbol == _SPY and bar.eligible for bar in snapshot.bars):
        raise SpyBaselineError(
            _SPY,
            "missing eligible SPY bar at the first scored window",
        )
    events, book = apply_decision(book, _spy_all_in_decision(first, book.cash), snapshot)
    return _close_baseline(book, events, official_closes, close_timestamp)


def _close_baseline(
    book: Portfolio,
    events: Sequence[LedgerEvent],
    official_closes: Mapping[str, Decimal],
    close_timestamp: datetime,
) -> BaselineResult:
    equity, mark_event = mark_to_close(
        book, official_closes, timestamp=close_timestamp
    )
    nlv, nlv_event = final_nlv(book, official_closes, timestamp=close_timestamp)
    return BaselineResult(
        replica_id=book.replica_id,
        events=tuple(events) + (mark_event, nlv_event),
        final_portfolio=book,
        marked_equity=equity,
        nlv=nlv,
    )


def _snapshot_for_first_window(
    round_id: str,
    snapshots_or_bars: Mapping[str, Snapshot | Sequence[Bar]],
    book: Portfolio,
) -> Snapshot:
    item = snapshots_or_bars.get(round_id)
    if not isinstance(item, Snapshot):
        raise FirstWindowError(
            round_id,
            "first scored window must be a Snapshot (clock + bars)",
        )
    clock = item.clock if item.clock.round_id == round_id else replace(
        item.clock, round_id=round_id
    )
    return Snapshot(
        schema_version=item.schema_version,
        clock=clock,
        bars=item.bars,
        portfolio=book,
    )


def _spy_all_in_decision(round_id: str, cash: Decimal) -> Decision:
    return Decision(
        round_id=round_id,
        action="trade",
        orders=(
            Order(
                priority=1,
                symbol=_SPY,
                side="buy",
                notional_usd=cash,
                quantity=None,
            ),
        ),
        thesis="SPY buy-and-hold baseline.",
        confidence=Decimal("1"),
        risk_note="SPY can fall.",
        invalidation="Not a strategy.",
        intended_horizon="Until Day-20 close.",
        schema_version=None,
    )


class EqualWeightError(FieldError):
    """Equal-weight baseline cannot run on this universe or book."""


def equal_weight_notionals(
    starting_cash: Decimal, universe: Sequence[str]
) -> tuple[tuple[str, Decimal], ...]:
    """Split cash into equal notionals. Last symbol gets the remainder."""
    if not universe:
        raise EqualWeightError("universe", "must list at least one symbol")
    if len(set(universe)) != len(universe):
        raise EqualWeightError("universe", "duplicate symbol")
    symbols = tuple(sorted(universe))
    share = round_cash(starting_cash / len(symbols))
    allocated = Decimal("0.00")
    rows: list[tuple[str, Decimal]] = []
    for index, symbol in enumerate(symbols):
        if index == len(symbols) - 1:
            notional = round_cash(starting_cash - allocated)
        else:
            notional = share
            allocated = round_cash(allocated + share)
        if notional <= 0:
            raise EqualWeightError(symbol, "equal-weight notional must be positive")
        rows.append((symbol, notional))
    return tuple(rows)


def run_equal_weight(
    starting_portfolio: Portfolio,
    round_ids: Sequence[str],
    snapshots_or_bars: Mapping[str, Snapshot | Sequence[Bar]],
    official_closes: Mapping[str, Decimal],
    close_timestamp: datetime,
    universe: Sequence[str],
) -> BaselineResult:
    """Equal notionals at the first scored window. No later rebalance."""
    if starting_portfolio.positions:
        raise EqualWeightError(
            "positions",
            "equal-weight starts from cash only",
        )
    splits = equal_weight_notionals(starting_portfolio.cash, universe)
    symbols = tuple(symbol for symbol, _notional in splits)
    book = replace(
        starting_portfolio,
        replica_id=_EQUAL_WEIGHT_REPLICA_ID,
        product_id=BASELINE_PRODUCT_ID,
    )
    try:
        first = first_scored_round_id(
            round_ids,
            snapshots_or_bars,
            required_symbols=symbols,
        )
    except FirstWindowError as exc:
        if not round_ids:
            raise
        raise EqualWeightError(
            "universe",
            "no round has an eligible bar for every universe symbol",
        ) from exc
    snapshot = _snapshot_for_first_window(first, snapshots_or_bars, book)
    events, book = apply_decision(
        book, _equal_weight_decision(first, splits), snapshot
    )
    return _close_baseline(book, events, official_closes, close_timestamp)


def _equal_weight_decision(
    round_id: str, splits: Sequence[tuple[str, Decimal]]
) -> Decision:
    orders = tuple(
        Order(
            priority=index,
            symbol=symbol,
            side="buy",
            notional_usd=notional,
            quantity=None,
        )
        for index, (symbol, notional) in enumerate(splits, start=1)
    )
    return Decision(
        round_id=round_id,
        action="trade",
        orders=orders,
        thesis="Equal-weight baseline.",
        confidence=Decimal("1"),
        risk_note="Equal names can fall together.",
        invalidation="Not a strategy.",
        intended_horizon="Until Day-20 close.",
        schema_version=None,
    )


class SeededRandomError(FieldError):
    """Seeded random cannot run. Do not fall back to the clock."""


def load_random_seed(path: Path | str) -> int:
    """Read ``random_seed`` from ``baselines.json``. No time fallback."""
    source = Path(path)
    if not source.is_file():
        raise SeededRandomError(_BASELINES_FILE, "missing")
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SeededRandomError(_BASELINES_FILE, f"invalid JSON: {exc.msg}") from exc
    if not isinstance(raw, dict):
        raise SeededRandomError(_BASELINES_FILE, "expected an object")
    if "random_seed" not in raw:
        raise SeededRandomError("random_seed", "missing")
    seed = raw["random_seed"]
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise SeededRandomError("random_seed", "must be an integer")
    return seed


def random_decision(
    rng: Random,
    portfolio: Portfolio,
    universe: Sequence[str],
    round_id: str,
) -> Decision:
    """One hold, or one long-only buy, from ``rng``. Not a strategy."""
    parsed_round = parse_round_id(round_id)
    symbols = tuple(sorted(set(universe)))
    if not symbols or portfolio.cash <= 0:
        return _random_hold(parsed_round)
    if rng.choice(("hold", "trade")) == "hold":
        return _random_hold(parsed_round)
    cents = int((portfolio.cash / CASH_QUANTUM).to_integral_value())
    if cents <= 0:
        return _random_hold(parsed_round)
    notional = round_cash(Decimal(rng.randint(1, cents)) / Decimal(100))
    return Decision(
        round_id=parsed_round,
        action="trade",
        orders=(
            Order(
                priority=1,
                symbol=rng.choice(symbols),
                side="buy",
                notional_usd=notional,
                quantity=None,
            ),
        ),
        thesis="Seeded random baseline.",
        confidence=Decimal("0.5"),
        risk_note="Random allocation can lose money.",
        invalidation="Not a strategy.",
        intended_horizon="Until the next round.",
        schema_version=None,
    )


def run_seeded_random(
    starting_portfolio: Portfolio,
    round_ids: Sequence[str],
    snapshots_or_bars: Mapping[str, Snapshot | Sequence[Bar]],
    official_closes: Mapping[str, Decimal],
    close_timestamp: datetime,
    universe: Sequence[str],
    *,
    seed: int | None = None,
    baselines_path: Path | str | None = None,
) -> BaselineResult:
    """Apply ``random_decision`` at every scheduled window, then D12."""
    resolved = _resolve_seed(seed, baselines_path)
    if not universe:
        raise SeededRandomError("universe", "must list at least one symbol")
    if not round_ids:
        raise FirstWindowError("rounds.json", "must list at least one round")
    book = replace(
        starting_portfolio,
        replica_id=_SEEDED_RANDOM_REPLICA_ID,
        product_id=BASELINE_PRODUCT_ID,
    )
    rng = Random(resolved)
    events: list[LedgerEvent] = []
    for round_id in round_ids:
        snapshot = _snapshot_for_first_window(round_id, snapshots_or_bars, book)
        decision = random_decision(rng, book, universe, round_id)
        step, book = apply_decision(book, decision, snapshot)
        events.extend(step)
    return _close_baseline(book, events, official_closes, close_timestamp)


def _resolve_seed(seed: int | None, baselines_path: Path | str | None) -> int:
    if seed is not None:
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise SeededRandomError("random_seed", "must be an integer")
        return seed
    if baselines_path is None:
        raise SeededRandomError("random_seed", "missing")
    return load_random_seed(baselines_path)


def _random_hold(round_id: str) -> Decision:
    return Decision(
        round_id=round_id,
        action="hold",
        orders=(),
        thesis="Seeded random baseline.",
        confidence=Decimal("0.5"),
        risk_note="Random allocation can lose money.",
        invalidation="Not a strategy.",
        intended_horizon="Until the next round.",
        schema_version=None,
    )


def run_baselines(tape_dir: Path | str) -> dict[str, BaselineResult]:
    """Run cash, SPY, equal-weight, and seeded random on one tape."""
    tape = Path(tape_dir)
    if not tape.is_dir():
        raise BaselineTapeError(str(tape), "tape directory missing")
    starter, round_ids, snapshots, official_closes, close_at = _load_baseline_tape(
        tape
    )
    universe = tuple(sorted(_symbols_in(snapshots)))
    results = (
        run_cash_baseline(starter, official_closes, close_at),
        run_spy_buy_and_hold(
            starter, round_ids, snapshots, official_closes, close_at
        ),
        run_equal_weight(
            starter, round_ids, snapshots, official_closes, close_at, universe
        ),
        run_seeded_random(
            starter,
            round_ids,
            snapshots,
            official_closes,
            close_at,
            universe,
            baselines_path=tape / _BASELINES_FILE,
        ),
    )
    return {result.replica_id: result for result in results}


def dump_baselines_result(results: Mapping[str, BaselineResult]) -> str:
    """Stable JSON: B1 replica order, decimal strings, trailing newline."""
    replicas: dict[str, object] = {}
    for replica_id in BASELINE_REPLICA_IDS:
        result = results[replica_id]
        replicas[replica_id] = {
            "events": [ledger_event_to_dict(event) for event in result.events],
            "equity": format_cash(result.marked_equity),
            "nlv": format_cash(result.nlv),
        }
    extra = sorted(set(results) - set(BASELINE_REPLICA_IDS))
    if extra:
        raise BaselineTapeError("replicas", f"unexpected baseline ids: {extra}")
    return dump_json({"replicas": replicas})


class BaselineTapeError(FieldError):
    """Tape pieces needed to run all four baselines are missing or malformed."""


def _load_baseline_tape(
    tape: Path,
) -> tuple[
    Portfolio,
    list[str],
    dict[str, Snapshot],
    dict[str, Decimal],
    datetime,
]:
    raw_rounds = json.loads(_read_tape_file(tape, "rounds.json"))
    if not isinstance(raw_rounds, list) or not raw_rounds:
        raise FirstWindowError("rounds.json", "must list at least one round")
    if not all(isinstance(item, str) for item in raw_rounds):
        raise FirstWindowError("rounds.json", "must be a list of round_id strings")
    starter = parse_portfolio(_read_tape_file(tape, "starting_portfolio.json"))
    close_spec = load_json_object(_read_tape_file(tape, "close.json"))
    close_at = parse_et_timestamp(close_spec["timestamp"])
    official_closes = {
        symbol: as_decimal(price) for symbol, price in close_spec["prices"].items()
    }
    snapshots: dict[str, Snapshot] = {}
    for round_id in raw_rounds:
        round_dir = tape / "rounds" / round_id
        clock = parse_clock(_read_tape_file(round_dir, "clock.json"))
        payload = load_json_object(_read_tape_file(round_dir, "bars.json"))
        bars = tuple(parse_bar(item) for item in payload["bars"])
        snapshots[round_id] = Snapshot(
            schema_version=SCHEMA_VERSION,
            clock=clock,
            bars=bars,
            portfolio=starter,
        )
    return starter, list(raw_rounds), snapshots, official_closes, close_at


def _read_tape_file(directory: Path, name: str) -> str:
    path = directory / name
    if not path.is_file():
        raise BaselineTapeError(name, "missing")
    return path.read_text(encoding="utf-8")

