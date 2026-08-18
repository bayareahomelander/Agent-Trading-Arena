"""R8: isolation composes R7 without acquiring provider policy."""

import ast
from pathlib import Path


def test_isolation_has_no_provider_network_or_outcome_logic() -> None:
    module = Path(__file__).parents[2] / "src" / "arena_runtime" / "isolation.py"
    source = module.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(module))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".", 1)[0])

    assert roots.isdisjoint(
        {
            "aiohttp",
            "http",
            "httpx",
            "openai",
            "requests",
            "socket",
            "subprocess",
            "urllib",
            "xai",
        }
    )
    assert "RUNNER_OUTCOMES" not in source
