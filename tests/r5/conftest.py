"""Shared R5 archive events and synthetic provider output."""

from __future__ import annotations

from typing import Any

from arena_runtime.audit import AuditEvent, parse_audit_event

SYNTHETIC_API_KEY = b"sk-test-abcdefghijklmnop"
SYNTHETIC_OAUTH_TOKEN = b"oauth-secret-123456789"
SYNTHETIC_BEARER_TOKEN = b"bearer.secret.value"

PROVIDER_OUTPUT = b"".join(
    (
        b'{"access_token":"' + SYNTHETIC_OAUTH_TOKEN + b'","status":"ok"}\n',
        b"PROVIDER_API_KEY=" + SYNTHETIC_API_KEY + b"\n",
        b"Authorization: Bearer " + SYNTHETIC_BEARER_TOKEN + b"\n",
        b"ordinary output remains\n",
    )
)


def audit_event(event_type: str = "commit_started") -> AuditEvent:
    round_scoped = event_type in {
        "round_disposition_selected",
        "commit_started",
        "commit_completed",
        "pause",
        "operator_intervention",
    }
    payloads: dict[str, dict[str, Any]] = {
        "preflight_completed": {"ready": True, "failure_reason": None},
        "replica_completed": {
            "outcome": "completed",
            "exit_status": 0,
            "session_reference": "opaque-session-a1",
        },
        "commit_started": {},
        "commit_completed": {},
    }
    return parse_audit_event(
        {
            "schema_version": "1",
            "type": event_type,
            "product_id": None if round_scoped else "product-a",
            "replica_id": None if round_scoped else "product-a-1",
            "round_id": "2026-08-17-morning",
            "timestamp": "2026-08-17T10:05:00-04:00",
            "payload": payloads[event_type],
            "provider_artifacts": [],
        }
    )
