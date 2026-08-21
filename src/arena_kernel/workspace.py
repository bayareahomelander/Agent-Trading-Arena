"""Replica workspace tree writer.

Intended permissions (not enforced at the OS in Phase A):
`RULES.md`, `PROMPT.md`, and `state/` are evaluator-owned and read-only for
the agent. `agent/` and `outbox/` are writable. Do not chmod here.

This module does not author prompt text. It does not invent a hold
`outbox/decision.json`; a missing file means the replica has not decided.
"""

from __future__ import annotations

from pathlib import Path

from arena_kernel.schema.clock import Clock, dump_clock
from arena_kernel.schema.fills import FillsFile, dump_fills
from arena_kernel.schema.market import Snapshot, dump_snapshot
from arena_kernel.schema.portfolio import Portfolio, dump_portfolio

RULES_FILE = "RULES.md"
PROMPT_FILE = "PROMPT.md"
CLOCK_FILE = "state/clock.json"
PORTFOLIO_FILE = "state/portfolio.json"
FILLS_FILE = "state/fills.json"
SNAPSHOT_FILE = "state/market/snapshot.json"
INTRADAY_FILE = "state/market/intraday.json"
DAILY_FILE = "state/market/daily.json"
OUTBOX_DECISION_FILE = "outbox/decision.json"

_EMPTY_DIRS = (
    "state/market",
    "agent/notes",
    "agent/research",
    "agent/tools",
    "outbox",
)


def write_replica_workspace(
    root: Path | str,
    *,
    rules_md: str,
    prompt_md: str,
    clock: Clock,
    portfolio: Portfolio,
    fills: FillsFile,
    snapshot: Snapshot,
    intraday_json: str | None = None,
    daily_json: str | None = None,
) -> Path:
    """Create one replica tree. Returns the resolved root."""
    if (intraday_json is None) != (daily_json is None):
        raise ValueError("intraday_json and daily_json must both be set or both omitted")
    base = Path(root)
    for relative in _EMPTY_DIRS:
        (base / relative).mkdir(parents=True, exist_ok=True)
    (base / RULES_FILE).write_text(rules_md, encoding="utf-8", newline="\n")
    (base / PROMPT_FILE).write_text(prompt_md, encoding="utf-8", newline="\n")
    (base / CLOCK_FILE).write_text(dump_clock(clock), encoding="utf-8", newline="\n")
    (base / PORTFOLIO_FILE).write_text(
        dump_portfolio(portfolio), encoding="utf-8", newline="\n"
    )
    (base / FILLS_FILE).write_text(dump_fills(fills), encoding="utf-8", newline="\n")
    (base / SNAPSHOT_FILE).write_text(
        dump_snapshot(snapshot), encoding="utf-8", newline="\n"
    )
    if intraday_json is not None and daily_json is not None:
        (base / INTRADAY_FILE).write_text(
            intraday_json, encoding="utf-8", newline="\n"
        )
        (base / DAILY_FILE).write_text(daily_json, encoding="utf-8", newline="\n")
    return base.resolve()
