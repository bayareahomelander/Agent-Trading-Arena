"""R6: FakeRunner emits the required normalized audit sequence."""

from pathlib import Path

from arena_runtime.adapters.fake import FakeRunner
from arena_runtime.audit import AuditArchive, parse_audit_event

from .conftest import EXACT_DECISION, make_request, make_script


def _event_types(archive: AuditArchive) -> list[str]:
    return [
        parse_audit_event(line).event_type
        for line in archive.events_path.read_text(encoding="utf-8").splitlines()
    ]


def test_ready_completed_run_emits_required_sequence(tmp_path: Path) -> None:
    archive = AuditArchive(tmp_path / "archive")
    runner = FakeRunner((make_script(),), archive=archive)
    request = make_request(tmp_path / "workspace")

    runner.preflight(request)
    runner.run(request)

    assert _event_types(archive) == [
        "preflight_started",
        "preflight_completed",
        "replica_launched",
        "decision_collected",
        "replica_completed",
    ]
    assert (request.workspace / "outbox" / "decision.json").read_bytes() == (
        EXACT_DECISION
    )


def test_timeout_records_termination_before_collection_and_completion(
    tmp_path: Path,
) -> None:
    archive = AuditArchive(tmp_path / "archive")
    runner = FakeRunner(
        (make_script(outcome="timeout", session_reference=None),),
        archive=archive,
    )
    request = make_request(tmp_path / "workspace")

    runner.run(request)

    assert _event_types(archive) == [
        "replica_launched",
        "replica_terminated",
        "decision_collected",
        "replica_completed",
    ]


def test_failed_preflight_emits_started_and_completed_only(tmp_path: Path) -> None:
    archive = AuditArchive(tmp_path / "archive")
    runner = FakeRunner(
        (
            make_script(
                preflight_ready=False,
                preflight_failure_reason="not ready",
            ),
        ),
        archive=archive,
    )
    request = make_request(tmp_path / "workspace")

    result = runner.preflight(request)

    assert result.ready is False
    assert result.failure_reason == "not ready"
    assert _event_types(archive) == ["preflight_started", "preflight_completed"]
    assert not (request.workspace / "outbox" / "decision.json").exists()
