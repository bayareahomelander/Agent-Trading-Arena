"""R1: runtime terms and meanings are complete and exact."""

from arena_runtime.vocabulary import STABLE_TERMS


EXPECTED_TERMS = {
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


def test_runtime_terms_and_meanings_are_complete_and_exact() -> None:
    assert STABLE_TERMS == EXPECTED_TERMS
