"""Helpers for sealed decision-collection fixtures."""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from arena_kernel.workspace import OUTBOX_DECISION_FILE
from arena_runtime.disposition import COMMON_DATA_AVAILABLE, decide_round_disposition
from arena_runtime.orchestrator import (
    DecisionBarrierResult,
    collect_sealed_decisions,
)
from arena_runtime.runner import RUNNER_CONTRACT_VERSION, RunnerResult

ET = ZoneInfo("America/New_York")
STARTED = datetime(2026, 8, 17, 10, tzinfo=ET)
FINISHED = datetime(2026, 8, 17, 10, 5, tzinfo=ET)
DEADLINE = datetime(2026, 8, 17, 10, 15, tzinfo=ET)
ROUND_ID = "2026-08-17-morning"
SNAPSHOT = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
DECISION_A = b'{"round_id":"2026-08-17-morning","action":"hold","not":"parsed"}\n'
DECISION_B = b" {not valid json so R20 must not parse this \r\n"


def checksum_of(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def make_result(
    *,
    product_id: str = "product-a",
    replica_id: str = "product-a-1",
    outcome: str = "completed",
    payload: bytes | None = None,
) -> RunnerResult:
    present = payload is not None
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
        decision_checksum=checksum_of(payload) if present else None,
    )


def write_decision(workspace: Path, payload: bytes) -> Path:
    path = workspace / OUTBOX_DECISION_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def make_workspace(root: Path, replica_id: str, payload: bytes | None = None) -> Path:
    workspace = (root / "workspaces" / replica_id).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "outbox").mkdir(exist_ok=True)
    if payload is not None:
        write_decision(workspace, payload)
    return workspace


def make_barrier(results: tuple[RunnerResult, ...]) -> DecisionBarrierResult:
    return DecisionBarrierResult(
        contract_version=RUNNER_CONTRACT_VERSION,
        round_id=ROUND_ID,
        snapshot_checksum=SNAPSHOT,
        deadline=DEADLINE,
        results=results,
    )


def collect(
    root: Path,
    results: tuple[RunnerResult, ...],
    *,
    payloads: dict[str, bytes | None] | None = None,
    common_data_status: str = COMMON_DATA_AVAILABLE,
    workspaces: dict[str, Path] | None = None,
    staging_root: Path | None = None,
):
    if workspaces is None:
        resolved_payloads = payloads or {}
        workspaces = {
            result.replica_id: make_workspace(
                root,
                result.replica_id,
                resolved_payloads.get(result.replica_id),
            )
            for result in results
        }
    barrier = make_barrier(results)
    disposition = decide_round_disposition(results, common_data_status)
    return collect_sealed_decisions(
        barrier=barrier,
        disposition=disposition,
        workspaces=workspaces,
        staging_root=staging_root or (root / "staging").resolve(),
    )
