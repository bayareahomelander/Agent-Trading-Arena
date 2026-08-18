"""R19: mixed outcomes keep every replica and apply the stronger round rule."""

from arena_runtime.disposition import (
    COMMON_DATA_AVAILABLE,
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


def test_one_timeout_does_not_void_a_completed_sibling() -> None:
    disposition = decide_round_disposition(
        (
            make_result(replica_id="product-a-1", outcome="completed"),
            make_result(replica_id="product-a-2", outcome="timeout"),
        ),
        COMMON_DATA_AVAILABLE,
    )

    assert disposition.treatment == ROUND_TREATMENT_EVALUATE
    by_replica = {
        item.replica_id: item.treatment for item in disposition.replica_dispositions
    }
    assert by_replica == {
        "product-a-1": REPLICA_TREATMENT_EVALUATE,
        "product-a-2": REPLICA_TREATMENT_HOLD_NO_ACTION,
    }
    assert disposition.comparison_degraded is False


def test_one_quota_failure_voids_every_sibling() -> None:
    disposition = decide_round_disposition(
        (
            make_result(
                product_id="product-a",
                replica_id="product-a-1",
                outcome="completed",
            ),
            make_result(
                product_id="product-b",
                replica_id="product-b-1",
                outcome="quota_exhausted",
            ),
        ),
        COMMON_DATA_AVAILABLE,
    )

    assert disposition.treatment == ROUND_TREATMENT_VOID_AND_PAUSE
    assert disposition.reason_codes == ("quota_exhausted",)
    assert {item.treatment for item in disposition.replica_dispositions} == {
        REPLICA_TREATMENT_VOIDED,
    }
    assert {item.replica_id for item in disposition.replica_dispositions} == {
        "product-a-1",
        "product-b-1",
    }


def test_refusal_does_not_void_siblings_and_marks_comparison_degraded() -> None:
    disposition = decide_round_disposition(
        (
            make_result(
                product_id="product-a",
                replica_id="product-a-1",
                outcome="completed",
            ),
            make_result(
                product_id="product-b",
                replica_id="product-b-1",
                outcome="refusal",
            ),
            make_result(
                product_id="product-b",
                replica_id="product-b-2",
                outcome="completed",
            ),
        ),
        COMMON_DATA_AVAILABLE,
    )

    assert disposition.treatment == ROUND_TREATMENT_EVALUATE
    by_replica = {
        item.replica_id: item.treatment for item in disposition.replica_dispositions
    }
    assert by_replica == {
        "product-a-1": REPLICA_TREATMENT_EVALUATE,
        "product-b-1": REPLICA_TREATMENT_DISQUALIFY_REFUSAL,
        "product-b-2": REPLICA_TREATMENT_EVALUATE,
    }
    assert disposition.comparison_degraded is True


def test_one_runner_error_voids_the_round_as_evaluator_failure() -> None:
    disposition = decide_round_disposition(
        (
            make_result(replica_id="product-a-1", outcome="completed"),
            make_result(replica_id="product-a-2", outcome="runner_error"),
        ),
        COMMON_DATA_AVAILABLE,
    )

    assert disposition.treatment == ROUND_TREATMENT_EVALUATOR_FAILURE
    assert disposition.reason_codes == ("runner_error",)
    assert {item.treatment for item in disposition.replica_dispositions} == {
        REPLICA_TREATMENT_VOIDED,
    }


def test_no_result_is_silently_dropped() -> None:
    results = (
        make_result(replica_id="product-a-1", outcome="completed"),
        make_result(replica_id="product-a-2", outcome="missing_decision"),
        make_result(
            product_id="product-b",
            replica_id="product-b-1",
            outcome="timeout",
        ),
    )

    disposition = decide_round_disposition(results, COMMON_DATA_AVAILABLE)

    assert [
        (item.product_id, item.replica_id, item.outcome)
        for item in disposition.replica_dispositions
    ] == [
        (result.product_id, result.replica_id, result.outcome) for result in results
    ]
    assert len(disposition.replica_dispositions) == 3
