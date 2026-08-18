"""R9: Codex preflight uses shared runtime layers and starts no agent task."""

import ast
from pathlib import Path

from arena_runtime.runner import Runner

from .conftest import make_case


def test_r9_adapter_is_preflight_only(tmp_path: Path) -> None:
    adapter, _, _, _, _ = make_case(tmp_path)

    assert not isinstance(adapter, Runner)
    assert not hasattr(adapter, "run")


def test_codex_adapter_has_no_direct_network_or_subprocess_edge() -> None:
    module = (
        Path(__file__).parents[2]
        / "src"
        / "arena_runtime"
        / "adapters"
        / "codex.py"
    )
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
            "requests",
            "socket",
            "subprocess",
            "urllib",
        }
    )
    assert "run_isolated_process" in source
    assert 'arguments=("exec", "--help")' in source
