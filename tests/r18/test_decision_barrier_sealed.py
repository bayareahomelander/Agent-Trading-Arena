"""R18: early finish grants no extra round and decisions stay sealed."""

from pathlib import Path

from arena_runtime.audit import parse_audit_event
from tests.r6.conftest import EXACT_DECISION

from .conftest import REPLICA_A1, REPLICA_B1, launch_barrier


def test_each_due_replica_runs_once_and_barrier_returns_sealed_metadata(
    tmp_path: Path,
) -> None:
    result, archive, runner, requests, _ = launch_barrier(tmp_path)

    assert [item.outcome for item in result.results] == ["completed", "completed"]
    assert {item.replica_id for item in result.results} == {REPLICA_A1, REPLICA_B1}
    assert runner._completed_requests == {  # noqa: SLF001
        ("product-a", REPLICA_A1, "2026-08-17-morning"),
        ("product-b", REPLICA_B1, "2026-08-17-morning"),
    }
    for request, sealed in zip(requests, result.results, strict=True):
        written = (request.workspace / "outbox" / "decision.json").read_bytes()
        assert written == EXACT_DECISION
        assert sealed.decision_present is True
        assert sealed.decision_checksum is not None

    event_types = [
        parse_audit_event(line).event_type
        for line in archive.events_path.read_text(encoding="utf-8").splitlines()
    ]
    assert event_types.count("replica_launched") == 2
    assert event_types.count("replica_completed") == 2
    assert "round_disposition_selected" not in event_types
    assert "commit_started" not in event_types
