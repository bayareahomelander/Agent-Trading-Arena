"""R1: the kernel stays offline and the vocabulary slice has no live edges."""

import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).parents[2]


def _import_roots(path: Path) -> set[str]:
    roots: set[str] = set()
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".", 1)[0])
    return roots


def test_arena_kernel_does_not_import_arena_runtime() -> None:
    for path in (PROJECT_ROOT / "src" / "arena_kernel").rglob("*.py"):
        assert "arena_runtime" not in _import_roots(path), path


def test_r1_runtime_modules_import_only_typing_and_their_own_package() -> None:
    allowed = {"__future__", "typing", "arena_runtime"}
    for path in (PROJECT_ROOT / "src" / "arena_runtime").glob("*.py"):
        assert _import_roots(path) <= allowed, path


def test_arena_kernel_does_not_import_process_or_network_libraries() -> None:
    forbidden = {
        "aiohttp",
        "http",
        "httpx",
        "requests",
        "socket",
        "subprocess",
        "urllib",
    }
    for path in (PROJECT_ROOT / "src" / "arena_kernel").rglob("*.py"):
        assert _import_roots(path).isdisjoint(forbidden), path
