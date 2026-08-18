"""Normalized runtime audit-event schema.

R4 defines stable JSON records only. Provider evidence is represented by a
sanitized relative path and SHA-256 checksum; no provider output, secret, file
write, or redaction behavior belongs here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any, Final, Mapping

from arena_kernel.schema._dump import dump_json
from arena_kernel.schema._parse import (
    SCHEMA_VERSION,
    as_mapping,
    join_path,
    require_list,
    require_object,
    require_schema_version,
    require_str,
    require_timestamp,
)
from arena_kernel.schema.errors import SchemaError
from arena_kernel.schema.round_id import parse_round_id
from arena_kernel.types import format_et_timestamp
from arena_runtime.runner import RUNNER_OUTCOMES

AUDIT_SCHEMA_VERSION: Final[str] = SCHEMA_VERSION

AUDIT_EVENT_TYPES: Final[tuple[str, ...]] = (
    "preflight_started",
    "preflight_completed",
    "replica_launched",
    "replica_completed",
    "replica_terminated",
    "decision_collected",
    "round_disposition_selected",
    "commit_started",
    "commit_completed",
    "pause",
    "operator_intervention",
)

_EVENT_FIELDS: Final[tuple[str, ...]] = (
    "schema_version",
    "type",
    "product_id",
    "replica_id",
    "round_id",
    "timestamp",
    "payload",
    "provider_artifacts",
)

_REPLICA_EVENT_TYPES: Final[frozenset[str]] = frozenset(
    {
        "preflight_started",
        "preflight_completed",
        "replica_launched",
        "replica_completed",
        "replica_terminated",
        "decision_collected",
    }
)

_ROUND_EVENT_TYPES: Final[frozenset[str]] = frozenset(AUDIT_EVENT_TYPES) - (
    _REPLICA_EVENT_TYPES
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SECRET_FIELD_NAMES: Final[frozenset[str]] = frozenset(
    {
        "access_token",
        "api_key",
        "authorization",
        "cookie",
        "cookies",
        "credential",
        "credentials",
        "oauth_token",
        "password",
        "refresh_token",
        "secret",
        "token",
    }
)
_SECRET_FIELD_SUFFIXES: Final[tuple[str, ...]] = (
    "_cookie",
    "_credentials",
    "_password",
    "_secret",
    "_token",
)


@dataclass(frozen=True)
class ProviderArtifactReference:
    """Sanitized provider evidence referenced by path and checksum."""

    path: str
    checksum: str


@dataclass(frozen=True)
class PreflightStartedPayload:
    pass


@dataclass(frozen=True)
class PreflightCompletedPayload:
    ready: bool
    failure_reason: str | None


@dataclass(frozen=True)
class ReplicaLaunchedPayload:
    deadline: datetime
    session_reference: str | None


@dataclass(frozen=True)
class ReplicaCompletedPayload:
    outcome: str
    exit_status: int | None
    session_reference: str | None


@dataclass(frozen=True)
class ReplicaTerminatedPayload:
    reason: str
    exit_status: int | None


@dataclass(frozen=True)
class DecisionCollectedPayload:
    decision_present: bool
    decision_checksum: str | None


@dataclass(frozen=True)
class RoundDispositionSelectedPayload:
    disposition: str
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class CommitStartedPayload:
    pass


@dataclass(frozen=True)
class CommitCompletedPayload:
    pass


@dataclass(frozen=True)
class PausePayload:
    reason: str


@dataclass(frozen=True)
class OperatorInterventionPayload:
    action: str
    reason: str


AuditPayload = (
    PreflightStartedPayload
    | PreflightCompletedPayload
    | ReplicaLaunchedPayload
    | ReplicaCompletedPayload
    | ReplicaTerminatedPayload
    | DecisionCollectedPayload
    | RoundDispositionSelectedPayload
    | CommitStartedPayload
    | CommitCompletedPayload
    | PausePayload
    | OperatorInterventionPayload
)


@dataclass(frozen=True)
class AuditEvent:
    """One provider-neutral runtime lifecycle fact."""

    schema_version: str
    event_type: str
    product_id: str | None
    replica_id: str | None
    round_id: str
    timestamp: datetime
    payload: AuditPayload
    provider_artifacts: tuple[ProviderArtifactReference, ...]


def parse_audit_event(data: Mapping[str, Any] | str | bytes) -> AuditEvent:
    """Parse one strict normalized audit record."""

    root = as_mapping(data)
    _reject_secret_field_names(root)
    require_object(root, required=_EVENT_FIELDS)

    event_type = require_str(root, "type")
    if event_type not in AUDIT_EVENT_TYPES:
        raise SchemaError("type", f"unknown event type {event_type!r}")

    product_id = _optional_string(root, "product_id")
    replica_id = _optional_string(root, "replica_id")
    _validate_identity_scope(event_type, product_id, replica_id)

    raw_payload = root["payload"]
    if not isinstance(raw_payload, dict):
        raise SchemaError("payload", "expected an object")

    return AuditEvent(
        schema_version=require_schema_version(root),
        event_type=event_type,
        product_id=product_id,
        replica_id=replica_id,
        round_id=parse_round_id(require_str(root, "round_id")),
        timestamp=require_timestamp(root, "timestamp"),
        payload=_parse_payload(event_type, raw_payload),
        provider_artifacts=_parse_provider_artifacts(root),
    )


def audit_event_to_dict(event: AuditEvent) -> dict[str, Any]:
    """Return the normalized event in stable key order."""

    return {
        "schema_version": event.schema_version,
        "type": event.event_type,
        "product_id": event.product_id,
        "replica_id": event.replica_id,
        "round_id": event.round_id,
        "timestamp": _format_timestamp(event.timestamp, path="timestamp"),
        "payload": _payload_to_dict(event.payload),
        "provider_artifacts": [
            {
                "path": artifact.path,
                "checksum": artifact.checksum,
            }
            for artifact in event.provider_artifacts
        ],
    }


def dump_audit_event(event: AuditEvent) -> str:
    """Dump a byte-stable normalized event with a trailing newline."""

    payload = audit_event_to_dict(event)
    canonical = parse_audit_event(payload)
    return dump_json(audit_event_to_dict(canonical))


def _parse_payload(event_type: str, data: Mapping[str, Any]) -> AuditPayload:
    path = "payload"
    if event_type == "preflight_started":
        require_object(data, required=(), path=path)
        return PreflightStartedPayload()
    if event_type == "preflight_completed":
        require_object(data, required=("ready", "failure_reason"), path=path)
        ready = _require_bool(data, "ready", path=path)
        failure_reason = _optional_string(data, "failure_reason", path=path)
        if ready and failure_reason is not None:
            raise SchemaError(
                "payload.failure_reason",
                "must be null when ready is true",
            )
        if not ready and failure_reason is None:
            raise SchemaError(
                "payload.failure_reason",
                "required when ready is false",
            )
        return PreflightCompletedPayload(ready, failure_reason)
    if event_type == "replica_launched":
        require_object(
            data,
            required=("deadline", "session_reference"),
            path=path,
        )
        return ReplicaLaunchedPayload(
            deadline=require_timestamp(data, "deadline", path=path),
            session_reference=_optional_string(
                data,
                "session_reference",
                path=path,
            ),
        )
    if event_type == "replica_completed":
        require_object(
            data,
            required=("outcome", "exit_status", "session_reference"),
            path=path,
        )
        outcome = require_str(data, "outcome", path=path)
        if outcome not in RUNNER_OUTCOMES:
            raise SchemaError(
                "payload.outcome",
                f"must be one of {', '.join(RUNNER_OUTCOMES)}",
            )
        return ReplicaCompletedPayload(
            outcome=outcome,
            exit_status=_optional_int(data, "exit_status", path=path),
            session_reference=_optional_string(
                data,
                "session_reference",
                path=path,
            ),
        )
    if event_type == "replica_terminated":
        require_object(data, required=("reason", "exit_status"), path=path)
        return ReplicaTerminatedPayload(
            reason=require_str(data, "reason", path=path),
            exit_status=_optional_int(data, "exit_status", path=path),
        )
    if event_type == "decision_collected":
        require_object(
            data,
            required=("decision_present", "decision_checksum"),
            path=path,
        )
        present = _require_bool(data, "decision_present", path=path)
        checksum = _optional_string(data, "decision_checksum", path=path)
        _validate_checksum_presence(present, checksum)
        return DecisionCollectedPayload(present, checksum)
    if event_type == "round_disposition_selected":
        require_object(
            data,
            required=("disposition", "reason_codes"),
            path=path,
        )
        return RoundDispositionSelectedPayload(
            disposition=require_str(data, "disposition", path=path),
            reason_codes=_require_unique_strings(
                data,
                "reason_codes",
                path=path,
            ),
        )
    if event_type == "commit_started":
        require_object(data, required=(), path=path)
        return CommitStartedPayload()
    if event_type == "commit_completed":
        require_object(data, required=(), path=path)
        return CommitCompletedPayload()
    if event_type == "pause":
        require_object(data, required=("reason",), path=path)
        return PausePayload(reason=require_str(data, "reason", path=path))
    require_object(data, required=("action", "reason"), path=path)
    return OperatorInterventionPayload(
        action=require_str(data, "action", path=path),
        reason=require_str(data, "reason", path=path),
    )


def _payload_to_dict(payload: AuditPayload) -> dict[str, Any]:
    if isinstance(payload, PreflightStartedPayload):
        return {}
    if isinstance(payload, PreflightCompletedPayload):
        return {
            "ready": payload.ready,
            "failure_reason": payload.failure_reason,
        }
    if isinstance(payload, ReplicaLaunchedPayload):
        return {
            "deadline": _format_timestamp(
                payload.deadline,
                path="payload.deadline",
            ),
            "session_reference": payload.session_reference,
        }
    if isinstance(payload, ReplicaCompletedPayload):
        return {
            "outcome": payload.outcome,
            "exit_status": payload.exit_status,
            "session_reference": payload.session_reference,
        }
    if isinstance(payload, ReplicaTerminatedPayload):
        return {
            "reason": payload.reason,
            "exit_status": payload.exit_status,
        }
    if isinstance(payload, DecisionCollectedPayload):
        return {
            "decision_present": payload.decision_present,
            "decision_checksum": payload.decision_checksum,
        }
    if isinstance(payload, RoundDispositionSelectedPayload):
        return {
            "disposition": payload.disposition,
            "reason_codes": list(payload.reason_codes),
        }
    if isinstance(payload, (CommitStartedPayload, CommitCompletedPayload)):
        return {}
    if isinstance(payload, PausePayload):
        return {"reason": payload.reason}
    if isinstance(payload, OperatorInterventionPayload):
        return {"action": payload.action, "reason": payload.reason}
    raise SchemaError("payload", "unknown audit payload type")


def _parse_provider_artifacts(
    root: Mapping[str, Any],
) -> tuple[ProviderArtifactReference, ...]:
    raw_artifacts = require_list(root, "provider_artifacts")
    artifacts: list[ProviderArtifactReference] = []
    seen_paths: set[str] = set()
    for index, item in enumerate(raw_artifacts):
        item_path = join_path("provider_artifacts", str(index))
        if not isinstance(item, dict):
            raise SchemaError(item_path, "expected an object")
        require_object(
            item,
            required=("path", "checksum"),
            path=item_path,
        )
        artifact_path = require_str(item, "path", path=item_path)
        _validate_artifact_path(
            artifact_path,
            path=join_path(item_path, "path"),
        )
        checksum = require_str(item, "checksum", path=item_path)
        if _SHA256.fullmatch(checksum) is None:
            raise SchemaError(
                join_path(item_path, "checksum"),
                "must be a lowercase SHA-256 hex digest",
            )
        if artifact_path in seen_paths:
            raise SchemaError(join_path(item_path, "path"), "duplicate artifact path")
        seen_paths.add(artifact_path)
        artifacts.append(ProviderArtifactReference(artifact_path, checksum))
    return tuple(artifacts)


def _validate_identity_scope(
    event_type: str,
    product_id: str | None,
    replica_id: str | None,
) -> None:
    if event_type in _REPLICA_EVENT_TYPES:
        if product_id is None:
            raise SchemaError("product_id", "required for replica event")
        if replica_id is None:
            raise SchemaError("replica_id", "required for replica event")
        return
    if event_type in _ROUND_EVENT_TYPES:
        if product_id is not None:
            raise SchemaError("product_id", "must be null for round event")
        if replica_id is not None:
            raise SchemaError("replica_id", "must be null for round event")


def _optional_string(
    data: Mapping[str, Any],
    key: str,
    *,
    path: str = "$",
) -> str | None:
    if data[key] is None:
        return None
    return require_str(data, key, path=path)


def _optional_int(
    data: Mapping[str, Any],
    key: str,
    *,
    path: str,
) -> int | None:
    value = data[key]
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise SchemaError(join_path(path, key), "expected an integer or null")
    return value


def _require_bool(
    data: Mapping[str, Any],
    key: str,
    *,
    path: str,
) -> bool:
    value = data[key]
    if not isinstance(value, bool):
        raise SchemaError(join_path(path, key), "expected a boolean")
    return value


def _require_unique_strings(
    data: Mapping[str, Any],
    key: str,
    *,
    path: str,
) -> tuple[str, ...]:
    raw_values = require_list(data, key, path=path)
    values: list[str] = []
    seen: set[str] = set()
    parent = join_path(path, key)
    for index, item in enumerate(raw_values):
        item_path = join_path(parent, str(index))
        if not isinstance(item, str) or not item or item.strip() != item:
            raise SchemaError(
                item_path,
                "must be a non-empty string without padding",
            )
        if item in seen:
            raise SchemaError(item_path, "duplicate reason code")
        seen.add(item)
        values.append(item)
    return tuple(values)


def _validate_checksum_presence(present: bool, checksum: str | None) -> None:
    if present:
        if checksum is None or _SHA256.fullmatch(checksum) is None:
            raise SchemaError(
                "payload.decision_checksum",
                "must be a lowercase SHA-256 hex digest when decision is present",
            )
    elif checksum is not None:
        raise SchemaError(
            "payload.decision_checksum",
            "must be null when decision is not present",
        )


def _validate_artifact_path(value: str, *, path: str) -> None:
    artifact_path = PurePosixPath(value)
    if artifact_path.is_absolute() or "\\" in value or ".." in artifact_path.parts:
        raise SchemaError(path, "must be a safe relative archive path")
    if artifact_path.as_posix() != value or value in {".", ""}:
        raise SchemaError(path, "must be a normalized relative archive path")


def _format_timestamp(value: datetime, *, path: str) -> str:
    try:
        return format_et_timestamp(value)
    except ValueError as exc:
        raise SchemaError(path, str(exc)) from exc


def _reject_secret_field_names(value: Any, *, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                raise SchemaError(path, "field names must be strings")
            child_path = join_path(path, key)
            normalized = key.casefold().replace("-", "_")
            if normalized in _SECRET_FIELD_NAMES or normalized.endswith(
                _SECRET_FIELD_SUFFIXES
            ):
                raise SchemaError(
                    child_path,
                    "secret-valued field names are prohibited",
                )
            _reject_secret_field_names(child, path=child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_secret_field_names(
                child,
                path=join_path(path, str(index)),
            )
