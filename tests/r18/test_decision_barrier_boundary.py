"""R18: the barrier does not parse decisions or apply matching."""

import inspect

from arena_runtime.orchestrator import run_decision_barrier


def test_decision_barrier_does_not_parse_or_match_decisions() -> None:
    source = inspect.getsource(run_decision_barrier)

    assert "parse_decision" not in source
    assert "apply_decision" not in source
    assert "apply_order" not in source
    assert "validate_decision" not in source
    assert "round_disposition" not in source
