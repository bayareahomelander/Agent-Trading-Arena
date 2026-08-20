"""Shared R4 normalized audit records."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from arena_runtime.audit import AUDIT_EVENT_TYPES

EVENT_TIMESTAMP = "2026-08-17T10:05:00-04:00"
DEADLINE = "2026-08-17T10:15:00-04:00"
ARTIFACT_CHECKSUM = "a" * 64
DECISION_CHECKSUM = "b" * 64

REPLICA_EVENTS = {
    "preflight_started",
    "preflight_completed",
    "replica_launched",
    "replica_completed",
    "replica_terminated",
    "decision_collected",
}

PAYLOADS: dict[str, dict[str, Any]] = {
    "preflight_started": {},
    "preflight_completed": {"ready": True, "failure_reason": None},
    "replica_launched": {
        "deadline": DEADLINE,
        "session_reference": None,
    },
    "replica_completed": {
        "outcome": "completed",
        "exit_status": 0,
        "session_reference": "opaque-session-a1",
    },
    "replica_terminated": {
        "reason": "deadline",
        "exit_status": -15,
    },
    "decision_collected": {
        "decision_present": True,
        "decision_checksum": DECISION_CHECKSUM,
    },
    "commit_started": {},
    "commit_completed": {},
    "pause": {"reason": "common_data_unavailable"},
}

assert set(PAYLOADS) == set(AUDIT_EVENT_TYPES)


def audit_record(event_type: str) -> dict[str, Any]:
    replica_scoped = event_type in REPLICA_EVENTS
    artifacts = []
    if event_type in {"preflight_completed", "replica_completed"}:
        artifacts = [
            {
                "path": f"provider/{event_type}.json",
                "checksum": ARTIFACT_CHECKSUM,
            }
        ]
    return deepcopy(
        {
            "schema_version": "1",
            "type": event_type,
            "product_id": "product-a" if replica_scoped else None,
            "replica_id": "product-a-1" if replica_scoped else None,
            "round_id": "2026-08-17-morning",
            "timestamp": EVENT_TIMESTAMP,
            "payload": PAYLOADS[event_type],
            "provider_artifacts": artifacts,
        }
    )
