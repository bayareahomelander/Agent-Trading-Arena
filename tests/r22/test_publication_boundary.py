"""R22: publication does not mark close or run baselines."""

import inspect

from arena_runtime.orchestrator import publish_candidates


def test_publish_candidates_does_not_close_or_run_baselines() -> None:
    source = inspect.getsource(publish_candidates)

    assert "mark_to_close" not in source
    assert "final_nlv" not in source
    assert "run_baselines" not in source
    assert "dump_baselines_result" not in source
    assert "cli" not in source
