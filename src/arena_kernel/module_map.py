"""Where each concern will live.

D1 records owners only. Behavior lands in later deliverables inside
these modules — do not invent a parallel tree.
"""

from __future__ import annotations

from typing import Final, Mapping

KERNEL_MODULES: Final[tuple[str, ...]] = (
    "types",
    "schema",
    "workspace",
    "validate",
    "pricing",
    "matching",
    "ledger",
    "replay",
    "baselines",
    "calendar",
    "marketdata",
)

# Concept key -> owning module(s), in the order a reader should look.
CONCEPT_OWNERS: Final[Mapping[str, tuple[str, ...]]] = {
    "numeric_and_time_primitives": ("types",),
    "json_contracts": ("schema",),
    "workspace_tree": ("workspace",),
    "order_allowed": ("validate",),
    "fill_price": ("pricing",),
    "cash_movement": ("matching", "ledger"),
    "position_update": ("matching", "ledger"),
    "append_only_facts": ("ledger",),
    "canned_tape_replay": ("replay",),
    "non_agent_baseline": ("baselines",),
    "holiday": ("calendar",),
    "bar_fetch": ("marketdata",),
}
