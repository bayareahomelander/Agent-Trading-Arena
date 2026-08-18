"""R8: one validated replica root becomes the process cwd."""

import json
from pathlib import Path

from arena_runtime.isolation import prepare_replica_launch, run_isolated_process

from .conftest import argv, deadline, make_season, sanitized_host_environment


def test_valid_replica_launch_freezes_direct_workspace_and_credential_store(
    tmp_path: Path,
) -> None:
    season, credentials = make_season(tmp_path)

    launch = prepare_replica_launch(
        season,
        "product-a-1",
        credential_store=credentials,
        host_environment=sanitized_host_environment(),
    )

    assert launch.workspace == season / "replicas" / "product-a-1"
    assert launch.workspace.parent == launch.replicas_root
    assert launch.credential_store == credentials
    assert launch.read_only_paths == (
        launch.workspace / "RULES.md",
        launch.workspace / "PROMPT.md",
        launch.workspace / "state",
    )
    assert launch.writable_paths == (
        launch.workspace / "agent",
        launch.workspace / "outbox",
    )


def test_isolated_process_uses_replica_root_as_cwd(tmp_path: Path) -> None:
    season, credentials = make_season(tmp_path)
    launch = prepare_replica_launch(
        season,
        "product-a-1",
        credential_store=credentials,
        host_environment=sanitized_host_environment(),
    )

    facts = run_isolated_process(
        launch,
        argv("report"),
        deadline=deadline(),
    )
    report = json.loads(facts.stdout)

    assert facts.cwd == launch.workspace
    assert Path(report["cwd"]) == launch.workspace
    assert report["replica_id"] == "product-a-1"
    assert Path(report["workspace"]) == launch.workspace


def test_launch_environment_is_minimal_and_drops_secret_or_unrelated_values(
    tmp_path: Path,
) -> None:
    season, credentials = make_season(tmp_path)
    launch = prepare_replica_launch(
        season,
        "product-a-1",
        credential_store=credentials,
        host_environment=sanitized_host_environment(),
    )
    environment = launch.environment()

    assert environment["ARENA_REPLICA_ID"] == "product-a-1"
    assert environment["ARENA_WORKSPACE"] == str(launch.workspace)
    assert "HOME" not in environment
    assert "UNRELATED_SETTING" not in environment
    assert "PROVIDER_API_KEY" not in environment
    assert str(credentials) not in environment.values()

    facts = run_isolated_process(launch, argv("report"), deadline=deadline())
    report = json.loads(facts.stdout)
    assert report["home"] is None
    assert report["unrelated"] is None
    assert report["api_key"] is None
