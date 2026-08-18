"""Stable domain names for the paper-exchange kernel.

These strings are the language of README protocol 0.2. Do not rename them
to match a later implementation convenience. D1: names only — no formulas.
"""

from __future__ import annotations

from typing import Final, Mapping

ROUND_KINDS: Final[tuple[str, ...]] = ("morning", "late")

STABLE_TERMS: Final[Mapping[str, str]] = {
    "product": "Named subscribed agent system",
    "replica": (
        "One isolated portfolio / workspace / session of a product"
    ),
    "round": "One sealed decision window (morning or late)",
    "snapshot": (
        "Common market files + replica portfolio files frozen at round start"
    ),
    "decision": "The replica's outbox/decision.json",
    "paper_exchange": "Validates a decision and assigns fills",
    "ledger": "Append-only list of facts the agent cannot edit",
    "bar": "One one-minute OHLCV record, plus optional VWAP",
    "fill": "One accepted execution at a documented price",
}
