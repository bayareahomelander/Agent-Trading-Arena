"""R7: the absolute deadline terminates the complete process tree."""

import time
from pathlib import Path

from arena_runtime.process import run_process

from .conftest import argv, deadline, sanitized_environment


def test_deadline_marks_timeout_and_terminates_parent(tmp_path: Path) -> None:
    facts = run_process(
        argv("sleep", "30"),
        cwd=tmp_path,
        environment=sanitized_environment(),
        deadline=deadline(0.35),
    )

    assert facts.timed_out is True
    assert facts.exit_status != 0


def test_timeout_terminates_spawned_child(tmp_path: Path) -> None:
    pid_file = tmp_path / "child.pid"
    heartbeat = tmp_path / "heartbeat.txt"

    facts = run_process(
        argv("spawn-child", str(pid_file), str(heartbeat)),
        cwd=tmp_path,
        environment=sanitized_environment(),
        deadline=deadline(0.75),
    )

    assert facts.timed_out is True
    assert pid_file.is_file()
    assert heartbeat.is_file()
    before = heartbeat.read_text(encoding="ascii")
    time.sleep(0.35)
    after = heartbeat.read_text(encoding="ascii")
    assert after == before
