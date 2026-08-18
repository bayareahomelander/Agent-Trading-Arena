"""R6: fake sessions remain one-to-one with product replicas."""

from pathlib import Path

import pytest

from arena_runtime.adapters.fake import FakeRunner, FakeRunnerError
from arena_runtime.audit import AuditArchive

from .conftest import make_request, make_script


def test_two_replicas_resume_only_their_own_sessions(tmp_path: Path) -> None:
    scripts = (
        make_script(replica_id="product-a-1", session_reference="session-a1"),
        make_script(replica_id="product-a-2", session_reference="session-a2"),
        make_script(
            replica_id="product-a-1",
            round_id="2026-08-17-late",
            session_reference="session-a1",
        ),
        make_script(
            replica_id="product-a-2",
            round_id="2026-08-17-late",
            session_reference="session-a2",
        ),
    )
    runner = FakeRunner(scripts, archive=AuditArchive(tmp_path / "archive"))
    a_workspace = tmp_path / "a"
    b_workspace = tmp_path / "b"

    a_first = runner.run(make_request(a_workspace, replica_id="product-a-1"))
    b_first = runner.run(make_request(b_workspace, replica_id="product-a-2"))
    a_second = runner.run(
        make_request(
            a_workspace,
            replica_id="product-a-1",
            round_id="2026-08-17-late",
            session_reference=a_first.session_reference,
        )
    )
    b_second = runner.run(
        make_request(
            b_workspace,
            replica_id="product-a-2",
            round_id="2026-08-17-late",
            session_reference=b_first.session_reference,
        )
    )

    assert a_second.session_reference == "session-a1"
    assert b_second.session_reference == "session-a2"


def test_cross_replica_session_is_rejected_before_decision_write(
    tmp_path: Path,
) -> None:
    scripts = (
        make_script(replica_id="product-a-1", session_reference="session-a1"),
        make_script(replica_id="product-a-2", session_reference="session-a2"),
        make_script(
            replica_id="product-a-1",
            round_id="2026-08-17-late",
            session_reference="session-a1",
        ),
    )
    archive = AuditArchive(tmp_path / "archive")
    runner = FakeRunner(scripts, archive=archive)
    runner.run(make_request(tmp_path / "a", replica_id="product-a-1"))
    b_result = runner.run(make_request(tmp_path / "b", replica_id="product-a-2"))
    late_workspace = tmp_path / "a-late"

    with pytest.raises(FakeRunnerError) as exc:
        runner.run(
            make_request(
                late_workspace,
                replica_id="product-a-1",
                round_id="2026-08-17-late",
                session_reference=b_result.session_reference,
            )
        )

    assert exc.value.path == "session_reference"
    assert not (late_workspace / "outbox" / "decision.json").exists()


def test_same_session_cannot_be_assigned_to_two_replicas(tmp_path: Path) -> None:
    scripts = (
        make_script(replica_id="product-a-1", session_reference="shared-session"),
        make_script(replica_id="product-a-2", session_reference="shared-session"),
    )
    runner = FakeRunner(scripts, archive=AuditArchive(tmp_path / "archive"))
    runner.run(make_request(tmp_path / "a", replica_id="product-a-1"))
    b_workspace = tmp_path / "b"

    with pytest.raises(FakeRunnerError) as exc:
        runner.run(make_request(b_workspace, replica_id="product-a-2"))

    assert exc.value.path == "session_reference"
    assert not (b_workspace / "outbox" / "decision.json").exists()
