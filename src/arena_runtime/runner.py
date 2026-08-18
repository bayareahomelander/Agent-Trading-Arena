"""Provider-neutral runner contracts.

R2 defines immutable request, preflight, and result records plus the shared
runner protocol. It performs contract validation only: no serialization,
filesystem access, process launch, provider logic, or trading interpretation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Final, Protocol, runtime_checkable

from arena_kernel.schema.errors import SchemaError
from arena_kernel.schema.round_id import parse_round_id

RUNNER_CONTRACT_VERSION: Final[str] = "1"

RUNNER_OUTCOMES: Final[tuple[str, ...]] = (
    "completed",
    "missing_decision",
    "timeout",
    "refusal",
    "quota_exhausted",
    "provider_unavailable",
    "runner_error",
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class RunnerContractError(ValueError):
    """Invalid runner contract value with a stable field path."""

    def __init__(self, path: str, message: str) -> None:
        self.path = path
        self.message = message
        super().__init__(f"{path}: {message}")


@dataclass(frozen=True)
class RunnerRequest:
    """Provider-neutral description of one replica's due round execution."""

    contract_version: str
    product_id: str
    replica_id: str
    round_id: str
    workspace: Path
    model_reference: str
    configuration_reference: str
    launch_instruction: bytes
    deadline: datetime
    session_reference: str | None = None

    def __post_init__(self) -> None:
        _require_contract_version(self.contract_version)
        _require_text(self.product_id, path="product_id")
        _require_text(self.replica_id, path="replica_id")
        _require_round_id(self.round_id)
        _require_absolute_workspace(self.workspace)
        _require_text(self.model_reference, path="model_reference")
        _require_text(
            self.configuration_reference,
            path="configuration_reference",
        )
        if not isinstance(self.launch_instruction, bytes):
            raise RunnerContractError("launch_instruction", "expected bytes")
        if not self.launch_instruction:
            raise RunnerContractError("launch_instruction", "must not be empty")
        _require_aware_timestamp(self.deadline, path="deadline")
        _require_optional_text(
            self.session_reference,
            path="session_reference",
        )


@dataclass(frozen=True)
class PreflightResult:
    """Readiness result returned before publication or process launch."""

    contract_version: str
    product_id: str
    replica_id: str
    round_id: str
    ready: bool
    started_at: datetime
    finished_at: datetime
    failure_reason: str | None = None
    artifact_references: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_contract_version(self.contract_version)
        _require_identity(self.product_id, self.replica_id, self.round_id)
        if not isinstance(self.ready, bool):
            raise RunnerContractError("ready", "expected a boolean")
        _require_timestamp_range(self.started_at, self.finished_at)
        _require_optional_text(self.failure_reason, path="failure_reason")
        if self.ready and self.failure_reason is not None:
            raise RunnerContractError(
                "failure_reason",
                "must be absent when ready is true",
            )
        if not self.ready and self.failure_reason is None:
            raise RunnerContractError(
                "failure_reason",
                "required when ready is false",
            )
        _require_artifact_references(self.artifact_references)


@dataclass(frozen=True)
class RunnerResult:
    """Normalized adapter lifecycle result, not a trading interpretation."""

    contract_version: str
    product_id: str
    replica_id: str
    round_id: str
    outcome: str
    started_at: datetime
    finished_at: datetime
    exit_status: int | None
    decision_present: bool
    decision_checksum: str | None
    session_reference: str | None = None
    artifact_references: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_contract_version(self.contract_version)
        _require_identity(self.product_id, self.replica_id, self.round_id)
        if self.outcome not in RUNNER_OUTCOMES:
            raise RunnerContractError(
                "outcome",
                f"must be one of {', '.join(RUNNER_OUTCOMES)}",
            )
        _require_timestamp_range(self.started_at, self.finished_at)
        if self.exit_status is not None and (
            isinstance(self.exit_status, bool)
            or not isinstance(self.exit_status, int)
        ):
            raise RunnerContractError("exit_status", "expected an integer or null")
        if not isinstance(self.decision_present, bool):
            raise RunnerContractError("decision_present", "expected a boolean")
        _require_decision_checksum(
            present=self.decision_present,
            checksum=self.decision_checksum,
        )
        if self.outcome == "completed" and not self.decision_present:
            raise RunnerContractError(
                "decision_present",
                "completed outcome requires a collected decision",
            )
        if self.outcome == "missing_decision" and self.decision_present:
            raise RunnerContractError(
                "decision_present",
                "missing_decision outcome cannot have a collected decision",
            )
        _require_optional_text(
            self.session_reference,
            path="session_reference",
        )
        _require_artifact_references(self.artifact_references)


RunnerResponse = PreflightResult | RunnerResult


def require_matching_identity(
    request: RunnerRequest,
    response: RunnerResponse,
) -> RunnerResponse:
    """Return a response only when it belongs to the supplied request."""

    for path in ("contract_version", "product_id", "replica_id", "round_id"):
        if getattr(response, path) != getattr(request, path):
            raise RunnerContractError(path, "does not match runner request")
    return response


@runtime_checkable
class Runner(Protocol):
    """Shared provider-neutral boundary implemented by every adapter."""

    def preflight(self, request: RunnerRequest) -> PreflightResult: ...

    def run(self, request: RunnerRequest) -> RunnerResult: ...


def _require_contract_version(value: str) -> None:
    if value != RUNNER_CONTRACT_VERSION:
        raise RunnerContractError(
            "contract_version",
            f"must be {RUNNER_CONTRACT_VERSION!r}",
        )


def _require_identity(product_id: str, replica_id: str, round_id: str) -> None:
    _require_text(product_id, path="product_id")
    _require_text(replica_id, path="replica_id")
    _require_round_id(round_id)


def _require_text(value: str, *, path: str) -> None:
    if not isinstance(value, str):
        raise RunnerContractError(path, "expected a string")
    if not value or value.strip() != value:
        raise RunnerContractError(path, "must be a non-empty string without padding")


def _require_optional_text(value: str | None, *, path: str) -> None:
    if value is not None:
        _require_text(value, path=path)


def _require_round_id(value: str) -> None:
    try:
        parse_round_id(value, path="round_id")
    except SchemaError as exc:
        raise RunnerContractError(exc.path, exc.message) from exc


def _require_absolute_workspace(value: Path) -> None:
    if not isinstance(value, Path):
        raise RunnerContractError("workspace", "expected a Path")
    if not value.is_absolute():
        raise RunnerContractError("workspace", "must be absolute")
    if ".." in value.parts:
        raise RunnerContractError("workspace", "must be resolved")


def _require_aware_timestamp(value: datetime, *, path: str) -> None:
    if not isinstance(value, datetime):
        raise RunnerContractError(path, "expected a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise RunnerContractError(path, "must be timezone-aware")


def _require_timestamp_range(started_at: datetime, finished_at: datetime) -> None:
    _require_aware_timestamp(started_at, path="started_at")
    _require_aware_timestamp(finished_at, path="finished_at")
    if finished_at < started_at:
        raise RunnerContractError("finished_at", "must not precede started_at")


def _require_decision_checksum(*, present: bool, checksum: str | None) -> None:
    if present:
        if not isinstance(checksum, str) or _SHA256.fullmatch(checksum) is None:
            raise RunnerContractError(
                "decision_checksum",
                "must be a lowercase SHA-256 hex digest when decision is present",
            )
    elif checksum is not None:
        raise RunnerContractError(
            "decision_checksum",
            "must be absent when decision is not present",
        )


def _require_artifact_references(value: tuple[str, ...]) -> None:
    if not isinstance(value, tuple):
        raise RunnerContractError("artifact_references", "expected a tuple")
    seen: set[str] = set()
    for index, item in enumerate(value):
        path = f"artifact_references.{index}"
        _require_text(item, path=path)
        if item in seen:
            raise RunnerContractError(path, "duplicate artifact reference")
        seen.add(item)
