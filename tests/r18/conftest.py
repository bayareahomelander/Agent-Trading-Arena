"""Shared concurrent decision-barrier fixtures."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from arena_kernel.workspace import SNAPSHOT_FILE
from arena_runtime.adapters.fake import FakeRunner
from arena_runtime.orchestrator import (
    published_snapshot_checksum,
    run_decision_barrier,
)
from arena_runtime.runner import RunnerRequest, RunnerResult
from tests.r17.conftest import (
    PRODUCT_A,
    PRODUCT_B,
    REPLICA_A1,
    REPLICA_B1,
    run_barrier,
    script_for,
)

COMMON_CLOCK = {
    "schema_version": "1",
    "exchange_timestamp": "2026-08-17T10:15:00-04:00",
    "timezone": "America/New_York",
    "session_status": "open",
    "round_id": "2026-08-17-morning",
    "round_start": "2026-08-17T10:00:00-04:00",
    "deadline": "2026-08-17T10:15:00-04:00",
}
COMMON_BARS = [
    {
        "symbol": "AAA",
        "bar_start": "2026-08-17T10:15:00-04:00",
        "open": "10.00",
        "high": "10.20",
        "low": "9.90",
        "close": "10.10",
        "volume": "1000",
        "vwap": "10.05",
    }
]


class OverlapRunner:
    """Test double that records overlapping run() entry without extra rounds."""

    def __init__(self, inner: FakeRunner, party_count: int) -> None:
        self.inner = inner
        self.barrier = threading.Barrier(party_count, timeout=5)
        self.starts: list[tuple[str, float]] = []
        self.finishes: list[tuple[str, float]] = []
        self._guard = threading.Lock()

    def preflight(self, request: RunnerRequest):
        return self.inner.preflight(request)

    def run(self, request: RunnerRequest) -> RunnerResult:
        with self._guard:
            self.starts.append((request.replica_id, time.monotonic()))
        self.barrier.wait()
        result = self.inner.run(request)
        with self._guard:
            self.finishes.append((request.replica_id, time.monotonic()))
        return result


def write_snapshot(workspace: Path, *, product_id: str, replica_id: str) -> None:
    snapshot_path = workspace / SNAPSHOT_FILE
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "1",
        "clock": COMMON_CLOCK,
        "bars": COMMON_BARS,
        "portfolio": {
            "schema_version": "1",
            "replica_id": replica_id,
            "product_id": product_id,
            "cash": "1000.00",
            "positions": [],
        },
    }
    snapshot_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def prepare_ready_field(
    root: Path,
    *,
    wrap_overlap: bool = False,
):
    scripts = (
        script_for(PRODUCT_A, REPLICA_A1),
        script_for(PRODUCT_B, REPLICA_B1),
    )
    preflight, archive, inner = run_barrier(root, scripts=scripts)
    assert preflight.ready
    due = [
        (PRODUCT_A, REPLICA_A1),
        (PRODUCT_B, REPLICA_B1),
    ]
    requests = []
    for product_id, replica_id in due:
        workspace = root / replica_id
        write_snapshot(workspace, product_id=product_id, replica_id=replica_id)
        requests.append(
            _request_for(preflight, workspace, product_id, replica_id),
        )
    checksum = published_snapshot_checksum(requests[0].workspace)
    runner: FakeRunner | OverlapRunner = inner
    if wrap_overlap:
        runner = OverlapRunner(inner, party_count=len(due))
    return preflight, archive, runner, tuple(requests), checksum


def _request_for(preflight, workspace: Path, product_id: str, replica_id: str):
    from tests.r6.conftest import make_request
    from tests.r17.conftest import ROUND_ID

    return make_request(
        workspace,
        product_id=product_id,
        replica_id=replica_id,
        round_id=ROUND_ID,
    )


def launch_barrier(root: Path, *, wrap_overlap: bool = False):
    preflight, archive, runner, requests, checksum = prepare_ready_field(
        root,
        wrap_overlap=wrap_overlap,
    )
    result = run_decision_barrier(
        preflight=preflight,
        requests=requests,
        runners={PRODUCT_A: runner, PRODUCT_B: runner},
        snapshot_checksum=checksum,
    )
    return result, archive, runner, requests, checksum
