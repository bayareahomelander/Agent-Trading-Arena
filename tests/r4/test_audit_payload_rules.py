"""R4: normalized event payloads retain lifecycle facts only."""

from typing import Any

import pytest

from arena_kernel.schema.errors import SchemaError
from arena_runtime.audit import parse_audit_event

from .conftest import DECISION_CHECKSUM, audit_record


@pytest.mark.parametrize(
    ("event_type", "payload", "path"),
    [
        (
            "preflight_completed",
            {"ready": False, "failure_reason": None},
            "payload.failure_reason",
        ),
        (
            "replica_completed",
            {
                "outcome": "bad_trade",
                "exit_status": 0,
                "session_reference": None,
            },
            "payload.outcome",
        ),
        (
            "decision_collected",
            {"decision_present": True, "decision_checksum": None},
            "payload.decision_checksum",
        ),
        (
            "decision_collected",
            {
                "decision_present": False,
                "decision_checksum": DECISION_CHECKSUM,
            },
            "payload.decision_checksum",
        ),
    ],
)
def test_inconsistent_payload_fails_at_named_path(
    event_type: str,
    payload: dict[str, Any],
    path: str,
) -> None:
    record = audit_record(event_type)
    record["payload"] = payload

    with pytest.raises(SchemaError) as exc:
        parse_audit_event(record)

    assert exc.value.path == path


def test_missing_decision_is_explicit_without_inventing_a_checksum() -> None:
    record = audit_record("decision_collected")
    record["payload"] = {
        "decision_present": False,
        "decision_checksum": None,
    }

    payload = parse_audit_event(record).payload

    assert payload.decision_present is False
    assert payload.decision_checksum is None
