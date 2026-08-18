"""R11: session continuity adds no provider failure classification."""

import inspect
from pathlib import Path

import pytest

from arena_runtime.adapters.codex import CodexAdapter, CodexPreflightError, CodexSessionStore

from .conftest import build_adapter, make_registration
from arena_runtime.audit import AuditArchive


def test_session_store_inside_agent_workspace_is_rejected(tmp_path: Path) -> None:
    registration = make_registration(("codex-product-1",))
    outside_store = CodexSessionStore(tmp_path / "outside-store")
    adapter, workspace, _ = build_adapter(
        tmp_path,
        replica_id="codex-product-1",
        registration=registration,
        session_store=outside_store,
        archive=AuditArchive(tmp_path / "archive"),
        thread_id="thread-a",
    )

    with pytest.raises(CodexPreflightError) as exc:
        CodexAdapter(
            registration,
            adapter._launch,  # noqa: SLF001 - construct invalid boundary
            archive=AuditArchive(tmp_path / "other-archive"),
            session_store=CodexSessionStore(workspace / "agent" / "sessions"),
        )

    assert exc.value.path == "session_store"


def test_session_helpers_do_not_classify_provider_failures() -> None:
    source = inspect.getsource(CodexSessionStore)

    assert "quota_exhausted" not in source
    assert "provider_unavailable" not in source
    assert "refusal" not in source
    assert "runner_error" not in source
