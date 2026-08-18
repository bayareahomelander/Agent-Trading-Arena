"""R19: each applicable Protocol 0.2 row maps to one locked treatment."""

import pytest

from arena_runtime.disposition import (
    COMMON_DATA_AVAILABLE,
    COMMON_DATA_UNAVAILABLE,
    COMMON_DATA_UNAVAILABLE_REASON,
    REPLICA_TREATMENT_DISQUALIFY_REFUSAL,
    REPLICA_TREATMENT_EVALUATE,
    REPLICA_TREATMENT_HOLD_NO_ACTION,
    REPLICA_TREATMENT_VOIDED,
    ROUND_TREATMENT_EVALUATE,
    ROUND_TREATMENT_EVALUATOR_FAILURE,
    ROUND_TREATMENT_VOID_AND_PAUSE,
    decide_round_disposition,
)

from .conftest import make_result


@pytest.mark.parametrize(
    ("outcome", "common_data", "round_treatment", "replica_treatment", "reason"),
    [
        (
            "quota_exhausted",
            COMMON_DATA_AVAILABLE,
            ROUND_TREATMENT_VOID_AND_PAUSE,
            REPLICA_TREATMENT_VOIDED,
            "quota_exhausted",
        ),
        (
            "provider_unavailable",
            COMMON_DATA_AVAILABLE,
            ROUND_TREATMENT_VOID_AND_PAUSE,
            REPLICA_TREATMENT_VOIDED,
            "provider_unavailable",
        ),
        (
            "completed",
            COMMON_DATA_UNAVAILABLE,
            ROUND_TREATMENT_VOID_AND_PAUSE,
            REPLICA_TREATMENT_VOIDED,
            COMMON_DATA_UNAVAILABLE_REASON,
        ),
        (
            "timeout",
            COMMON_DATA_AVAILABLE,
            ROUND_TREATMENT_EVALUATE,
            REPLICA_TREATMENT_HOLD_NO_ACTION,
            REPLICA_TREATMENT_HOLD_NO_ACTION,
        ),
        (
            "missing_decision",
            COMMON_DATA_AVAILABLE,
            ROUND_TREATMENT_EVALUATE,
            REPLICA_TREATMENT_HOLD_NO_ACTION,
            REPLICA_TREATMENT_HOLD_NO_ACTION,
        ),
        (
            "completed",
            COMMON_DATA_AVAILABLE,
            ROUND_TREATMENT_EVALUATE,
            REPLICA_TREATMENT_EVALUATE,
            REPLICA_TREATMENT_EVALUATE,
        ),
        (
            "refusal",
            COMMON_DATA_AVAILABLE,
            ROUND_TREATMENT_EVALUATE,
            REPLICA_TREATMENT_DISQUALIFY_REFUSAL,
            REPLICA_TREATMENT_DISQUALIFY_REFUSAL,
        ),
        (
            "runner_error",
            COMMON_DATA_AVAILABLE,
            ROUND_TREATMENT_EVALUATOR_FAILURE,
            REPLICA_TREATMENT_VOIDED,
            "runner_error",
        ),
    ],
)
def test_protocol_row_maps_to_locked_treatment(
    outcome: str,
    common_data: str,
    round_treatment: str,
    replica_treatment: str,
    reason: str,
) -> None:
    disposition = decide_round_disposition(
        (make_result(outcome=outcome),),
        common_data,
    )

    assert disposition.treatment == round_treatment
    assert reason in disposition.reason_codes
    assert len(disposition.replica_dispositions) == 1
    assert disposition.replica_dispositions[0].outcome == outcome
    assert disposition.replica_dispositions[0].treatment == replica_treatment
