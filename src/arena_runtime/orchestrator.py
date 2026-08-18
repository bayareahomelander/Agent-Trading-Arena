"""Thin provider-neutral round coordination.

R17 is the all-product preflight barrier. R18 launches every due replica
concurrently after common state is published and keeps decisions sealed.
R20 copies sealed outbox bytes into immutable staging without parsing them.
"""

from __future__ import annotations

import hashlib
import os
import re
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Final, Mapping, Sequence

from arena_kernel.schema._dump import dump_json
from arena_kernel.schema.clock import clock_to_dict
from arena_kernel.schema.market import bar_to_dict, parse_snapshot
from arena_kernel.types import format_et_timestamp
from arena_kernel.workspace import OUTBOX_DECISION_FILE, SNAPSHOT_FILE
from arena_runtime.audit import AUDIT_SCHEMA_VERSION, AuditArchive, parse_audit_event
from arena_runtime.disposition import (
    REPLICA_TREATMENT_EVALUATE,
    REPLICA_TREATMENT_VOIDED,
    ROUND_TREATMENT_EVALUATE,
    ReplicaDisposition,
    RoundDisposition,
)
from arena_runtime.registration import RuntimeRegistration
from arena_runtime.runner import (
    RUNNER_CONTRACT_VERSION,
    PreflightResult,
    Runner,
    RunnerRequest,
    RunnerResult,
    require_matching_identity,
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")

REPLICA_STATUS_ACTIVE: Final[str] = "active"
REPLICA_STATUS_INACTIVE: Final[str] = "inactive"
REPLICA_STATUS_DQ_REFUSAL: Final[str] = "dq_refusal"
REPLICA_STATUSES: Final[tuple[str, ...]] = (
    REPLICA_STATUS_ACTIVE,
    REPLICA_STATUS_INACTIVE,
    REPLICA_STATUS_DQ_REFUSAL,
)

COMMON_DATA_AVAILABLE: Final[str] = "available"
COMMON_DATA_UNAVAILABLE: Final[str] = "unavailable"
COMMON_DATA_STATUSES: Final[tuple[str, ...]] = (
    COMMON_DATA_AVAILABLE,
    COMMON_DATA_UNAVAILABLE,
)

COMMON_DATA_UNAVAILABLE_REASON: Final[str] = "common_data_unavailable"
SHARED_PREFLIGHT_FAILURES: Final[frozenset[str]] = frozenset(
    {
        "quota_exhausted",
        "provider_unavailable",
        COMMON_DATA_UNAVAILABLE_REASON,
    }
)
_PAUSE_REASON_PRIORITY: Final[tuple[str, ...]] = (
    COMMON_DATA_UNAVAILABLE_REASON,
    "quota_exhausted",
    "provider_unavailable",
)


class OrchestratorError(ValueError):
    """Invalid orchestrator input with a stable field path."""

    def __init__(self, path: str, message: str) -> None:
        self.path = path
        self.message = message
        super().__init__(f"{path}: {message}")


@dataclass(frozen=True)
class ReplicaDuty:
    """Season eligibility for one registered replica in the current round."""

    product_id: str
    replica_id: str
    status: str

    def __post_init__(self) -> None:
        _require_text(self.product_id, path="product_id")
        _require_text(self.replica_id, path="replica_id")
        if self.status not in REPLICA_STATUSES:
            raise OrchestratorError(
                "status",
                f"must be one of {', '.join(REPLICA_STATUSES)}",
            )


@dataclass(frozen=True)
class PreflightBarrierResult:
    """Aggregate readiness before any publish or replica launch."""

    contract_version: str
    round_id: str
    ready: bool
    reason_codes: tuple[str, ...]
    due_replica_ids: tuple[str, ...]
    skipped_replica_ids: tuple[str, ...]
    preflight_results: tuple[PreflightResult, ...]

    def __post_init__(self) -> None:
        if self.contract_version != RUNNER_CONTRACT_VERSION:
            raise OrchestratorError(
                "contract_version",
                f"must be {RUNNER_CONTRACT_VERSION!r}",
            )
        _require_text(self.round_id, path="round_id")
        if not isinstance(self.ready, bool):
            raise OrchestratorError("ready", "expected a boolean")
        if self.ready and self.reason_codes:
            raise OrchestratorError(
                "reason_codes",
                "must be empty when the barrier is ready",
            )
        if not self.ready and not self.reason_codes:
            raise OrchestratorError(
                "reason_codes",
                "required when the barrier is paused",
            )


@dataclass(frozen=True)
class DecisionBarrierResult:
    """Sealed runner results collected after every due replica finishes."""

    contract_version: str
    round_id: str
    snapshot_checksum: str
    deadline: datetime
    results: tuple[RunnerResult, ...]

    def __post_init__(self) -> None:
        if self.contract_version != RUNNER_CONTRACT_VERSION:
            raise OrchestratorError(
                "contract_version",
                f"must be {RUNNER_CONTRACT_VERSION!r}",
            )
        _require_text(self.round_id, path="round_id")
        _require_checksum(self.snapshot_checksum)
        if self.deadline.tzinfo is None:
            raise OrchestratorError("deadline", "must be timezone-aware")


@dataclass(frozen=True)
class SealedDecisionRecord:
    """One replica's staged decision bytes or an explicit missing record."""

    product_id: str
    replica_id: str
    round_id: str
    outcome: str
    treatment: str
    decision_present: bool
    byte_length: int | None
    checksum: str | None
    staged_path: Path | None
    exposed_to_kernel: bool

    def __post_init__(self) -> None:
        if self.decision_present:
            if self.byte_length is None or self.byte_length < 0:
                raise OrchestratorError(
                    "byte_length",
                    "required when a decision file is present",
                )
            if self.checksum is None or _SHA256.fullmatch(self.checksum) is None:
                raise OrchestratorError(
                    "checksum",
                    "must be a lowercase SHA-256 hex digest when present",
                )
            if self.staged_path is None:
                raise OrchestratorError(
                    "staged_path",
                    "required when a decision file is present",
                )
        else:
            if self.byte_length is not None or self.checksum is not None:
                raise OrchestratorError(
                    "checksum",
                    "must be absent when no decision file is staged",
                )
            if self.staged_path is not None:
                raise OrchestratorError(
                    "staged_path",
                    "must be absent when no decision file is staged",
                )
            if self.exposed_to_kernel:
                raise OrchestratorError(
                    "exposed_to_kernel",
                    "missing records cannot be exposed to the kernel",
                )


@dataclass(frozen=True)
class SealedCollection:
    """Immutable staged decisions for one closed decision barrier."""

    contract_version: str
    round_id: str
    staging_root: Path
    round_treatment: str
    records: tuple[SealedDecisionRecord, ...]

    def kernel_records(self) -> tuple[SealedDecisionRecord, ...]:
        """Return only the staged decisions the kernel may later evaluate."""

        return tuple(item for item in self.records if item.exposed_to_kernel)


def collect_sealed_decisions(
    *,
    barrier: DecisionBarrierResult,
    disposition: RoundDisposition,
    workspaces: Mapping[str, Path],
    staging_root: Path,
) -> SealedCollection:
    """Copy sealed outbox bytes into staging. Do not parse or apply them."""

    pairs = _align_collection_inputs(barrier, disposition, workspaces)
    staging = _require_staging_root(
        staging_root,
        workspaces=tuple(workspace for _result, _replica, workspace in pairs),
    )
    expose_completed = disposition.treatment == ROUND_TREATMENT_EVALUATE
    records = tuple(
        _collect_one_decision(
            result,
            replica,
            workspace,
            staging_root=staging,
            expose_completed=expose_completed,
        )
        for result, replica, workspace in pairs
    )
    return SealedCollection(
        contract_version=RUNNER_CONTRACT_VERSION,
        round_id=barrier.round_id,
        staging_root=staging,
        round_treatment=disposition.treatment,
        records=records,
    )


def published_snapshot_checksum(workspace: Path) -> str:
    """Hash the published clock and bars, ignoring the replica book."""

    if not isinstance(workspace, Path):
        raise OrchestratorError("workspace", "expected a path")
    snapshot_path = workspace / SNAPSHOT_FILE
    if not snapshot_path.is_file():
        raise OrchestratorError(
            "workspace.snapshot",
            "published snapshot is missing",
        )
    snapshot = parse_snapshot(snapshot_path.read_text(encoding="utf-8"))
    payload = {
        "clock": clock_to_dict(snapshot.clock),
        "bars": [bar_to_dict(bar) for bar in snapshot.bars],
    }
    return hashlib.sha256(dump_json(payload).encode("utf-8")).hexdigest()


def run_decision_barrier(
    *,
    preflight: PreflightBarrierResult,
    requests: Sequence[RunnerRequest],
    runners: Mapping[str, Runner],
    snapshot_checksum: str,
) -> DecisionBarrierResult:
    """Launch every due replica concurrently and collect sealed results."""

    if not isinstance(preflight, PreflightBarrierResult):
        raise OrchestratorError("preflight", "expected PreflightBarrierResult")
    if not preflight.ready:
        raise OrchestratorError(
            "preflight",
            "paused field must not launch any replica",
        )
    _require_checksum(snapshot_checksum)
    due = tuple(
        ReplicaDuty(result.product_id, result.replica_id, REPLICA_STATUS_ACTIVE)
        for result in preflight.preflight_results
    )
    if tuple(duty.replica_id for duty in due) != preflight.due_replica_ids:
        raise OrchestratorError(
            "preflight.due_replica_ids",
            "does not match archived due preflight identities",
        )
    request_by_replica = _request_index(requests, due)
    runner_by_product = _runner_index(runners, due)
    for duty in due:
        runner = runner_by_product[duty.product_id]
        if not callable(getattr(runner, "run", None)):
            raise OrchestratorError(
                f"runners.{duty.product_id}",
                "expected a Runner with run",
            )
    round_id = _shared_round_id(due, request_by_replica)
    if round_id != preflight.round_id:
        raise OrchestratorError(
            "requests.round_id",
            "does not match the ready preflight round",
        )
    deadline = _shared_deadline(due, request_by_replica)
    _require_shared_snapshot(due, request_by_replica, snapshot_checksum)

    ordered = list(due)

    def _launch(duty: ReplicaDuty) -> RunnerResult:
        request = request_by_replica[duty.replica_id]
        return require_matching_identity(
            request,
            runner_by_product[duty.product_id].run(request),
        )

    collected: dict[str, RunnerResult] = {}
    first_error: BaseException | None = None
    with ThreadPoolExecutor(max_workers=max(len(ordered), 1)) as pool:
        futures = {pool.submit(_launch, duty): duty for duty in ordered}
        wait(futures)
        for future, duty in futures.items():
            try:
                collected[duty.replica_id] = future.result()
            except BaseException as exc:  # noqa: BLE001 - wait for every worker
                if first_error is None:
                    first_error = exc
    if first_error is not None:
        raise OrchestratorError(
            "run",
            "a due replica failed before the decision barrier closed",
        ) from first_error
    return DecisionBarrierResult(
        contract_version=RUNNER_CONTRACT_VERSION,
        round_id=round_id,
        snapshot_checksum=snapshot_checksum,
        deadline=deadline,
        results=tuple(collected[duty.replica_id] for duty in ordered),
    )


def preflight_round(
    *,
    registrations: Sequence[RuntimeRegistration],
    duties: Sequence[ReplicaDuty],
    requests: Sequence[RunnerRequest],
    runners: Mapping[str, Runner],
    common_data_status: str,
    archive: AuditArchive,
    decided_at: datetime,
) -> PreflightBarrierResult:
    """Preflight every due replica and decide whether the field may proceed."""

    if not isinstance(archive, AuditArchive):
        raise OrchestratorError("archive", "expected AuditArchive")
    if decided_at.tzinfo is None:
        raise OrchestratorError("decided_at", "must be timezone-aware")
    if common_data_status not in COMMON_DATA_STATUSES:
        raise OrchestratorError(
            "common_data_status",
            f"must be one of {', '.join(COMMON_DATA_STATUSES)}",
        )

    registry = _registration_index(registrations)
    due, skipped = _partition_duties(duties, registry)
    request_by_replica = _request_index(requests, due)
    runner_by_product = _runner_index(runners, due)
    round_id = _shared_round_id(due, request_by_replica)

    preflight_results: list[PreflightResult] = []
    reason_codes: list[str] = []
    if common_data_status == COMMON_DATA_UNAVAILABLE:
        reason_codes.append(COMMON_DATA_UNAVAILABLE_REASON)

    for duty in due:
        request = request_by_replica[duty.replica_id]
        result = require_matching_identity(
            request,
            runner_by_product[duty.product_id].preflight(request),
        )
        preflight_results.append(result)
        if not result.ready:
            if result.failure_reason is None:
                raise OrchestratorError(
                    "preflight.failure_reason",
                    "required when a due replica is not ready",
                )
            reason_codes.append(result.failure_reason)

    ready = not reason_codes
    if not ready:
        _append_pause(
            archive,
            round_id=round_id,
            timestamp=decided_at,
            reason=_pause_reason(reason_codes),
        )
    return PreflightBarrierResult(
        contract_version=RUNNER_CONTRACT_VERSION,
        round_id=round_id,
        ready=ready,
        reason_codes=tuple(reason_codes),
        due_replica_ids=tuple(duty.replica_id for duty in due),
        skipped_replica_ids=tuple(duty.replica_id for duty in skipped),
        preflight_results=tuple(preflight_results),
    )


def _registration_index(
    registrations: Sequence[RuntimeRegistration],
) -> dict[tuple[str, str], RuntimeRegistration]:
    if not registrations:
        raise OrchestratorError("registrations", "must contain at least one product")
    index: dict[tuple[str, str], RuntimeRegistration] = {}
    seen_products: set[str] = set()
    for offset, registration in enumerate(registrations):
        path = f"registrations.{offset}"
        if not isinstance(registration, RuntimeRegistration):
            raise OrchestratorError(path, "expected RuntimeRegistration")
        if registration.product_id in seen_products:
            raise OrchestratorError(
                f"{path}.product_id",
                "duplicate product registration",
            )
        seen_products.add(registration.product_id)
        for replica_id in registration.replica_ids:
            key = (registration.product_id, replica_id)
            if key in index:
                raise OrchestratorError(
                    f"{path}.replica_ids",
                    "duplicate replica registration",
                )
            index[key] = registration
    return index


def _partition_duties(
    duties: Sequence[ReplicaDuty],
    registry: Mapping[tuple[str, str], RuntimeRegistration],
) -> tuple[tuple[ReplicaDuty, ...], tuple[ReplicaDuty, ...]]:
    if not duties:
        raise OrchestratorError("duties", "must contain at least one replica")
    seen: set[tuple[str, str]] = set()
    due: list[ReplicaDuty] = []
    skipped: list[ReplicaDuty] = []
    for offset, duty in enumerate(duties):
        path = f"duties.{offset}"
        if not isinstance(duty, ReplicaDuty):
            raise OrchestratorError(path, "expected ReplicaDuty")
        key = (duty.product_id, duty.replica_id)
        if key in seen:
            raise OrchestratorError(path, "duplicate replica duty")
        seen.add(key)
        if key not in registry:
            raise OrchestratorError(
                path,
                "replica is not in the frozen registrations",
            )
        if duty.status == REPLICA_STATUS_ACTIVE:
            due.append(duty)
        else:
            skipped.append(duty)
    return tuple(due), tuple(skipped)


def _request_index(
    requests: Sequence[RunnerRequest],
    due: Sequence[ReplicaDuty],
) -> dict[str, RunnerRequest]:
    expected = {(duty.product_id, duty.replica_id) for duty in due}
    index: dict[str, RunnerRequest] = {}
    for offset, request in enumerate(requests):
        path = f"requests.{offset}"
        if not isinstance(request, RunnerRequest):
            raise OrchestratorError(path, "expected RunnerRequest")
        key = (request.product_id, request.replica_id)
        if key not in expected:
            raise OrchestratorError(path, "request is not for a due replica")
        if request.replica_id in index:
            raise OrchestratorError(path, "duplicate due replica request")
        index[request.replica_id] = request
    missing = [
        duty.replica_id for duty in due if duty.replica_id not in index
    ]
    if missing:
        raise OrchestratorError(
            "requests",
            f"missing request for due replica {missing[0]}",
        )
    return index


def _runner_index(
    runners: Mapping[str, Runner],
    due: Sequence[ReplicaDuty],
) -> dict[str, Runner]:
    if not isinstance(runners, Mapping):
        raise OrchestratorError("runners", "expected a product-id mapping")
    index: dict[str, Runner] = {}
    for product_id, runner in runners.items():
        _require_text(product_id, path="runners")
        if not callable(getattr(runner, "preflight", None)):
            raise OrchestratorError(
                f"runners.{product_id}",
                "expected a Runner with preflight",
            )
        index[product_id] = runner
    for duty in due:
        if duty.product_id not in index:
            raise OrchestratorError(
                "runners",
                f"missing runner for product {duty.product_id}",
            )
    return index


def _shared_round_id(
    due: Sequence[ReplicaDuty],
    requests: Mapping[str, RunnerRequest],
) -> str:
    if not due:
        raise OrchestratorError(
            "duties",
            "at least one replica must be due",
        )
    round_id = requests[due[0].replica_id].round_id
    for duty in due:
        if requests[duty.replica_id].round_id != round_id:
            raise OrchestratorError(
                "requests.round_id",
                "every due replica must share the same round",
            )
        if requests[duty.replica_id].product_id != duty.product_id:
            raise OrchestratorError(
                "requests.product_id",
                "does not match replica duty",
            )
    return round_id


def _pause_reason(reason_codes: Sequence[str]) -> str:
    prioritized = [code for code in _PAUSE_REASON_PRIORITY if code in reason_codes]
    return prioritized[0] if prioritized else reason_codes[0]


def _append_pause(
    archive: AuditArchive,
    *,
    round_id: str,
    timestamp: datetime,
    reason: str,
) -> None:
    event = parse_audit_event(
        {
            "schema_version": AUDIT_SCHEMA_VERSION,
            "type": "pause",
            "product_id": None,
            "replica_id": None,
            "round_id": round_id,
            "timestamp": format_et_timestamp(timestamp),
            "payload": {"reason": reason},
            "provider_artifacts": [],
        }
    )
    archive.append_event(event)


def _require_text(value: object, *, path: str) -> None:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise OrchestratorError(path, "must be a non-empty string without padding")


def _require_checksum(value: object) -> None:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise OrchestratorError(
            "snapshot_checksum",
            "must be a lowercase SHA-256 hex digest",
        )


def _shared_deadline(
    due: Sequence[ReplicaDuty],
    requests: Mapping[str, RunnerRequest],
) -> datetime:
    deadline = requests[due[0].replica_id].deadline
    for duty in due:
        if requests[duty.replica_id].deadline != deadline:
            raise OrchestratorError(
                "requests.deadline",
                "every due replica must share the same absolute deadline",
            )
    return deadline


def _require_shared_snapshot(
    due: Sequence[ReplicaDuty],
    requests: Mapping[str, RunnerRequest],
    snapshot_checksum: str,
) -> None:
    for duty in due:
        observed = published_snapshot_checksum(requests[duty.replica_id].workspace)
        if observed != snapshot_checksum:
            raise OrchestratorError(
                "snapshot_checksum",
                "published snapshot does not match the shared checksum",
            )


def _align_collection_inputs(
    barrier: object,
    disposition: object,
    workspaces: object,
) -> tuple[tuple[RunnerResult, ReplicaDisposition, Path], ...]:
    if not isinstance(barrier, DecisionBarrierResult):
        raise OrchestratorError("barrier", "expected DecisionBarrierResult")
    if not isinstance(disposition, RoundDisposition):
        raise OrchestratorError("disposition", "expected RoundDisposition")
    if not isinstance(workspaces, Mapping):
        raise OrchestratorError("workspaces", "expected a replica-id mapping")
    if not barrier.results:
        raise OrchestratorError("barrier.results", "must contain every sealed result")
    if len(disposition.replica_dispositions) != len(barrier.results):
        raise OrchestratorError(
            "disposition",
            "must contain one record for every sealed result",
        )
    pairs: list[tuple[RunnerResult, ReplicaDisposition, Path]] = []
    for index, (result, replica) in enumerate(
        zip(barrier.results, disposition.replica_dispositions, strict=True)
    ):
        if (
            result.product_id,
            result.replica_id,
            result.round_id,
            result.outcome,
        ) != (
            replica.product_id,
            replica.replica_id,
            replica.round_id,
            replica.outcome,
        ):
            raise OrchestratorError(
                f"disposition.replica_dispositions.{index}",
                "must match the sealed barrier result",
            )
        if result.round_id != barrier.round_id:
            raise OrchestratorError(
                f"barrier.results.{index}.round_id",
                "must match the barrier round",
            )
        workspace = workspaces.get(result.replica_id)
        if workspace is None:
            raise OrchestratorError(
                "workspaces",
                f"missing workspace for replica {result.replica_id}",
            )
        pairs.append(
            (
                result,
                replica,
                _require_collection_workspace(workspace, result.replica_id),
            )
        )
    return tuple(pairs)


def _require_collection_workspace(value: object, replica_id: str) -> Path:
    path_name = f"workspaces.{replica_id}"
    if replica_id in {".", ".."} or "/" in replica_id or "\\" in replica_id:
        raise OrchestratorError(
            path_name,
            "replica id must be one direct directory name",
        )
    if not isinstance(value, (Path, str)):
        raise OrchestratorError(path_name, "expected a path")
    candidate = Path(value)
    if not candidate.is_absolute():
        raise OrchestratorError(path_name, "must be absolute")
    resolved = candidate.resolve(strict=False)
    if resolved != candidate or ".." in candidate.parts:
        raise OrchestratorError(path_name, "must be resolved")
    if _is_link_or_junction(candidate):
        raise OrchestratorError(path_name, "symlink or junction is prohibited")
    if not resolved.is_dir():
        raise OrchestratorError(path_name, "must be an existing directory")
    return resolved


def _require_staging_root(
    value: object,
    *,
    workspaces: Sequence[Path],
) -> Path:
    if not isinstance(value, (Path, str)):
        raise OrchestratorError("staging_root", "expected a path")
    candidate = Path(value)
    if not candidate.is_absolute():
        raise OrchestratorError("staging_root", "must be absolute")
    resolved = candidate.resolve(strict=False)
    if resolved != candidate or ".." in candidate.parts:
        raise OrchestratorError("staging_root", "must be resolved")
    if _is_link_or_junction(candidate):
        raise OrchestratorError("staging_root", "symlink or junction is prohibited")
    for workspace in workspaces:
        if resolved == workspace or resolved.is_relative_to(workspace):
            raise OrchestratorError(
                "staging_root",
                "must stay outside every replica workspace",
            )
    try:
        resolved.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise OrchestratorError(
            "staging_root",
            f"cannot create staging directory: {exc}",
        ) from exc
    if not resolved.is_dir() or _is_link_or_junction(resolved):
        raise OrchestratorError("staging_root", "must be an existing directory")
    return resolved


def _collect_one_decision(
    result: RunnerResult,
    replica: ReplicaDisposition,
    workspace: Path,
    *,
    staging_root: Path,
    expose_completed: bool,
) -> SealedDecisionRecord:
    should_stage = replica.treatment == REPLICA_TREATMENT_EVALUATE or (
        replica.treatment == REPLICA_TREATMENT_VOIDED and result.decision_present
    )
    if not should_stage:
        return SealedDecisionRecord(
            product_id=result.product_id,
            replica_id=result.replica_id,
            round_id=result.round_id,
            outcome=result.outcome,
            treatment=replica.treatment,
            decision_present=False,
            byte_length=None,
            checksum=None,
            staged_path=None,
            exposed_to_kernel=False,
        )
    payload, checksum = _read_sealed_decision(workspace, result)
    staged_path = _write_staged_decision(
        staging_root,
        round_id=result.round_id,
        replica_id=result.replica_id,
        payload=payload,
    )
    return SealedDecisionRecord(
        product_id=result.product_id,
        replica_id=result.replica_id,
        round_id=result.round_id,
        outcome=result.outcome,
        treatment=replica.treatment,
        decision_present=True,
        byte_length=len(payload),
        checksum=checksum,
        staged_path=staged_path,
        exposed_to_kernel=(
            expose_completed and replica.treatment == REPLICA_TREATMENT_EVALUATE
        ),
    )


def _read_sealed_decision(
    workspace: Path,
    result: RunnerResult,
) -> tuple[bytes, str]:
    field = f"workspaces.{result.replica_id}.outbox.decision"
    source = workspace / OUTBOX_DECISION_FILE
    _reject_link_chain(workspace, source, path=field)
    if not source.is_file():
        raise OrchestratorError(field, "sealed decision file is missing")
    if _is_link_or_junction(source):
        raise OrchestratorError(field, "symlink or junction is prohibited")
    try:
        payload = source.read_bytes()
    except OSError as exc:
        raise OrchestratorError(field, f"cannot read sealed decision: {exc}") from exc
    checksum = hashlib.sha256(payload).hexdigest()
    if result.decision_checksum != checksum:
        raise OrchestratorError(
            field,
            "staged checksum does not match the sealed runner result",
        )
    return payload, checksum


def _write_staged_decision(
    staging_root: Path,
    *,
    round_id: str,
    replica_id: str,
    payload: bytes,
) -> Path:
    destination = staging_root / round_id / replica_id / "decision.json"
    resolved = destination.resolve(strict=False)
    if not resolved.is_relative_to(staging_root):
        raise OrchestratorError(
            f"workspaces.{replica_id}.outbox.decision",
            "staged path escapes the staging root",
        )
    if resolved.exists():
        raise OrchestratorError(
            f"workspaces.{replica_id}.outbox.decision",
            "staged decision already exists",
        )
    try:
        resolved.parent.mkdir(parents=True, exist_ok=True)
        if _is_link_or_junction(resolved.parent) or _is_link_or_junction(
            resolved.parent.parent
        ):
            raise OrchestratorError(
                f"workspaces.{replica_id}.outbox.decision",
                "symlink or junction is prohibited",
            )
        resolved.write_bytes(payload)
        os.chmod(resolved, 0o444)
    except OrchestratorError:
        raise
    except OSError as exc:
        raise OrchestratorError(
            f"workspaces.{replica_id}.outbox.decision",
            f"cannot stage sealed decision: {exc}",
        ) from exc
    return resolved


def _reject_link_chain(root: Path, candidate: Path, *, path: str) -> None:
    current = root
    try:
        relative = candidate.relative_to(root)
    except ValueError as exc:
        raise OrchestratorError(path, "must stay within the replica workspace") from exc
    for part in relative.parts:
        current = current / part
        if current.exists() and _is_link_or_junction(current):
            raise OrchestratorError(path, "symlink or junction is prohibited")


def _is_link_or_junction(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    return bool(is_junction()) if callable(is_junction) else False
