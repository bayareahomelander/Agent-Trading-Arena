"""R7: success and failure return raw exit and stream facts."""

from pathlib import Path

from arena_runtime.process import run_process

from .conftest import argv, deadline, sanitized_environment


def test_success_returns_raw_exit_and_stream_facts(tmp_path: Path) -> None:
    facts = run_process(
        argv("success"),
        cwd=tmp_path,
        environment=sanitized_environment(),
        deadline=deadline(),
    )

    assert facts.exit_status == 0
    assert facts.timed_out is False
    assert facts.stdout == b"success stdout\n"
    assert facts.stderr == b"success stderr\n"
    assert facts.stdout_truncated is False
    assert facts.stderr_truncated is False
    assert facts.started_at.tzinfo is not None
    assert facts.finished_at >= facts.started_at


def test_nonzero_exit_is_returned_without_classification(tmp_path: Path) -> None:
    facts = run_process(
        argv("fail"),
        cwd=tmp_path,
        environment=sanitized_environment(),
        deadline=deadline(),
    )

    assert facts.exit_status == 7
    assert facts.timed_out is False
    assert facts.stdout == b"failure stdout\n"
    assert facts.stderr == b"failure stderr\n"


def test_stdout_and_stderr_are_bounded_while_fully_drained(tmp_path: Path) -> None:
    facts = run_process(
        argv("spam", "10000"),
        cwd=tmp_path,
        environment=sanitized_environment(),
        deadline=deadline(),
        stdout_limit=128,
        stderr_limit=96,
    )

    assert facts.stdout == b"O" * 128
    assert facts.stderr == b"E" * 96
    assert facts.stdout_truncated is True
    assert facts.stderr_truncated is True
