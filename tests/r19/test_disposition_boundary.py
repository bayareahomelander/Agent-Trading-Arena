"""R19: disposition is a pure function with no I/O or adapter policy."""

import ast
import inspect
from pathlib import Path

from arena_runtime.disposition import decide_round_disposition


def test_disposition_module_has_no_io_or_provider_edge() -> None:
    module = (
        Path(__file__).parents[2]
        / "src"
        / "arena_runtime"
        / "disposition.py"
    )
    source = module.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(module))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".", 1)[0])

    assert roots <= {"__future__", "typing", "dataclasses", "arena_runtime"}
    assert "pathlib" not in roots
    assert "orchestrator" not in source
    assert "codex" not in source
    assert "grok" not in source
    assert "parse_decision" not in source
    assert "apply_decision" not in source


def test_decide_function_performs_no_file_or_archive_work() -> None:
    source = inspect.getsource(decide_round_disposition)

    assert "open(" not in source
    assert "append_event" not in source
    assert "write" not in source
