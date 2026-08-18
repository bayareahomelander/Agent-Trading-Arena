"""Canned-tape replay. No live vendor or agent runner."""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from arena_kernel.ledger import final_nlv, mark_to_close, median_nlv
from arena_kernel.matching import apply_decision
from arena_kernel.schema._dump import dump_json
from arena_kernel.schema._parse import SCHEMA_VERSION, load_json_object
from arena_kernel.schema.clock import parse_clock
from arena_kernel.schema.decision import parse_decision
from arena_kernel.schema.events import LedgerEvent, OrderFilledPayload, ledger_event_to_dict
from arena_kernel.schema.fills import FillsFile, PriorFill
from arena_kernel.schema.market import Bar, Snapshot, parse_bar
from arena_kernel.schema.portfolio import Portfolio, parse_portfolio
from arena_kernel.types import as_decimal, format_cash, parse_et_timestamp
from arena_kernel.workspace import write_replica_workspace


@dataclass(frozen=True)
class ReplayResult:
    events_by_replica: dict[str, tuple[LedgerEvent, ...]]
    equity_by_replica: dict[str, Decimal]
    nlv_by_replica: dict[str, Decimal]
    median: Decimal


def replay_tape(tape_dir: Path | str, work_root: Path | str) -> ReplayResult:
    """Write replica workspaces, apply each round, mark close, return books."""
    tape = Path(tape_dir)
    work = Path(work_root)
    rules_md = (tape / "RULES.md").read_text(encoding="utf-8")
    prompt_md = (tape / "PROMPT.md").read_text(encoding="utf-8")
    replica_ids = _load_json(tape / "replicas.json")
    round_ids = _load_json(tape / "rounds.json")
    starter = parse_portfolio((tape / "starting_portfolio.json").read_text(encoding="utf-8"))
    close_spec = load_json_object((tape / "close.json").read_text(encoding="utf-8"))
    close_at = parse_et_timestamp(close_spec["timestamp"])
    official_closes = {
        symbol: as_decimal(price) for symbol, price in close_spec["prices"].items()
    }

    books: dict[str, Portfolio] = {
        replica_id: _clone_starter(starter, replica_id) for replica_id in replica_ids
    }
    fills: dict[str, FillsFile] = {
        replica_id: FillsFile(schema_version=SCHEMA_VERSION, fills=())
        for replica_id in replica_ids
    }
    events: dict[str, list[LedgerEvent]] = {replica_id: [] for replica_id in replica_ids}

    for round_id in round_ids:
        round_dir = tape / "rounds" / round_id
        clock = parse_clock((round_dir / "clock.json").read_text(encoding="utf-8"))
        bars = _load_bars(round_dir / "bars.json")
        for replica_id in replica_ids:
            portfolio = books[replica_id]
            snapshot = Snapshot(
                schema_version=SCHEMA_VERSION,
                clock=clock,
                bars=bars,
                portfolio=portfolio,
            )
            write_replica_workspace(
                work / replica_id,
                rules_md=rules_md,
                prompt_md=prompt_md,
                clock=clock,
                portfolio=portfolio,
                fills=fills[replica_id],
                snapshot=snapshot,
            )
            decision = parse_decision(
                (round_dir / "decisions" / f"{replica_id}.json").read_text(encoding="utf-8")
            )
            round_events, portfolio = apply_decision(portfolio, decision, snapshot)
            events[replica_id].extend(round_events)
            books[replica_id] = portfolio
            fills[replica_id] = _extend_fills(fills[replica_id], round_events)

    equities: dict[str, Decimal] = {}
    nlvs: dict[str, Decimal] = {}
    for replica_id in replica_ids:
        equity, mark_event = mark_to_close(
            books[replica_id], official_closes, timestamp=close_at
        )
        nlv, nlv_event = final_nlv(
            books[replica_id], official_closes, timestamp=close_at
        )
        events[replica_id].extend((mark_event, nlv_event))
        equities[replica_id] = equity
        nlvs[replica_id] = nlv

    return ReplayResult(
        events_by_replica={key: tuple(value) for key, value in events.items()},
        equity_by_replica=equities,
        nlv_by_replica=nlvs,
        median=median_nlv(tuple(nlvs.values())),
    )


def dump_replay_result(result: ReplayResult) -> str:
    replicas: dict[str, Any] = {}
    for replica_id in sorted(result.events_by_replica):
        replicas[replica_id] = {
            "events": [
                ledger_event_to_dict(event)
                for event in result.events_by_replica[replica_id]
            ],
            "equity": _money(result.equity_by_replica[replica_id]),
            "nlv": _money(result.nlv_by_replica[replica_id]),
        }
    return dump_json(
        {
            "replicas": replicas,
            "median_nlv": _money(result.median),
        }
    )


def _clone_starter(starter: Portfolio, replica_id: str) -> Portfolio:
    return Portfolio(
        schema_version=starter.schema_version,
        replica_id=replica_id,
        product_id=starter.product_id,
        cash=starter.cash,
        positions=starter.positions,
        reported_equity=starter.reported_equity,
    )


def _load_bars(path: Path) -> tuple[Bar, ...]:
    payload = load_json_object(path.read_text(encoding="utf-8"))
    raw = payload["bars"]
    return tuple(parse_bar(item) for item in raw)


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _extend_fills(book: FillsFile, events: tuple[LedgerEvent, ...]) -> FillsFile:
    extra: list[PriorFill] = []
    for event in events:
        payload = event.payload
        if not isinstance(payload, OrderFilledPayload) or event.round_id is None:
            continue
        extra.append(
            PriorFill(
                fill_id=payload.fill_id,
                round_id=event.round_id,
                symbol=payload.symbol,
                side=payload.side,
                quantity=payload.quantity,
                fill_price=payload.fill_price,
                notional_usd=payload.notional_usd,
                filled_at=event.timestamp,
            )
        )
    return FillsFile(schema_version=book.schema_version, fills=book.fills + tuple(extra))


def _money(value: Decimal) -> str:
    return format_cash(value)
