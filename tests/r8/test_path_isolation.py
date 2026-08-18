"""R8: runtime paths cannot escape to roots or sibling replicas."""

from pathlib import Path

import pytest

from arena_runtime.isolation import (
    IsolationError,
    prepare_replica_launch,
    resolve_replica_path,
)

from .conftest import make_season, sanitized_host_environment


def _launch(tmp_path: Path):
    season, credentials = make_season(tmp_path)
    return prepare_replica_launch(
        season,
        "product-a-1",
        credential_store=credentials,
        host_environment=sanitized_host_environment(),
    )


def test_read_paths_resolve_inside_selected_replica(tmp_path: Path) -> None:
    launch = _launch(tmp_path)

    assert resolve_replica_path(launch, "state/portfolio.json") == (
        launch.workspace / "state" / "portfolio.json"
    )


@pytest.mark.parametrize("relative", ["agent/notes/new.txt", "outbox/decision.json"])
def test_only_declared_writable_areas_are_accepted(
    tmp_path: Path,
    relative: str,
) -> None:
    launch = _launch(tmp_path)

    assert resolve_replica_path(launch, relative, writable=True).is_relative_to(
        launch.workspace
    )


@pytest.mark.parametrize(
    "candidate",
    ["state/portfolio.json", "RULES.md", "."],
)
def test_broad_or_evaluator_owned_write_paths_are_rejected(
    tmp_path: Path,
    candidate: str,
) -> None:
    launch = _launch(tmp_path)

    with pytest.raises(IsolationError) as exc:
        resolve_replica_path(launch, candidate, writable=True)

    assert exc.value.path == "path"


def test_parent_traversal_is_rejected(tmp_path: Path) -> None:
    launch = _launch(tmp_path)

    with pytest.raises(IsolationError) as exc:
        resolve_replica_path(launch, "../product-a-2/state/portfolio.json")

    assert exc.value.path == "path"


def test_absolute_sibling_replica_path_is_rejected(tmp_path: Path) -> None:
    launch = _launch(tmp_path)
    sibling = launch.replicas_root / "product-a-2" / "state" / "portfolio.json"

    with pytest.raises(IsolationError) as exc:
        resolve_replica_path(launch, sibling)

    assert exc.value.path == "path"
