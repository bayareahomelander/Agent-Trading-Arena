"""R26: opt-in live adapter smokes are excluded from default pytest."""

import inspect
from pathlib import Path

import pytest

from tests.r26.live_smoke import (
    FORBIDDEN_ARCHIVE_NAMES,
    LiveSmokeSkipped,
    live_smoke_enabled,
    run_codex_smoke,
    run_grok_smoke,
)


def test_live_smoke_harness_never_archives_credentials() -> None:
    source = inspect.getsource(run_codex_smoke) + inspect.getsource(run_grok_smoke)
    assert "auth.json" not in source
    assert "API_KEY" not in source
    assert "write_provider_artifact" not in source
    for name in FORBIDDEN_ARCHIVE_NAMES:
        assert name in inspect.getsource(
            __import__("tests.r26.live_smoke", fromlist=["FORBIDDEN_ARCHIVE_NAMES"])
        )


@pytest.mark.skipif(not live_smoke_enabled(), reason="opt-in live adapter smoke")
def test_live_codex_smoke(tmp_path: Path) -> None:
    try:
        assert run_codex_smoke(tmp_path) == "codex-smoke-harness-ready"
    except LiveSmokeSkipped as exc:
        pytest.skip(str(exc))


@pytest.mark.skipif(not live_smoke_enabled(), reason="opt-in live adapter smoke")
def test_live_grok_smoke(tmp_path: Path) -> None:
    try:
        assert run_grok_smoke(tmp_path) == "grok-smoke-harness-ready"
    except LiveSmokeSkipped as exc:
        pytest.skip(str(exc))
