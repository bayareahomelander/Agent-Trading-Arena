"""Deterministic in-process runner for contracts and orchestration tests.

R6 executes caller-supplied scripts only. It uses no subprocess, real clock,
network, subscription, provider output, or trading interpretation.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Final, Sequence
import threading

from arena_kernel.types import format_et_timestamp
from arena_kernel.schema.errors import FieldError
from arena_runtime.audit import AuditArchive, append_runner_event
from arena_runtime.runner import (
    RUNNER_CONTRACT_VERSION,
    PreflightResult,
    RunnerContractError,
    RunnerRequest,
    RunnerResult,
    require_matching_identity,
)

OUTBOX_DECISION_PATH: Final[str] = "outbox/decision.json"


class FakeRunnerError(FieldError):
    """Invalid or unavailable fake script with a stable field path."""


@dataclass(frozen=True)
class FakeRunnerScript:
    """All deterministic facts returned for one request identity."""

    product_id: str
    replica_id: str
    round_id: str
    preflight_ready: bool
    preflight_failure_reason: str | None
    preflight_started_at: datetime
    preflight_finished_at: datetime
    outcome: str
    run_started_at: datetime
    run_finished_at: datetime
    exit_status: int | None
    decision_bytes: bytes | None
    session_reference: str | None

    def __post_init__(self) -> None:
        if self.decision_bytes is not None and not isinstance(self.decision_bytes, bytes):
            raise FakeRunnerError("decision_bytes", "expected bytes or null")
        checksum = (
            hashlib.sha256(self.decision_bytes).hexdigest()
            if self.decision_bytes is not None
            else None
        )
        try:
            PreflightResult(
                contract_version=RUNNER_CONTRACT_VERSION,
                product_id=self.product_id,
                replica_id=self.replica_id,
                round_id=self.round_id,
                ready=self.preflight_ready,
                started_at=self.preflight_started_at,
                finished_at=self.preflight_finished_at,
                failure_reason=self.preflight_failure_reason,
            )
            RunnerResult(
                contract_version=RUNNER_CONTRACT_VERSION,
                product_id=self.product_id,
                replica_id=self.replica_id,
                round_id=self.round_id,
                outcome=self.outcome,
                started_at=self.run_started_at,
                finished_at=self.run_finished_at,
                exit_status=self.exit_status,
                decision_present=self.decision_bytes is not None,
                decision_checksum=checksum,
                session_reference=self.session_reference,
            )
        except RunnerContractError as exc:
            raise FakeRunnerError(exc.path, exc.message) from exc


class FakeRunner:
    """Provider-neutral runner driven entirely by immutable scripts."""

    def __init__(
        self,
        scripts: Sequence[FakeRunnerScript],
        *,
        archive: AuditArchive,
    ) -> None:
        if not isinstance(archive, AuditArchive):
            raise FakeRunnerError("archive", "expected an AuditArchive")
        self._archive = archive
        self._scripts: dict[tuple[str, str, str], FakeRunnerScript] = {}
        for index, script in enumerate(scripts):
            if not isinstance(script, FakeRunnerScript):
                raise FakeRunnerError(f"scripts.{index}", "expected FakeRunnerScript")
            key = _identity_key(script.product_id, script.replica_id, script.round_id)
            if key in self._scripts:
                raise FakeRunnerError(f"scripts.{index}", "duplicate request identity")
            self._scripts[key] = script
        if not self._scripts:
            raise FakeRunnerError("scripts", "must contain at least one script")
        self._sessions_by_replica: dict[tuple[str, str], str] = {}
        self._replica_by_session: dict[str, tuple[str, str]] = {}
        self._completed_requests: set[tuple[str, str, str]] = set()
        self._lock = threading.Lock()

    def preflight(self, request: RunnerRequest) -> PreflightResult:
        """Return scripted readiness and emit the normalized preflight pair."""

        with self._lock:
            script = self._script_for(request)
            result = PreflightResult(
                contract_version=RUNNER_CONTRACT_VERSION,
                product_id=request.product_id,
                replica_id=request.replica_id,
                round_id=request.round_id,
                ready=script.preflight_ready,
                started_at=script.preflight_started_at,
                finished_at=script.preflight_finished_at,
                failure_reason=script.preflight_failure_reason,
            )
            require_matching_identity(request, result)
            self._append_audit(
                request,
                event_type="preflight_started",
                timestamp=script.preflight_started_at,
                payload={},
            )
            self._append_audit(
                request,
                event_type="preflight_completed",
                timestamp=script.preflight_finished_at,
                payload={
                    "ready": result.ready,
                    "failure_reason": result.failure_reason,
                },
            )
            return result

    def run(self, request: RunnerRequest) -> RunnerResult:
        """Run one script, optionally writing its exact decision bytes."""

        with self._lock:
            script = self._script_for(request)
            key = _identity_key(request.product_id, request.replica_id, request.round_id)
            if key in self._completed_requests:
                raise FakeRunnerError("round_id", "script has already run")
            self._validate_incoming_session(request)
            self._validate_outgoing_session(request, script.session_reference)
            self._append_audit(
                request,
                event_type="replica_launched",
                timestamp=script.run_started_at,
                payload={
                    "deadline": format_et_timestamp(request.deadline),
                    "session_reference": request.session_reference,
                },
            )

            decision_checksum = self._write_decision(request, script.decision_bytes)
            decision_present = script.decision_bytes is not None

            if script.outcome == "timeout":
                self._append_audit(
                    request,
                    event_type="replica_terminated",
                    timestamp=script.run_finished_at,
                    payload={
                        "reason": "deadline",
                        "exit_status": script.exit_status,
                    },
                )

            self._append_audit(
                request,
                event_type="decision_collected",
                timestamp=script.run_finished_at,
                payload={
                    "decision_present": decision_present,
                    "decision_checksum": decision_checksum,
                },
            )
            result = RunnerResult(
                contract_version=RUNNER_CONTRACT_VERSION,
                product_id=request.product_id,
                replica_id=request.replica_id,
                round_id=request.round_id,
                outcome=script.outcome,
                started_at=script.run_started_at,
                finished_at=script.run_finished_at,
                exit_status=script.exit_status,
                decision_present=decision_present,
                decision_checksum=decision_checksum,
                session_reference=script.session_reference,
            )
            require_matching_identity(request, result)
            self._register_outgoing_session(request, result.session_reference)
            self._append_audit(
                request,
                event_type="replica_completed",
                timestamp=script.run_finished_at,
                payload={
                    "outcome": result.outcome,
                    "exit_status": result.exit_status,
                    "session_reference": result.session_reference,
                },
            )
            self._completed_requests.add(key)
            return result

    def _script_for(self, request: RunnerRequest) -> FakeRunnerScript:
        if not isinstance(request, RunnerRequest):
            raise FakeRunnerError("request", "expected RunnerRequest")
        key = _identity_key(request.product_id, request.replica_id, request.round_id)
        try:
            return self._scripts[key]
        except KeyError as exc:
            raise FakeRunnerError("round_id", "no script for request identity") from exc

    def _validate_incoming_session(self, request: RunnerRequest) -> None:
        replica_key = (request.product_id, request.replica_id)
        expected = self._sessions_by_replica.get(replica_key)
        if expected is None:
            if request.session_reference is not None:
                raise FakeRunnerError(
                    "session_reference",
                    "no session is registered for this replica",
                )
            return
        if request.session_reference != expected:
            raise FakeRunnerError(
                "session_reference",
                "does not match the session registered for this replica",
            )

    def _register_outgoing_session(
        self,
        request: RunnerRequest,
        session_reference: str | None,
    ) -> None:
        if session_reference is None:
            return
        self._validate_outgoing_session(request, session_reference)
        replica_key = (request.product_id, request.replica_id)
        self._sessions_by_replica[replica_key] = session_reference
        self._replica_by_session[session_reference] = replica_key

    def _validate_outgoing_session(
        self,
        request: RunnerRequest,
        session_reference: str | None,
    ) -> None:
        if session_reference is None:
            return
        replica_key = (request.product_id, request.replica_id)
        incoming = request.session_reference
        if incoming is not None and session_reference != incoming:
            raise FakeRunnerError(
                "session_reference",
                "resumed session reference must remain unchanged",
            )
        owner = self._replica_by_session.get(session_reference)
        if owner is not None and owner != replica_key:
            raise FakeRunnerError(
                "session_reference",
                "session reference is already mapped to another replica",
            )
        existing = self._sessions_by_replica.get(replica_key)
        if existing is not None and existing != session_reference:
            raise FakeRunnerError(
                "session_reference",
                "replica is already mapped to another session",
            )

    def _write_decision(
        self,
        request: RunnerRequest,
        decision_bytes: bytes | None,
    ) -> str | None:
        if decision_bytes is None:
            return None
        target = request.workspace / OUTBOX_DECISION_PATH
        workspace = request.workspace.resolve(strict=False)
        resolved_target = target.resolve(strict=False)
        if not resolved_target.is_relative_to(workspace):
            raise FakeRunnerError("workspace", "decision path escapes workspace")
        try:
            resolved_target.parent.mkdir(parents=True, exist_ok=True)
            resolved_target.write_bytes(decision_bytes)
        except OSError as exc:
            raise FakeRunnerError(
                "workspace",
                f"cannot write scripted decision: {exc}",
            ) from exc
        return hashlib.sha256(decision_bytes).hexdigest()

    def _append_audit(
        self,
        request: RunnerRequest,
        *,
        event_type: str,
        timestamp: datetime,
        payload: dict[str, object],
    ) -> None:
        append_runner_event(
            self._archive,
            event_type=event_type,
            product_id=request.product_id,
            replica_id=request.replica_id,
            round_id=request.round_id,
            timestamp=timestamp,
            payload=payload,
        )


def _identity_key(product_id: str, replica_id: str, round_id: str) -> tuple[str, str, str]:
    return product_id, replica_id, round_id
