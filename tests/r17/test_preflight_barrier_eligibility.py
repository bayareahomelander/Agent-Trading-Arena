"""R17: inactive and DQ replicas are not due and are not preflighted."""

from pathlib import Path

from arena_runtime.audit import parse_audit_event
from arena_runtime.orchestrator import (
    REPLICA_STATUS_ACTIVE,
    REPLICA_STATUS_DQ_REFUSAL,
    REPLICA_STATUS_INACTIVE,
    ReplicaDuty,
)

from .conftest import (
    PRODUCT_A,
    PRODUCT_B,
    REPLICA_A1,
    REPLICA_B1,
    REPLICA_B2,
    run_barrier,
    script_for,
)


def test_inactive_and_dq_replicas_are_skipped(tmp_path: Path) -> None:
    result, archive, _ = run_barrier(
        tmp_path,
        scripts=(
            script_for(PRODUCT_A, REPLICA_A1),
            script_for(PRODUCT_B, REPLICA_B1),
        ),
        duties=(
            ReplicaDuty(PRODUCT_A, REPLICA_A1, REPLICA_STATUS_ACTIVE),
            ReplicaDuty(PRODUCT_B, REPLICA_B1, REPLICA_STATUS_INACTIVE),
            ReplicaDuty(PRODUCT_B, REPLICA_B2, REPLICA_STATUS_DQ_REFUSAL),
        ),
    )

    assert result.ready is True
    assert result.due_replica_ids == (REPLICA_A1,)
    assert result.skipped_replica_ids == (REPLICA_B1, REPLICA_B2)
    assert [item.replica_id for item in result.preflight_results] == [REPLICA_A1]

    replica_ids = [
        parse_audit_event(line).replica_id
        for line in archive.events_path.read_text(encoding="utf-8").splitlines()
    ]
    assert set(replica_ids) == {REPLICA_A1}
    assert REPLICA_B1 not in replica_ids
    assert REPLICA_B2 not in replica_ids
