"""Thin provider-neutral round coordination.

R17 implements the all-product preflight barrier only. It does not publish
round state, launch runners, or select a commit/void treatment.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Final, Mapping, Sequence

from arena_kernel.types import format_et_timestamp
from arena_runtime.audit import AUDIT_SCHEMA_VERSION, AuditArchive, parse_audit_event
from arena_runtime.registration import RuntimeRegistration
from arena_runtime.runner import (
    RUNNER_CONTRACT_VERSION,
    PreflightResult,
    Runner,
    RunnerRequest,
    require_matching_identity,
)

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
    """Invalid preflight-barrier input with a stable field path."""

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
