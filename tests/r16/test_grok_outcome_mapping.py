"""R16: documented events and explicit codes map to frozen R2 outcomes."""

import pytest

from arena_runtime.adapters.grok_build import classify_grok_build_outcome

from .conftest import facts, jsonl


END_OK = {"type": "end", "stopReason": "end_turn", "sessionId": "session-a"}


@pytest.mark.parametrize(
    ("raw_facts", "decision_present", "outcome", "code"),
    [
        (facts(jsonl(END_OK)), True, "completed", None),
        (facts(jsonl(END_OK)), False, "missing_decision", None),
        (facts(b"", exit_status=1, timed_out=True), False, "timeout", None),
        (
            facts(
                jsonl({"type": "error", "code": "usage_limit_reached"}),
                exit_status=1,
            ),
            False,
            "quota_exhausted",
            "usage_limit_reached",
        ),
        (
            facts(
                jsonl(
                    {
                        "type": "error",
                        "error": {"error_type": "serviceUnavailable"},
                    }
                ),
                exit_status=1,
            ),
            False,
            "provider_unavailable",
            "service_unavailable",
        ),
        (
            facts(
                jsonl(
                    {
                        "type": "end",
                        "stopReason": "refusal",
                        "sessionId": "session-a",
                    }
                ),
                exit_status=1,
            ),
            False,
            "refusal",
            "refusal",
        ),
        (
            facts(
                jsonl({"type": "error", "code": "unknownNewFailure"}),
                exit_status=1,
            ),
            False,
            "runner_error",
            "unknown_new_failure",
        ),
    ],
)
def test_each_outcome_maps_exactly_once_and_retains_evidence(
    raw_facts,
    decision_present: bool,
    outcome: str,
    code: str | None,
) -> None:
    classification = classify_grok_build_outcome(
        raw_facts,
        decision_present=decision_present,
    )

    assert classification.outcome == outcome
    if code is not None:
        assert code in classification.error_codes
    assert isinstance(classification.event_types, tuple)


def test_explicit_quota_evidence_beats_ordinary_timeout() -> None:
    raw = facts(
        jsonl({"type": "error", "errorType": "usagePoolExhausted"}),
        exit_status=1,
        timed_out=True,
    )

    assert classify_grok_build_outcome(raw, decision_present=False).outcome == (
        "quota_exhausted"
    )


def test_documented_refusal_stop_reason_maps_without_message_guessing() -> None:
    raw = facts(
        jsonl(
            {
                "type": "end",
                "stopReason": "refusal",
                "sessionId": "session-a",
            }
        )
    )

    classification = classify_grok_build_outcome(raw, decision_present=False)

    assert classification.outcome == "refusal"
    assert classification.error_codes == ("refusal",)
