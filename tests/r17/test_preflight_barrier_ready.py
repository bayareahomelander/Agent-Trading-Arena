"""R17: all-ready due replicas may proceed; no runner is launched."""

from pathlib import Path

from arena_runtime.audit import parse_audit_event

from .conftest import (
    PRODUCT_A,
    PRODUCT_B,
    REPLICA_A1,
    REPLICA_B1,
    REPLICA_B2,
    run_barrier,
    script_for,
)


def test_all_ready_due_replicas_proceed_without_launching(tmp_path: Path) -> None:
    result, archive, runner = run_barrier(
        tmp_path,
        scripts=(
            script_for(PRODUCT_A, REPLICA_A1),
            script_for(PRODUCT_B, REPLICA_B1),
        ),
    )

    assert result.ready is True
    assert result.reason_codes == ()
    assert result.due_replica_ids == (REPLICA_A1, REPLICA_B1)
    assert result.skipped_replica_ids == (REPLICA_B2,)
    assert [item.ready for item in result.preflight_results] == [True, True]
    assert runner._completed_requests == set()  # noqa: SLF001 - run must stay unused

    event_types = [
        parse_audit_event(line).event_type
        for line in archive.events_path.read_text(encoding="utf-8").splitlines()
    ]
    assert event_types == [
        "preflight_started",
        "preflight_completed",
        "preflight_started",
        "preflight_completed",
    ]
    assert "replica_launched" not in event_types
    assert "pause" not in event_types
