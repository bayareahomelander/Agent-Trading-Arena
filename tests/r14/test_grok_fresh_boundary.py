"""R14: fresh execution adds Grok transport, not resume or failure semantics."""

import inspect
from pathlib import Path

from arena_runtime.adapters.grok_build import GrokBuildAdapter
from arena_runtime.runner import Runner

from .conftest import make_case


def test_grok_adapter_now_satisfies_shared_runner_protocol(tmp_path: Path) -> None:
    adapter, _, _, _, _ = make_case(tmp_path)

    assert isinstance(adapter, Runner)


def test_run_method_contains_no_round_disposition_policy() -> None:
    source = inspect.getsource(GrokBuildAdapter.run)

    assert "void_and_pause" not in source
    assert "commit_eligible" not in source
    assert "round_disposition" not in source


def test_run_source_does_not_parse_decision_json() -> None:
    source = inspect.getsource(GrokBuildAdapter.run)

    assert "parse_decision" not in source
    assert "json.loads" not in source


def test_run_source_does_not_copy_codex_command_semantics() -> None:
    source = inspect.getsource(GrokBuildAdapter._fresh_argv)

    assert "codex exec" not in source
    assert "workspace-write" not in source
    assert "--ignore-user-config" not in source
    assert "--skip-git-repo-check" not in source
