"""Planned ownership of subscription-backed runtime concerns.

R1 records owner names only. The named behavior modules arrive in later
deliverables and are deliberately not created here.
"""

from __future__ import annotations

from typing import Final, Mapping

RUNTIME_MODULES: Final[tuple[str, ...]] = (
    "runner",
    "registration",
    "audit",
    "process",
    "isolation",
    "disposition",
    "orchestrator",
    "cli",
    "adapters",
)

# Concept key -> future owning runtime module(s), in reader lookup order.
CONCEPT_OWNERS: Final[Mapping[str, tuple[str, ...]]] = {
    "provider_adapter": ("adapters",),
    "runner_request": ("runner",),
    "preflight": ("adapters",),
    "runner_outcome": ("runner",),
    "session_reference": ("runner",),
    "decision_barrier": ("orchestrator",),
    "round_disposition": ("disposition",),
    "staged_commit": ("orchestrator",),
    "provider_artifact": ("audit",),
    "runtime_registration": ("registration",),
    "process_supervision": ("process",),
    "replica_launch_isolation": ("isolation",),
    "operator_entry_point": ("cli",),
}
