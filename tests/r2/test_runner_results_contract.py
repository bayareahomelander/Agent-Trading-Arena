"""R2: preflight and runner results retain lifecycle facts only."""

from datetime import datetime

import pytest

from arena_runtime.runner import RUNNER_OUTCOMES, RunnerContractError

from conftest import DECISION_CHECKSUM, FINISHED_AT, make_preflight, make_result


def test_normalized_outcomes_are_complete_and_exact() -> None:
    assert RUNNER_OUTCOMES == (
        "completed",
        "missing_decision",
        "timeout",
        "refusal",
        "quota_exhausted",
        "provider_unavailable",
        "runner_error",
    )


def test_completed_result_can_reference_malformed_decision_bytes() -> None:
    result = make_result()

    assert result.outcome == "completed"
    assert result.decision_present is True
    assert result.decision_checksum == DECISION_CHECKSUM


def test_unknown_outcome_fails_with_named_field() -> None:
    with pytest.raises(RunnerContractError) as exc:
        make_result(outcome="malformed_decision")

    assert exc.value.path == "outcome"


def test_naive_result_timestamp_fails_with_named_field() -> None:
    with pytest.raises(RunnerContractError) as exc:
        make_result(finished_at=datetime(2026, 8, 17, 10, 5))

    assert exc.value.path == "finished_at"


def test_result_finish_cannot_precede_start() -> None:
    with pytest.raises(RunnerContractError) as exc:
        make_result(started_at=FINISHED_AT, finished_at=FINISHED_AT.replace(minute=4))

    assert exc.value.path == "finished_at"


@pytest.mark.parametrize(
    ("changes", "path"),
    [
        ({"exit_status": True}, "exit_status"),
        ({"decision_present": True, "decision_checksum": None}, "decision_checksum"),
        ({"decision_present": False, "decision_checksum": DECISION_CHECKSUM}, "decision_checksum"),
        ({"outcome": "completed", "decision_present": False, "decision_checksum": None}, "decision_present"),
        ({"outcome": "missing_decision"}, "decision_present"),
        ({"artifact_references": ["provider/stdout"]}, "artifact_references"),
        ({"artifact_references": ("provider/stdout", "provider/stdout")}, "artifact_references.1"),
    ],
)
def test_inconsistent_result_fields_fail_by_name(
    changes: dict[str, object],
    path: str,
) -> None:
    with pytest.raises(RunnerContractError) as exc:
        make_result(**changes)

    assert exc.value.path == path


def test_ready_preflight_has_no_failure_reason() -> None:
    result = make_preflight()

    assert result.ready is True
    assert result.failure_reason is None


def test_failed_preflight_requires_a_reason() -> None:
    with pytest.raises(RunnerContractError) as exc:
        make_preflight(ready=False)

    assert exc.value.path == "failure_reason"


def test_ready_preflight_rejects_a_failure_reason() -> None:
    with pytest.raises(RunnerContractError) as exc:
        make_preflight(failure_reason="not ready")

    assert exc.value.path == "failure_reason"
