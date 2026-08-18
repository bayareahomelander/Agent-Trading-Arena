"""R18: every due request shares one deadline and snapshot checksum."""

from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from arena_runtime.orchestrator import OrchestratorError, run_decision_barrier
from tests.r17.conftest import PRODUCT_A, PRODUCT_B

from .conftest import prepare_ready_field


def test_shared_deadline_and_snapshot_checksum_are_recorded(tmp_path: Path) -> None:
    preflight, _, runner, requests, checksum = prepare_ready_field(tmp_path)
    result = run_decision_barrier(
        preflight=preflight,
        requests=requests,
        runners={PRODUCT_A: runner, PRODUCT_B: runner},
        snapshot_checksum=checksum,
    )

    assert result.snapshot_checksum == checksum
    assert result.deadline == requests[0].deadline
    assert all(request.deadline == result.deadline for request in requests)


def test_mismatched_deadline_is_rejected_before_launch(tmp_path: Path) -> None:
    preflight, _, runner, requests, checksum = prepare_ready_field(tmp_path)
    drifted = replace(
        requests[1],
        deadline=requests[1].deadline + timedelta(minutes=1),
    )

    with pytest.raises(OrchestratorError) as exc:
        run_decision_barrier(
            preflight=preflight,
            requests=(requests[0], drifted),
            runners={PRODUCT_A: runner, PRODUCT_B: runner},
            snapshot_checksum=checksum,
        )

    assert exc.value.path == "requests.deadline"
    assert runner._completed_requests == set()  # noqa: SLF001


def test_mismatched_snapshot_is_rejected_before_launch(tmp_path: Path) -> None:
    preflight, _, runner, requests, checksum = prepare_ready_field(tmp_path)
    other = requests[1].workspace / "state" / "market" / "snapshot.json"
    payload = other.read_text(encoding="utf-8").replace("10.00", "11.00", 1)
    other.write_text(payload, encoding="utf-8")

    with pytest.raises(OrchestratorError) as exc:
        run_decision_barrier(
            preflight=preflight,
            requests=requests,
            runners={PRODUCT_A: runner, PRODUCT_B: runner},
            snapshot_checksum=checksum,
        )

    assert exc.value.path == "snapshot_checksum"
    assert runner._completed_requests == set()  # noqa: SLF001
