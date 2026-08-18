"""R15: two replicas capture and resume only their own Grok sessions."""

import json
from pathlib import Path

from arena_runtime.adapters.grok_build import GrokBuildSessionStore
from arena_runtime.audit import AuditArchive

from .conftest import (
    LATE_PROMPT,
    MORNING_PROMPT,
    build_adapter,
    make_registration,
    request,
)


def _run_commands(workspace: Path) -> list[list[str]]:
    entries = [
        json.loads(line)
        for line in (workspace / "agent" / "notes" / "commands.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    return [entry for entry in entries if "--single" in entry]


def test_two_replicas_resume_exact_one_to_one_sessions(tmp_path: Path) -> None:
    replica_ids = ("grok-product-1", "grok-product-2")
    registration = make_registration(replica_ids)
    store = GrokBuildSessionStore(tmp_path / "runtime-state" / "sessions")
    archive = AuditArchive(tmp_path / "archive")
    adapter_a, workspace_a, _ = build_adapter(
        tmp_path,
        replica_id=replica_ids[0],
        registration=registration,
        session_store=store,
        archive=archive,
        session_id="session-a",
    )
    adapter_b, workspace_b, _ = build_adapter(
        tmp_path,
        replica_id=replica_ids[1],
        registration=registration,
        session_store=store,
        archive=archive,
        session_id="session-b",
    )

    a_morning = request(
        workspace_a,
        replica_ids[0],
        round_id="2026-08-17-morning",
        prompt=MORNING_PROMPT,
    )
    b_morning = request(
        workspace_b,
        replica_ids[1],
        round_id="2026-08-17-morning",
        prompt=MORNING_PROMPT,
    )
    assert adapter_a.preflight(a_morning).ready
    assert adapter_b.preflight(b_morning).ready
    a_first = adapter_a.run(a_morning)
    b_first = adapter_b.run(b_morning)
    assert a_first.session_reference == "session-a"
    assert b_first.session_reference == "session-b"

    (workspace_a / "outbox" / "decision.json").unlink()
    (workspace_b / "outbox" / "decision.json").unlink()
    a_late = request(
        workspace_a,
        replica_ids[0],
        round_id="2026-08-17-late",
        prompt=LATE_PROMPT,
        session_reference=a_first.session_reference,
    )
    b_late = request(
        workspace_b,
        replica_ids[1],
        round_id="2026-08-17-late",
        prompt=LATE_PROMPT,
        session_reference=b_first.session_reference,
    )
    assert adapter_a.preflight(a_late).ready
    assert adapter_b.preflight(b_late).ready
    assert adapter_a.run(a_late).session_reference == "session-a"
    assert adapter_b.run(b_late).session_reference == "session-b"

    a_commands = _run_commands(workspace_a)
    b_commands = _run_commands(workspace_b)
    assert "--resume" not in a_commands[0]
    assert "--resume" not in b_commands[0]
    assert "--resume" in a_commands[1] and "session-a" in a_commands[1]
    assert "--resume" in b_commands[1] and "session-b" in b_commands[1]
    assert all("session-b" not in command for command in a_commands)
    assert all("session-a" not in command for command in b_commands)
    assert "-c" not in a_commands[1]
    assert "--continue" not in a_commands[1]
    assert "--session-id" not in a_commands[1]
    assert "--last" not in a_commands[1]


def test_session_records_live_outside_both_replica_workspaces(tmp_path: Path) -> None:
    registration = make_registration(("grok-product-1",))
    store = GrokBuildSessionStore(tmp_path / "runtime-state" / "sessions")
    adapter, workspace, _ = build_adapter(
        tmp_path,
        replica_id="grok-product-1",
        registration=registration,
        session_store=store,
        archive=AuditArchive(tmp_path / "archive"),
        session_id="session-a",
    )
    morning = request(
        workspace,
        "grok-product-1",
        round_id="2026-08-17-morning",
        prompt=MORNING_PROMPT,
    )
    adapter.preflight(morning)
    adapter.run(morning)

    record = store.record_path("grok-product", "grok-product-1")
    assert record.is_file()
    assert not record.is_relative_to(workspace)
    payload = json.loads(record.read_text(encoding="utf-8"))
    assert payload["session_reference"] == "session-a"
