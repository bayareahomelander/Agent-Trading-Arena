"""R20: collection does not parse, validate, or apply decisions."""

import ast
import inspect
from pathlib import Path

from arena_runtime.orchestrator import collect_sealed_decisions


def test_collection_does_not_import_kernel_evaluation() -> None:
    module = (
        Path(__file__).parents[2]
        / "src"
        / "arena_runtime"
        / "orchestrator.py"
    )
    source = module.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(module))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    assert "arena_kernel.schema.decision" not in imported
    assert "arena_kernel.validate" not in imported
    assert "arena_kernel.matching" not in imported
    assert "arena_kernel.ledger" not in imported
    assert "parse_decision" not in source
    assert "apply_decision" not in source
    assert "validate_decision" not in source


def test_collect_function_does_not_call_the_kernel() -> None:
    source = inspect.getsource(collect_sealed_decisions)

    assert "parse_decision" not in source
    assert "apply_decision" not in source
    assert "validate_decision" not in source
    assert "apply_order" not in source
