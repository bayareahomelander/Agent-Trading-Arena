"""R14: unsuccessful raw facts remain unclassified until R16."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from arena_runtime.adapters.grok_build import (
    GrokBuildExecutionError,
    GrokBuildSessionError,
)

from .conftest import make_case


def test_timeout_uses_shared_deadline_without_mapping_provider_meaning(
    tmp_path: Path,
) -> None:
    adapter, request, _, _, _ = make_case(
        tmp_path,
        decision_bytes=None,
        run_sleep_seconds=30,
    )
    assert adapter.preflight(request).ready
    timed_request = replace(
        request,
        deadline=datetime.now(timezone.utc) + timedelta(seconds=0.5),
    )

    with pytest.raises(GrokBuildExecutionError) as exc:
        adapter.run(timed_request)

    assert exc.value.path == "deadline"
    assert exc.value.facts is not None
    assert exc.value.facts.timed_out is True
    assert exc.value.decision_checksum is None


def test_nonzero_exit_retains_raw_facts_and_exact_decision_checksum(
    tmp_path: Path,
) -> None:
    adapter, request, _, _, _ = make_case(tmp_path, run_exit=7)
    assert adapter.preflight(request).ready

    with pytest.raises(GrokBuildExecutionError) as exc:
        adapter.run(request)

    assert exc.value.path == "exit_status"
    assert exc.value.facts is not None
    assert exc.value.facts.exit_status == 7
    assert exc.value.decision_checksum is not None
    assert exc.value.artifact_references


def test_missing_decision_remains_unclassified(tmp_path: Path) -> None:
    adapter, request, _, _, _ = make_case(tmp_path, decision_bytes=None)
    assert adapter.preflight(request).ready

    with pytest.raises(GrokBuildExecutionError) as exc:
        adapter.run(request)

    assert exc.value.path == "decision"
    assert exc.value.facts is not None
    assert exc.value.facts.exit_status == 0
    assert exc.value.decision_checksum is None


def test_fresh_run_rejects_stale_outbox_before_process_launch(tmp_path: Path) -> None:
    adapter, request, _, capture_path, _ = make_case(tmp_path)
    assert adapter.preflight(request).ready
    (request.workspace / "outbox" / "decision.json").write_bytes(b"stale")

    with pytest.raises(GrokBuildExecutionError) as exc:
        adapter.run(request)

    assert exc.value.path == "workspace.outbox.decision"
    assert not capture_path.exists()


def test_resume_reference_is_rejected_before_launch(tmp_path: Path) -> None:
    adapter, request, _, capture_path, _ = make_case(tmp_path)
    assert adapter.preflight(request).ready
    resumed = replace(request, session_reference="existing-session")

    with pytest.raises(GrokBuildSessionError) as exc:
        adapter.run(resumed)

    assert exc.value.path == "session_reference"
    assert not capture_path.exists()


def test_non_utf8_launch_instruction_is_rejected(tmp_path: Path) -> None:
    adapter, request, _, _, _ = make_case(tmp_path)
    assert adapter.preflight(request).ready
    invalid = replace(request, launch_instruction=b"\xff\xfe")

    with pytest.raises(GrokBuildExecutionError) as exc:
        adapter.run(invalid)

    assert exc.value.path == "launch_instruction"


def test_run_requires_matching_ready_preflight(tmp_path: Path) -> None:
    adapter, request, _, _, _ = make_case(tmp_path)

    with pytest.raises(GrokBuildExecutionError) as exc:
        adapter.run(request)

    assert exc.value.path == "preflight"
