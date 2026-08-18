"""R15: missing, corrupt, mismatched, or ambiguous sessions never fall back."""

import json
from pathlib import Path

import pytest

from arena_runtime.adapters.grok_build import (
    GrokBuildSessionError,
    GrokBuildSessionStore,
)
from arena_runtime.audit import AuditArchive

from .conftest import (
    LATE_PROMPT,
    MORNING_PROMPT,
    build_adapter,
    make_registration,
    request,
)


def _run_invocations(workspace: Path) -> list[list[str]]:
    path = workspace / "agent" / "notes" / "commands.jsonl"
    if not path.exists():
        return []
    return [
        item
        for item in (json.loads(line) for line in path.read_text().splitlines())
        if "--single" in item
    ]


def _single(tmp_path: Path, **scenario_changes):
    registration = make_registration(("grok-product-1",))
    store = GrokBuildSessionStore(tmp_path / "runtime-state" / "sessions")
    adapter, workspace, scenario_path = build_adapter(
        tmp_path,
        replica_id="grok-product-1",
        registration=registration,
        session_store=store,
        archive=AuditArchive(tmp_path / "archive"),
        session_id="session-a",
        scenario_changes=scenario_changes,
    )
    return adapter, workspace, scenario_path, store


def test_missing_stored_session_fails_before_resume_process(tmp_path: Path) -> None:
    adapter, workspace, _, _ = _single(tmp_path)
    resumed = request(
        workspace,
        "grok-product-1",
        round_id="2026-08-17-late",
        prompt=LATE_PROMPT,
        session_reference="session-a",
    )
    assert adapter.preflight(resumed).ready

    with pytest.raises(GrokBuildSessionError) as exc:
        adapter.run(resumed)

    assert exc.value.path == "session_reference"
    assert _run_invocations(workspace) == []


def test_corrupt_stored_session_fails_without_fresh_fallback(tmp_path: Path) -> None:
    adapter, workspace, _, store = _single(tmp_path)
    record = store.record_path("grok-product", "grok-product-1")
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text("not json\n", encoding="utf-8")
    resumed = request(
        workspace,
        "grok-product-1",
        round_id="2026-08-17-late",
        prompt=LATE_PROMPT,
        session_reference="session-a",
    )
    adapter.preflight(resumed)

    with pytest.raises(GrokBuildSessionError):
        adapter.run(resumed)

    assert _run_invocations(workspace) == []


def test_mismatched_request_session_is_rejected(tmp_path: Path) -> None:
    adapter, workspace, _, store = _single(tmp_path)
    store.save("grok-product", "grok-product-1", "session-a")
    request_with_wrong_ref = request(
        workspace,
        "grok-product-1",
        round_id="2026-08-17-late",
        prompt=LATE_PROMPT,
        session_reference="session-b",
    )
    adapter.preflight(request_with_wrong_ref)

    with pytest.raises(GrokBuildSessionError) as exc:
        adapter.run(request_with_wrong_ref)

    assert exc.value.path == "session_reference"
    assert _run_invocations(workspace) == []


@pytest.mark.parametrize("mode", ["missing", "duplicate", "invalid-json"])
def test_invalid_fresh_session_event_is_not_persisted(
    tmp_path: Path,
    mode: str,
) -> None:
    adapter, workspace, _, store = _single(tmp_path, session_event_mode=mode)
    fresh = request(
        workspace,
        "grok-product-1",
        round_id="2026-08-17-morning",
        prompt=MORNING_PROMPT,
    )
    adapter.preflight(fresh)

    with pytest.raises(GrokBuildSessionError) as exc:
        adapter.run(fresh)

    assert exc.value.path == "session_reference"
    assert not store.record_path("grok-product", "grok-product-1").exists()


def test_resumed_output_must_report_same_session(tmp_path: Path) -> None:
    adapter, workspace, scenario_path, _ = _single(tmp_path)
    fresh = request(
        workspace,
        "grok-product-1",
        round_id="2026-08-17-morning",
        prompt=MORNING_PROMPT,
    )
    adapter.preflight(fresh)
    first = adapter.run(fresh)
    (workspace / "outbox" / "decision.json").unlink()
    scenario_payload = json.loads(scenario_path.read_text(encoding="utf-8"))
    scenario_payload["resume_session_id"] = "different-session"
    scenario_path.write_text(json.dumps(scenario_payload), encoding="utf-8")
    resumed = request(
        workspace,
        "grok-product-1",
        round_id="2026-08-17-late",
        prompt=LATE_PROMPT,
        session_reference=first.session_reference,
    )
    adapter.preflight(resumed)

    with pytest.raises(GrokBuildSessionError) as exc:
        adapter.run(resumed)

    assert exc.value.path == "session_reference"


def test_store_never_replaces_replica_session(tmp_path: Path) -> None:
    store = GrokBuildSessionStore(tmp_path / "sessions")
    store.save("product", "replica", "session-a")

    with pytest.raises(GrokBuildSessionError) as exc:
        store.save("product", "replica", "session-b")

    assert exc.value.path == "session_reference"


def test_one_session_cannot_be_shared_by_two_replicas(tmp_path: Path) -> None:
    store = GrokBuildSessionStore(tmp_path / "sessions")
    store.save("product", "replica-a", "shared-session")

    with pytest.raises(GrokBuildSessionError) as exc:
        store.save("product", "replica-b", "shared-session")

    assert exc.value.path == "session_reference"
