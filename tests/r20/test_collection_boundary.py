"""R20: collection does not parse, validate, or apply decisions."""

import inspect

from arena_runtime import orchestrator
from arena_runtime.orchestrator import collect_sealed_decisions


def test_collection_helpers_do_not_call_the_kernel() -> None:
    for name in (
        "collect_sealed_decisions",
        "_collect_one_decision",
        "_read_sealed_decision",
        "_write_staged_decision",
    ):
        source = inspect.getsource(getattr(orchestrator, name))
        assert "parse_decision" not in source
        assert "apply_decision" not in source
        assert "validate_decision" not in source
        assert "apply_order" not in source


def test_collect_function_does_not_call_the_kernel() -> None:
    source = inspect.getsource(collect_sealed_decisions)

    assert "parse_decision" not in source
    assert "apply_decision" not in source
    assert "validate_decision" not in source
    assert "apply_order" not in source
