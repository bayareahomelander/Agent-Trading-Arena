"""R24: baselines stay non-contestant and do not invent fallbacks."""

import inspect

from arena_runtime.orchestrator import run_archived_baselines


def test_archived_baselines_call_b7_without_time_fallback() -> None:
    source = inspect.getsource(run_archived_baselines)

    assert "run_baselines" in source
    assert "dump_baselines_result" in source
    assert "int(time" not in source
    assert "time.time" not in source
    assert "Random(" not in source
    assert "mark_to_close" not in source
