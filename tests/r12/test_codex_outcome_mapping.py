"""R12: documented events and explicit codes map to frozen R2 outcomes."""

import pytest

from arena_runtime.adapters.codex import classify_codex_outcome

from .conftest import facts, jsonl


THREAD = {"type": "thread.started", "thread_id": "thread-a"}
TURN_COMPLETE = {"type": "turn.completed", "usage": {}}


@pytest.mark.parametrize(
    ("raw_facts", "decision_present", "outcome", "code"),
    [
        (facts(jsonl(THREAD, TURN_COMPLETE)), True, "completed", None),
        (facts(jsonl(THREAD, TURN_COMPLETE)), False, "missing_decision", None),
        (facts(b"", exit_status=1, timed_out=True), False, "timeout", None),
        (
            facts(
                jsonl(
                    THREAD,
                    {
                        "type": "turn.failed",
                        "error": {"error_type": "usageLimitExceeded"},
                    },
                ),
                exit_status=1,
            ),
            False,
            "quota_exhausted",
            "usage_limit_exceeded",
        ),
        (
            facts(
                jsonl(
                    THREAD,
                    {
                        "type": "error",
                        "error": {"codexErrorKind": "serverOverloaded"},
                    },
                ),
                exit_status=1,
            ),
            False,
            "provider_unavailable",
            "server_overloaded",
        ),
        (
            facts(
                jsonl(
                    THREAD,
                    {
                        "type": "turn.failed",
                        "error": {"error_type": "cyberPolicy"},
                    },
                ),
                exit_status=1,
            ),
            False,
            "refusal",
            "cyber_policy",
        ),
        (
            facts(
                jsonl(
                    THREAD,
                    {
                        "type": "turn.failed",
                        "error": {"error_type": "unknownNewFailure"},
                    },
                ),
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
    classification = classify_codex_outcome(
        raw_facts,
        decision_present=decision_present,
    )

    assert classification.outcome == outcome
    if code is not None:
        assert code in classification.error_codes
    assert isinstance(classification.event_types, tuple)


def test_explicit_quota_evidence_beats_ordinary_timeout() -> None:
    raw = facts(
        jsonl(
            {"type": "error", "error": {"errorType": "usageLimitExceeded"}}
        ),
        exit_status=1,
        timed_out=True,
    )

    assert classify_codex_outcome(raw, decision_present=False).outcome == (
        "quota_exhausted"
    )


def test_explicit_refused_item_maps_without_message_guessing() -> None:
    raw = facts(
        jsonl(
            THREAD,
            {
                "type": "item.completed",
                "item": {
                    "type": "agent_message",
                    "status": "refused",
                    "text": "synthetic refusal",
                },
            },
        )
    )

    classification = classify_codex_outcome(raw, decision_present=False)

    assert classification.outcome == "refusal"
    assert classification.error_codes == ("refusal",)
