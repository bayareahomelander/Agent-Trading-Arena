"""R9: documented Codex diagnostics prove a ready subscription runner."""

import json
from pathlib import Path

from arena_runtime.audit import parse_audit_event

from .conftest import (
    EXPECTED_MODEL,
    EXPECTED_REASONING,
    EXPECTED_VERSION,
    make_case,
)


def test_ready_preflight_proves_frozen_codex_capabilities(tmp_path: Path) -> None:
    adapter, request, archive, _, command_log = make_case(tmp_path)

    result = adapter.preflight(request)

    assert result.ready is True
    assert result.failure_reason is None
    assert result.artifact_references
    capabilities = adapter.last_capabilities
    assert capabilities is not None
    assert capabilities.cli_version == EXPECTED_VERSION
    assert capabilities.authentication_mode == "chatgpt"
    assert capabilities.model == EXPECTED_MODEL
    assert capabilities.model_provider == "openai"
    assert capabilities.reasoning_mode == EXPECTED_REASONING
    assert capabilities.automatic_routing is False
    assert capabilities.headless_exec is True
    assert capabilities.jsonl_output is True
    assert capabilities.structured_output is True
    assert capabilities.session_resume is True

    events = [
        parse_audit_event(line)
        for line in archive.events_path.read_text(encoding="utf-8").splitlines()
    ]
    assert [event.event_type for event in events] == [
        "preflight_started",
        "preflight_completed",
    ]
    assert events[-1].provider_artifacts

    commands = [
        json.loads(line)
        for line in command_log.read_text(encoding="utf-8").splitlines()
    ]
    assert commands == [
        ["--version"],
        ["login", "status"],
        ["exec", "--help"],
        ["doctor", "--json"],
    ]
def test_ready_summary_contains_only_safe_capability_metadata(tmp_path: Path) -> None:
    adapter, request, archive, _, _ = make_case(tmp_path)
    result = adapter.preflight(request)
    summary_path = next(
        path for path in result.artifact_references if path.endswith("summary.json")
    )
    summary = json.loads((archive.root / summary_path).read_text(encoding="utf-8"))

    assert summary["ready"] is True
    assert summary["failure_reason"] is None
    assert summary["capabilities"]["authentication_mode"] == "chatgpt"
    assert "token" not in json.dumps(summary).casefold()
    assert "api_key" not in json.dumps(summary).casefold()
