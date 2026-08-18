"""R17: every due preflight result is archived before the barrier decision."""

from pathlib import Path

from arena_runtime.audit import parse_audit_event

from .conftest import PRODUCT_A, PRODUCT_B, REPLICA_A1, REPLICA_B1, run_barrier, script_for


def test_every_due_preflight_pair_is_archived(tmp_path: Path) -> None:
    result, archive, _ = run_barrier(
        tmp_path,
        scripts=(
            script_for(PRODUCT_A, REPLICA_A1),
            script_for(
                PRODUCT_B,
                REPLICA_B1,
                ready=False,
                failure_reason="quota_exhausted",
            ),
        ),
    )

    events = [
        parse_audit_event(line)
        for line in archive.events_path.read_text(encoding="utf-8").splitlines()
    ]
    completed = [event for event in events if event.event_type == "preflight_completed"]
    assert len(completed) == 2
    assert {(event.product_id, event.replica_id, event.payload.ready) for event in completed} == {
        (PRODUCT_A, REPLICA_A1, True),
        (PRODUCT_B, REPLICA_B1, False),
    }
    assert completed[1].payload.failure_reason == "quota_exhausted"
    assert [item.ready for item in result.preflight_results] == [True, False]
