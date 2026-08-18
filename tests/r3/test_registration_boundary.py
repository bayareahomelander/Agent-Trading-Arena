"""R3: registration parsing has no CLI, auth-store, or provider behavior."""

import ast
from pathlib import Path


def test_registration_module_imports_only_local_parsing_dependencies() -> None:
    module = Path(__file__).parents[2] / "src" / "arena_runtime" / "registration.py"
    tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".", 1)[0])

    assert roots <= {
        "__future__",
        "arena_kernel",
        "dataclasses",
        "datetime",
        "typing",
        "urllib",
    }
