"""R17: one shared preflight failure pauses every product."""

from pathlib import Path

import pytest

from arena_runtime.audit import parse_audit_event
from arena_runtime.orchestrator import COMMON_DATA_UNAVAILABLE

from .conftest import PRODUCT_A, PRODUCT_B, REPLICA_A1, REPLICA_B1, run_barrier, script_for


@pytest.mark.parametrize(
    ("failure_reason", "pause_reason"),
    [
        ("quota_exhausted", "quota_exhausted"),
        ("provider_unavailable", "provider_unavailable"),
    ],
)
def test_one_shared_product_failure_pauses_the_whole_field(
    tmp_path: Path,
    failure_reason: str,
    pause_reason: str,
) -> None:
    result, archive, runner = run_barrier(
        tmp_path,
        scripts=(
            script_for(PRODUCT_A, REPLICA_A1),
            script_for(
                PRODUCT_B,
                REPLICA_B1,
                ready=False,
                failure_reason=failure_reason,
            ),
        ),
    )

    assert result.ready is False
    assert result.reason_codes == (failure_reason,)
    assert [item.ready for item in result.preflight_results] == [True, False]
    assert runner._completed_requests == set()  # noqa: SLF001

    events = [
        parse_audit_event(line)
        for line in archive.events_path.read_text(encoding="utf-8").splitlines()
    ]
    assert [event.event_type for event in events][-1] == "pause"
    assert events[-1].payload.reason == pause_reason
    assert events[-1].product_id is None
    assert events[-1].replica_id is None
    assert "replica_launched" not in [event.event_type for event in events]


def test_common_data_failure_pauses_even_when_products_are_ready(
    tmp_path: Path,
) -> None:
    result, archive, runner = run_barrier(
        tmp_path,
        scripts=(
            script_for(PRODUCT_A, REPLICA_A1),
            script_for(PRODUCT_B, REPLICA_B1),
        ),
        common_data_status=COMMON_DATA_UNAVAILABLE,
    )

    assert result.ready is False
    assert result.reason_codes == ("common_data_unavailable",)
    assert [item.ready for item in result.preflight_results] == [True, True]
    assert runner._completed_requests == set()  # noqa: SLF001

    events = [
        parse_audit_event(line)
        for line in archive.events_path.read_text(encoding="utf-8").splitlines()
    ]
    assert events[-1].event_type == "pause"
    assert events[-1].payload.reason == "common_data_unavailable"
