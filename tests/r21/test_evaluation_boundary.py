"""R21: evaluation does not publish books, mark close, or run baselines."""

import inspect

from arena_runtime.orchestrator import evaluate_candidates


def test_evaluate_candidates_does_not_publish_or_close() -> None:
    source = inspect.getsource(evaluate_candidates)

    assert "publish_round" not in source
    assert "mark_to_close" not in source
    assert "final_nlv" not in source
    assert "run_baselines" not in source
    assert "dump_baselines_result" not in source
    assert "outbox/decision.json" not in source

