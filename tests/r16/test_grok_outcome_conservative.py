"""R16: unknown, malformed, or ambiguous evidence is always runner_error."""

from arena_runtime.adapters.grok_build import classify_grok_build_outcome

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

    classification = classify_grok_build_outcome(raw, decision_present=False)

    assert classification.outcome == "runner_error"
    assert classification.error_codes == ()


def test_rate_limit_is_ambiguous_and_does_not_become_quota() -> None:
    raw = facts(
        jsonl({"type": "error", "code": "rate_limit"}),
        exit_status=1,
    )

    assert classify_grok_build_outcome(raw, decision_present=False).outcome == (
        "runner_error"
    )


def test_malformed_jsonl_is_runner_error_not_missing_decision() -> None:
    classification = classify_grok_build_outcome(
        facts(b"not-json\n", exit_status=0),
        decision_present=False,
    )

    assert classification.outcome == "runner_error"
    assert classification.jsonl_valid is False


def test_ambiguous_quota_and_provider_codes_are_runner_error() -> None:
    raw = facts(
        jsonl(
            {
                "type": "error",
                "error": {
                    "error_type": "usageLimitReached",
                    "nested": {"error_code": "serviceUnavailable"},
                },
            }
        ),
        exit_status=1,
    )

    classification = classify_grok_build_outcome(raw, decision_present=False)

    assert classification.outcome == "runner_error"
    assert classification.error_codes == (
        "service_unavailable",
        "usage_limit_reached",
    )


def test_success_exit_without_end_event_is_runner_error() -> None:
    raw = facts(
        jsonl({"type": "text", "data": "still running"}),
        exit_status=0,
    )

    assert classify_grok_build_outcome(raw, decision_present=False).outcome == (
        "runner_error"
    )
