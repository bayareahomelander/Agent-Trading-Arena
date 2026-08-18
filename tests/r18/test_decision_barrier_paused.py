"""R18: a paused preflight never launches a partial field."""

from pathlib import Path

import pytest

from arena_runtime.orchestrator import OrchestratorError, run_decision_barrier
from tests.r17.conftest import PRODUCT_A, PRODUCT_B, REPLICA_A1, REPLICA_B1, run_barrier, script_for

from .conftest import write_snapshot


def test_paused_preflight_does_not_launch(tmp_path: Path) -> None:
    preflight, _, runner = run_barrier(
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
    assert preflight.ready is False
    write_snapshot(tmp_path / REPLICA_A1, product_id=PRODUCT_A, replica_id=REPLICA_A1)

    with pytest.raises(OrchestratorError) as exc:
        run_decision_barrier(
            preflight=preflight,
            requests=(),
            runners={PRODUCT_A: runner, PRODUCT_B: runner},
            snapshot_checksum="a" * 64,
        )

    assert exc.value.path == "preflight"
    assert runner._completed_requests == set()  # noqa: SLF001
