"""Shared deterministic fake-runner scripts and requests."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from arena_runtime.adapters.fake import FakeRunnerScript
from arena_runtime.runner import RUNNER_CONTRACT_VERSION, RunnerRequest

ET = ZoneInfo("America/New_York")
PREFLIGHT_STARTED = datetime(2026, 8, 17, 9, 58, tzinfo=ET)
PREFLIGHT_FINISHED = datetime(2026, 8, 17, 9, 59, tzinfo=ET)
RUN_STARTED = datetime(2026, 8, 17, 10, 0, tzinfo=ET)
RUN_FINISHED = datetime(2026, 8, 17, 10, 5, tzinfo=ET)
DEADLINE = datetime(2026, 8, 17, 10, 15, tzinfo=ET)
EXACT_DECISION = b' {"round_id":"2026-08-17-morning", "broken": }\r\n'

_DEFAULT = object()


def make_script(
    *,
    product_id: str = "product-a",
    replica_id: str = "product-a-1",
    round_id: str = "2026-08-17-morning",
    outcome: str = "completed",
    decision_bytes: bytes | None | object = _DEFAULT,
    session_reference: str | None = "session-product-a-1",
    preflight_ready: bool = True,
    preflight_failure_reason: str | None = None,
    **changes: Any,
) -> FakeRunnerScript:
    if decision_bytes is _DEFAULT:
        decision_bytes = EXACT_DECISION if outcome == "completed" else None
    values: dict[str, Any] = {
        "product_id": product_id,
        "replica_id": replica_id,
        "round_id": round_id,
        "preflight_ready": preflight_ready,
        "preflight_failure_reason": preflight_failure_reason,
        "preflight_started_at": PREFLIGHT_STARTED,
        "preflight_finished_at": PREFLIGHT_FINISHED,
        "outcome": outcome,
        "run_started_at": RUN_STARTED,
        "run_finished_at": RUN_FINISHED,
        "exit_status": 0 if outcome == "completed" else None,
        "decision_bytes": decision_bytes,
        "session_reference": session_reference,
    }
    values.update(changes)
    return FakeRunnerScript(**values)


def make_request(
    workspace: Path,
    *,
    product_id: str = "product-a",
    replica_id: str = "product-a-1",
    round_id: str = "2026-08-17-morning",
    session_reference: str | None = None,
) -> RunnerRequest:
    return RunnerRequest(
        contract_version=RUNNER_CONTRACT_VERSION,
        product_id=product_id,
        replica_id=replica_id,
        round_id=round_id,
        workspace=workspace,
        model_reference="registration:model",
        configuration_reference="registration:configuration",
        launch_instruction=b"Frozen launch instruction",
        deadline=DEADLINE,
        session_reference=session_reference,
    )
