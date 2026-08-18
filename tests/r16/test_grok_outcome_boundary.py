"""R16: outcome mapping is lifecycle-only and not round policy."""

import inspect

from arena_runtime.adapters.grok_build import classify_grok_build_outcome


def test_mapper_contains_no_round_disposition_or_kernel_logic() -> None:
    source = inspect.getsource(classify_grok_build_outcome)

    assert "void" not in source
    assert "pause" not in source
    assert "commit" not in source
    assert "arena_kernel" not in source
