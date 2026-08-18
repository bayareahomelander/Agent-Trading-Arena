"""R12: unknown, malformed, or ambiguous evidence is always runner_error."""

from arena_runtime.adapters.codex import classify_codex_outcome

from .conftest import facts, jsonl


def test_quota_words_without_explicit_code_do_not_guess_quota() -> None:
    raw = facts(
        jsonl(
            {
                "type": "error",
                "message": "Maybe a quota or usage limit was reached",
            }
        ),
        exit_status=1,
    )

    classification = classify_codex_outcome(raw, decision_present=False)

    assert classification.outcome == "runner_error"
    assert classification.error_codes == ()


def test_malformed_jsonl_is_runner_error_not_missing_decision() -> None:
    classification = classify_codex_outcome(
        facts(b"not-json\n", exit_status=0),
        decision_present=False,
    )

    assert classification.outcome == "runner_error"
    assert classification.jsonl_valid is False


def test_ambiguous_quota_and_provider_codes_are_runner_error() -> None:
    raw = facts(
        jsonl(
            {
                "type": "turn.failed",
                "error": {
                    "error_type": "usageLimitExceeded",
                    "nested": {"error_code": "serverOverloaded"},
                },
            }
        ),
        exit_status=1,
    )

    classification = classify_codex_outcome(raw, decision_present=False)

    assert classification.outcome == "runner_error"
    assert classification.error_codes == (
        "server_overloaded",
        "usage_limit_exceeded",
    )


def test_success_exit_without_turn_completed_is_runner_error() -> None:
    raw = facts(
        jsonl({"type": "thread.started", "thread_id": "thread-a"}),
        exit_status=0,
    )

    assert classify_codex_outcome(raw, decision_present=False).outcome == (
        "runner_error"
    )
