"""Stable names for the subscription-backed runtime boundary.

R1 locks meanings only. Contracts and behavior belong to later deliverables.
"""

from __future__ import annotations

from typing import Final, Mapping

STABLE_TERMS: Final[Mapping[str, str]] = {
    "provider_adapter": (
        "Product-specific implementation of the shared runtime boundary"
    ),
    "runner_request": (
        "Provider-neutral description of one replica’s due round execution"
    ),
    "preflight": (
        "Readiness check performed before any round state is published or "
        "process launched"
    ),
    "runner_outcome": (
        "Normalized lifecycle result returned by an adapter; not a trading "
        "interpretation"
    ),
    "session_reference": (
        "Opaque provider-native identifier mapped one-to-one to a replica"
    ),
    "decision_barrier": (
        "Point before which no collected decision may be parsed, revealed, "
        "or applied"
    ),
    "round_disposition": (
        "Pure protocol treatment selected after all runner outcomes are known"
    ),
    "staged_commit": (
        "Candidate state prepared before all authoritative books are "
        "published together"
    ),
    "provider_artifact": (
        "Sanitized provider-specific evidence referenced by normalized audit "
        "records"
    ),
}
