"""R15: session continuity adds no provider failure classification."""

import inspect
from pathlib import Path

import pytest

from arena_runtime.adapters.grok_build import (
    GrokBuildAdapter,
    GrokBuildPreflightError,
    GrokBuildSessionStore,
)
from arena_runtime.audit import AuditArchive

from .conftest import build_adapter, make_registration


def test_session_store_inside_agent_workspace_is_rejected(tmp_path: Path) -> None:
    registration = make_registration(("grok-product-1",))
    outside_store = GrokBuildSessionStore(tmp_path / "outside-store")
    adapter, workspace, _ = build_adapter(
        tmp_path,
        replica_id="grok-product-1",
        registration=registration,
        session_store=outside_store,
        archive=AuditArchive(tmp_path / "archive"),
        session_id="session-a",
    )

    with pytest.raises(GrokBuildPreflightError) as exc:
        GrokBuildAdapter(
            registration,
            adapter._launch,  # noqa: SLF001 - construct invalid boundary
            archive=AuditArchive(tmp_path / "other-archive"),
            session_store=GrokBuildSessionStore(workspace / "agent" / "sessions"),
        )

    assert exc.value.path == "session_store"


def test_session_helpers_do_not_classify_provider_failures() -> None:
    source = inspect.getsource(GrokBuildSessionStore)

    assert "quota_exhausted" not in source
    assert "provider_unavailable" not in source
    assert "refusal" not in source
    assert "runner_error" not in source


def test_resume_argv_uses_documented_grok_flag() -> None:
    source = inspect.getsource(GrokBuildAdapter._resume_argv)

    assert "--resume" in source
    assert "codex exec" not in source
    assert "--last" not in source
    assert "--continue" not in source
    assert "--session-id" not in source
