"""R7: supervisor owns raw process mechanics, not provider meaning."""

import ast
from pathlib import Path


def test_supervisor_has_no_network_provider_or_outcome_mapping_imports() -> None:
    module = Path(__file__).parents[2] / "src" / "arena_runtime" / "process.py"
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
            "urllib",
            "xai",
        }
    )
    assert "RUNNER_OUTCOMES" not in source
    assert "shell=True" not in source
