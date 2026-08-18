"""Helpers for sealed RunnerResult fixtures."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from arena_runtime.runner import RUNNER_CONTRACT_VERSION, RunnerResult

ET = ZoneInfo("America/New_York")
STARTED = datetime(2026, 8, 17, 10, tzinfo=ET)
FINISHED = datetime(2026, 8, 17, 10, 5, tzinfo=ET)
ROUND_ID = "2026-08-17-morning"
CHECKSUM = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"


def make_result(
    *,
    product_id: str = "product-a",
    replica_id: str = "product-a-1",
    outcome: str = "completed",
) -> RunnerResult:
    present = outcome == "completed"
    return RunnerResult(
        contract_version=RUNNER_CONTRACT_VERSION,
        product_id=product_id,
        replica_id=replica_id,
        round_id=ROUND_ID,
        outcome=outcome,
        started_at=STARTED,
        finished_at=FINISHED,
        exit_status=0 if present else 1,
        decision_present=present,
        decision_checksum=CHECKSUM if present else None,
    )
