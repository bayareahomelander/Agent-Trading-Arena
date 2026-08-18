"""R4: every normalized audit event has stable JSON bytes."""

import pytest

from arena_runtime.audit import (
    AUDIT_EVENT_TYPES,
    audit_event_to_dict,
    dump_audit_event,
    parse_audit_event,
)

from .conftest import ARTIFACT_CHECKSUM, audit_record


def test_audit_event_types_are_complete_and_exact() -> None:
    assert AUDIT_EVENT_TYPES == (
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


@pytest.mark.parametrize("event_type", AUDIT_EVENT_TYPES)
def test_each_audit_event_round_trips_byte_stably(event_type: str) -> None:
    event = parse_audit_event(audit_record(event_type))
    first = dump_audit_event(event)
    second = dump_audit_event(parse_audit_event(first.encode("utf-8")))

    assert second == first
    assert first.endswith("\n")


def test_top_level_key_order_is_frozen() -> None:
    event = parse_audit_event(audit_record("replica_completed"))

    assert tuple(audit_event_to_dict(event)) == (
        "schema_version",
        "type",
        "product_id",
        "replica_id",
        "round_id",
        "timestamp",
        "payload",
        "provider_artifacts",
    )


def test_provider_evidence_is_only_path_and_checksum() -> None:
    event = parse_audit_event(audit_record("replica_completed"))
    artifact = event.provider_artifacts[0]
    dumped = audit_event_to_dict(event)["provider_artifacts"][0]

    assert artifact.path == "provider/replica_completed.json"
    assert artifact.checksum == ARTIFACT_CHECKSUM
    assert dumped == {"path": artifact.path, "checksum": artifact.checksum}


def test_empty_payload_events_remain_distinct() -> None:
    started = parse_audit_event(audit_record("commit_started"))
    completed = parse_audit_event(audit_record("commit_completed"))

    assert started.event_type != completed.event_type
    assert audit_event_to_dict(started)["payload"] == {}
    assert audit_event_to_dict(completed)["payload"] == {}
