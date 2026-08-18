"""Shared R2 contract fixtures."""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from arena_runtime.runner import (
    RUNNER_CONTRACT_VERSION,
    PreflightResult,
    RunnerRequest,
    RunnerResult,
)

ET = ZoneInfo("America/New_York")
STARTED_AT = datetime(2026, 8, 17, 10, 0, tzinfo=ET)
FINISHED_AT = datetime(2026, 8, 17, 10, 5, tzinfo=ET)
DEADLINE = datetime(2026, 8, 17, 10, 15, tzinfo=ET)
MALFORMED_DECISION = b"{not-json"
DECISION_CHECKSUM = hashlib.sha256(MALFORMED_DECISION).hexdigest()


def make_request(workspace: Path, **changes: Any) -> RunnerRequest:
    values: dict[str, Any] = {
        "contract_version": RUNNER_CONTRACT_VERSION,
        "product_id": "product-a",
        "replica_id": "product-a-1",
        "round_id": "2026-08-17-morning",
        "workspace": workspace,
        "model_reference": "registration:model",
        "configuration_reference": "registration:configuration",
        "launch_instruction": b"Frozen launch instruction",
        "deadline": DEADLINE,
        "session_reference": None,
    }
    values.update(changes)
    return RunnerRequest(**values)


def make_preflight(**changes: Any) -> PreflightResult:
    values: dict[str, Any] = {
        "contract_version": RUNNER_CONTRACT_VERSION,
        "product_id": "product-a",
        "replica_id": "product-a-1",
        "round_id": "2026-08-17-morning",
        "ready": True,
        "started_at": STARTED_AT,
        "finished_at": FINISHED_AT,
        "failure_reason": None,
        "artifact_references": ("provider/preflight",),
    }
    values.update(changes)
    return PreflightResult(**values)


def make_result(**changes: Any) -> RunnerResult:
    values: dict[str, Any] = {
        "contract_version": RUNNER_CONTRACT_VERSION,
        "product_id": "product-a",
        "replica_id": "product-a-1",
        "round_id": "2026-08-17-morning",
        "outcome": "completed",
        "started_at": STARTED_AT,
        "finished_at": FINISHED_AT,
        "exit_status": 0,
        "decision_present": True,
        "decision_checksum": DECISION_CHECKSUM,
        "session_reference": "opaque-session-a1",
        "artifact_references": ("provider/stdout", "provider/stderr"),
    }
    values.update(changes)
    return RunnerResult(**values)
