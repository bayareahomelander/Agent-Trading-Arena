"""R25: the CLI does not invent policy or edit decisions."""

import ast
import inspect
from pathlib import Path

from arena_runtime.cli import cmd_close, cmd_preflight, cmd_run_round, main


def test_cli_does_not_edit_decisions_or_wait() -> None:
    source = Path(__file__).parents[2] / "src" / "arena_runtime" / "cli.py"
    text = source.read_text(encoding="utf-8")
    tree = ast.parse(text)
    called: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            called.add(node.func.id)

    assert "preflight_round" in text
    assert "run_decision_barrier" in text
    assert "decide_round_disposition" in text
    assert "mark_official_close" in text
    assert "sleep" not in text
    assert "parse_decision" not in inspect.getsource(main)
    assert "apply_decision" not in inspect.getsource(cmd_preflight)
    assert "apply_decision" not in inspect.getsource(cmd_close)
    for command in (cmd_preflight, cmd_run_round, cmd_close):
        body = inspect.getsource(command)
        assert "while True" not in body
