"""R17: the barrier does not publish, launch, or branch on providers."""

import ast
import inspect
from pathlib import Path

from arena_runtime.orchestrator import preflight_round


def test_orchestrator_has_no_provider_or_publish_edge() -> None:
    module = (
        Path(__file__).parents[2]
        / "src"
        / "arena_runtime"
        / "orchestrator.py"
    )
    source = module.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(module))
    roots: set[str] = set()
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".", 1)[0])
            imported.add(node.module)

    assert roots.isdisjoint(
        {
            "aiohttp",
            "http",
            "httpx",
            "requests",
            "socket",
            "subprocess",
            "urllib",
        }
    )
    assert "arena_kernel.marketdata" not in imported
    assert "publish_round" not in source
    assert "codex" not in source
    assert "grok" not in source


def test_barrier_function_does_not_start_runners() -> None:
    source = inspect.getsource(preflight_round)

    assert ".run(" not in source
    assert "publish_round" not in source
