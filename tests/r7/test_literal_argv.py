"""R7: paths and prompt text remain literal argv values."""

import json
from pathlib import Path

from arena_runtime.process import run_process

from .conftest import argv, deadline, sanitized_environment


def test_spaces_and_shell_metacharacters_are_literal(tmp_path: Path) -> None:
    cwd = tmp_path / "working directory with spaces"
    cwd.mkdir()
    arguments = (
        "path with spaces/file.json",
        "prompt & echo SHOULD_NOT_RUN | more",
        "$(touch should-not-exist)",
        "`echo still-literal`",
        "semi;colon > redirect.txt",
    )

    facts = run_process(
        argv("echo", *arguments),
        cwd=cwd,
        environment=sanitized_environment(),
        deadline=deadline(),
    )

    assert json.loads(facts.stdout) == list(arguments)
    assert not (cwd / "redirect.txt").exists()
    assert not (cwd / "should-not-exist").exists()
