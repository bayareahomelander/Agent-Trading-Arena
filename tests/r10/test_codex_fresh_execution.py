"""R10: fresh Codex argv, cwd, prompt, output, and decision are exact."""

import base64
import hashlib
import json
from pathlib import Path

from arena_runtime.audit import parse_audit_event

from .conftest import (
    EXACT_DECISION,
    EXPECTED_MODEL,
    EXPECTED_REASONING,
    FROZEN_PROMPT,
    make_case,
)


def test_fresh_exec_uses_frozen_argv_cwd_and_prompt_bytes(tmp_path: Path) -> None:
    adapter, request, _, capture_path, _ = make_case(tmp_path)
    assert adapter.preflight(request).ready

    result = adapter.run(request)
    capture = json.loads(capture_path.read_text(encoding="utf-8"))

    assert capture["cwd"] == str(request.workspace)
    assert base64.b64decode(capture["prompt_base64"]) == FROZEN_PROMPT
    assert capture["argv"] == [
        "--model",
        EXPECTED_MODEL,
        "--config",
        f'model_reasoning_effort="{EXPECTED_REASONING}"',
        "--config",
        'model_provider="openai"',
        "--sandbox",
        "workspace-write",
        "--ask-for-approval",
        "never",
        "--search",
        "--strict-config",
        "--cd",
        str(request.workspace),
        "exec",
        "--json",
        "--ignore-user-config",
        "--ignore-rules",
        "--skip-git-repo-check",
        FROZEN_PROMPT.decode("utf-8"),
    ]
    assert "resume" not in capture["argv"]
    assert "--ephemeral" not in capture["argv"]
    assert result.outcome == "completed"
    assert result.session_reference is None


def test_exact_outbox_bytes_are_hashed_but_never_parsed_or_rewritten(
    tmp_path: Path,
) -> None:
    adapter, request, _, _, _ = make_case(tmp_path)
    assert adapter.preflight(request).ready

    result = adapter.run(request)

    assert (request.workspace / "outbox" / "decision.json").read_bytes() == (
        EXACT_DECISION
    )
    assert result.decision_checksum == hashlib.sha256(EXACT_DECISION).hexdigest()
    assert result.decision_present is True


def test_provider_jsonl_and_stderr_are_sanitized_archive_artifacts(
    tmp_path: Path,
) -> None:
    adapter, request, archive, _, _ = make_case(tmp_path)
    assert adapter.preflight(request).ready
    result = adapter.run(request)

    stdout_path = next(path for path in result.artifact_references if path.endswith(".jsonl"))
    stderr_path = next(path for path in result.artifact_references if path.endswith(".log"))
    stdout = (archive.root / stdout_path).read_text(encoding="utf-8")
    stderr = (archive.root / stderr_path).read_text(encoding="utf-8")

    assert '"type": "thread.started"' in stdout
    assert "fresh-thread-id" in stdout
    assert stderr == "synthetic progress\r\n" or stderr == "synthetic progress\n"


def test_success_emits_required_normalized_audit_sequence(tmp_path: Path) -> None:
    adapter, request, archive, _, _ = make_case(tmp_path)
    adapter.preflight(request)
    adapter.run(request)

    event_types = [
        parse_audit_event(line).event_type
        for line in archive.events_path.read_text(encoding="utf-8").splitlines()
    ]
    assert event_types == [
        "preflight_started",
        "preflight_completed",
        "replica_launched",
        "decision_collected",
        "replica_completed",
    ]
