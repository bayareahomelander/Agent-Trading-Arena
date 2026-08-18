"""R6: FakeRunner remains deterministic and provider-free."""

import ast
from pathlib import Path


def test_fake_runner_has_no_process_clock_network_or_provider_imports() -> None:
    module = (
        Path(__file__).parents[2]
        / "src"
        / "arena_runtime"
        / "adapters"
        / "fake.py"
    )
    tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
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
            "time",
            "urllib",
            "xai",
        }
    )
