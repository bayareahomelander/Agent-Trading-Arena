"""R23: close marks do not run baselines or invent prices."""

import inspect

from arena_runtime.orchestrator import mark_official_close


def test_close_operation_does_not_run_baselines_or_guess() -> None:
    source = inspect.getsource(mark_official_close)

    assert "run_baselines" not in source
    assert "dump_baselines_result" not in source
    assert "process reports" not in source
    assert "official_closes" in source
