"""R6: invalid fake scripts and request reuse fail explicitly."""

from pathlib import Path

import pytest

from arena_runtime.adapters.fake import FakeRunner, FakeRunnerError
from arena_runtime.audit import AuditArchive

from .conftest import make_request, make_script


def test_completed_script_requires_decision_bytes() -> None:
    with pytest.raises(FakeRunnerError) as exc:
        make_script(outcome="completed", decision_bytes=None)

    assert exc.value.path == "decision_present"


def test_duplicate_script_identity_is_rejected(tmp_path: Path) -> None:
    script = make_script()

    with pytest.raises(FakeRunnerError) as exc:
        FakeRunner((script, script), archive=AuditArchive(tmp_path / "archive"))

    assert exc.value.path == "scripts.1"


def test_unknown_request_identity_is_rejected(tmp_path: Path) -> None:
    runner = FakeRunner(
        (make_script(),),
        archive=AuditArchive(tmp_path / "archive"),
    )

    with pytest.raises(FakeRunnerError) as exc:
        runner.run(
            make_request(
                tmp_path / "workspace",
                round_id="2026-08-17-late",
            )
        )

    assert exc.value.path == "round_id"


def test_script_cannot_run_twice(tmp_path: Path) -> None:
    runner = FakeRunner(
        (make_script(),),
        archive=AuditArchive(tmp_path / "archive"),
    )
    request = make_request(tmp_path / "workspace")
    runner.run(request)

    with pytest.raises(FakeRunnerError) as exc:
        runner.run(request)

    assert exc.value.path == "round_id"


def test_missing_decision_script_does_not_create_a_file(tmp_path: Path) -> None:
    runner = FakeRunner(
        (make_script(outcome="missing_decision", session_reference=None),),
        archive=AuditArchive(tmp_path / "archive"),
    )
    request = make_request(tmp_path / "workspace")

    result = runner.run(request)

    assert result.decision_present is False
    assert not (request.workspace / "outbox" / "decision.json").exists()
