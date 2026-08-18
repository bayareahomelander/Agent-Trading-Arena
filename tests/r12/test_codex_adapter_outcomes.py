"""R12: mapped adapter results retain sanitized source artifacts."""

import json
from pathlib import Path

from arena_runtime.audit import parse_audit_event
from tests.r10.conftest import make_case


def test_quota_result_retains_explicit_code_and_source_artifact(tmp_path: Path) -> None:
    adapter, request, archive, _, _ = make_case(
        tmp_path,
        decision_bytes=None,
        run_exit=7,
    )
    scenario_path = tmp_path / "scenario.json"
    scenario = json.loads(scenario_path.read_text(encoding="utf-8"))
    scenario["stdout_events"] = [
        {"type": "thread.started", "thread_id": "thread-quota"},
        {
            "type": "turn.failed",
            "error": {"error_type": "usageLimitExceeded"},
        },
    ]
    scenario_path.write_text(json.dumps(scenario), encoding="utf-8")
    assert adapter.preflight(request).ready

    result = adapter.run(request)

    assert result.outcome == "quota_exhausted"
    assert result.artifact_references
    assert adapter.last_classification is not None
    assert adapter.last_classification.error_codes == ("usage_limit_exceeded",)
    stdout_path = next(
        path for path in result.artifact_references if path.endswith(".jsonl")
    )
    assert "usageLimitExceeded" in (archive.root / stdout_path).read_text(
        encoding="utf-8"
    )


def test_mapped_outcome_is_written_once_to_normalized_completion(
    tmp_path: Path,
) -> None:
    adapter, request, archive, _, _ = make_case(
        tmp_path,
        decision_bytes=None,
        run_exit=7,
    )
    scenario_path = tmp_path / "scenario.json"
    scenario = json.loads(scenario_path.read_text(encoding="utf-8"))
    scenario["stdout_events"] = [
        {"type": "thread.started", "thread_id": "thread-provider"},
        {
            "type": "error",
            "error": {"error_type": "serverOverloaded"},
        },
    ]
    scenario_path.write_text(json.dumps(scenario), encoding="utf-8")
    adapter.preflight(request)
    result = adapter.run(request)

    completed = [
        event
        for event in (
            parse_audit_event(line)
            for line in archive.events_path.read_text(encoding="utf-8").splitlines()
        )
        if event.event_type == "replica_completed"
    ]
    assert result.outcome == "provider_unavailable"
    assert len(completed) == 1
    assert completed[0].payload.outcome == "provider_unavailable"
