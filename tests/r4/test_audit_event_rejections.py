"""R4: malformed, ambiguous, or secret-shaped audit records fail by path."""

from dataclasses import replace
from datetime import datetime

from typing import Any, Callable

import pytest

from arena_kernel.schema.errors import SchemaError
from arena_runtime.audit import dump_audit_event, parse_audit_event

from .conftest import ARTIFACT_CHECKSUM, audit_record


Mutation = Callable[[dict[str, Any]], None]


def _unknown_type(record: dict[str, Any]) -> None:
    record["type"] = "provider_output"


def _unknown_top_level_field(record: dict[str, Any]) -> None:
    record["stdout"] = "raw provider output"


def _unknown_payload_field(record: dict[str, Any]) -> None:
    record["payload"]["transcript"] = "raw provider output"


def _naive_timestamp(record: dict[str, Any]) -> None:
    record["timestamp"] = "2026-08-17T10:05:00"


def _missing_product_identity(record: dict[str, Any]) -> None:
    del record["product_id"]


def _missing_replica_identity(record: dict[str, Any]) -> None:
    record["replica_id"] = None


def _missing_round_identity(record: dict[str, Any]) -> None:
    del record["round_id"]


@pytest.mark.parametrize(
    ("mutate", "path"),
    [
        (_unknown_type, "type"),
        (_unknown_top_level_field, "stdout"),
        (_unknown_payload_field, "payload.transcript"),
        (_naive_timestamp, "timestamp"),
        (_missing_product_identity, "product_id"),
        (_missing_replica_identity, "replica_id"),
        (_missing_round_identity, "round_id"),
    ],
)
def test_invalid_replica_event_fails_at_named_path(
    mutate: Mutation,
    path: str,
) -> None:
    record = audit_record("replica_completed")
    mutate(record)

    with pytest.raises(SchemaError) as exc:
        parse_audit_event(record)

    assert exc.value.path == path


@pytest.mark.parametrize("field", ["api_key", "access_token", "oauth-token"])
def test_secret_valued_payload_field_names_are_rejected(field: str) -> None:
    record = audit_record("replica_completed")
    record["payload"][field] = "synthetic-secret"

    with pytest.raises(SchemaError) as exc:
        parse_audit_event(record)

    assert exc.value.path == f"payload.{field}"
    assert "secret-valued" in exc.value.message


def test_round_event_rejects_replica_identity() -> None:
    record = audit_record("commit_started")
    record["product_id"] = "product-a"
    record["replica_id"] = "product-a-1"

    with pytest.raises(SchemaError) as exc:
        parse_audit_event(record)

    assert exc.value.path == "product_id"


def test_nested_naive_deadline_is_rejected() -> None:
    record = audit_record("replica_launched")
    record["payload"]["deadline"] = "2026-08-17T10:15:00"

    with pytest.raises(SchemaError) as exc:
        parse_audit_event(record)

    assert exc.value.path == "payload.deadline"


@pytest.mark.parametrize(
    ("path_value", "path"),
    [
        ("../auth-cache", "provider_artifacts.0.path"),
        ("C:\\auth-cache", "provider_artifacts.0.path"),
        ("/absolute/provider.json", "provider_artifacts.0.path"),
    ],
)
def test_provider_artifact_path_must_be_safe_and_relative(
    path_value: str,
    path: str,
) -> None:
    record = audit_record("replica_completed")
    record["provider_artifacts"][0]["path"] = path_value

    with pytest.raises(SchemaError) as exc:
        parse_audit_event(record)

    assert exc.value.path == path


def test_provider_artifact_checksum_must_be_sha256() -> None:
    record = audit_record("replica_completed")
    record["provider_artifacts"][0]["checksum"] = "not-a-checksum"

    with pytest.raises(SchemaError) as exc:
        parse_audit_event(record)

    assert exc.value.path == "provider_artifacts.0.checksum"


def test_provider_artifact_rejects_embedded_output() -> None:
    record = audit_record("replica_completed")
    record["provider_artifacts"][0]["content"] = "raw output"

    with pytest.raises(SchemaError) as exc:
        parse_audit_event(record)

    assert exc.value.path == "provider_artifacts.0.content"


def test_duplicate_provider_artifact_path_is_rejected() -> None:
    record = audit_record("replica_completed")
    record["provider_artifacts"].append(
        {
            "path": "provider/replica_completed.json",
            "checksum": ARTIFACT_CHECKSUM,
        }
    )

    with pytest.raises(SchemaError) as exc:
        parse_audit_event(record)

    assert exc.value.path == "provider_artifacts.1.path"


def test_dump_rejects_direct_event_with_naive_timestamp_by_path() -> None:
    event = parse_audit_event(audit_record("commit_started"))
    invalid = replace(event, timestamp=datetime(2026, 8, 17, 10, 5))

    with pytest.raises(SchemaError) as exc:
        dump_audit_event(invalid)

    assert exc.value.path == "timestamp"
