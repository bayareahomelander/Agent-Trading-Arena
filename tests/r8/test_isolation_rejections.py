"""R8: ambiguous roots, links, layouts, and credential stores fail early."""

import os
import subprocess
from pathlib import Path

import pytest

from arena_runtime.isolation import IsolationError, prepare_replica_launch

from .conftest import make_season, sanitized_host_environment


def _directory_link(target: Path, link: Path) -> None:
    try:
        os.symlink(target, link, target_is_directory=True)
        return
    except OSError as symlink_error:
        if os.name != "nt":
            pytest.skip(f"symlink creation unavailable: {symlink_error}")
    completed = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
        check=False,
    )
    if completed.returncode != 0:
        pytest.skip(
            "symlink/junction creation unavailable: "
            + completed.stderr.decode(errors="replace")
        )


@pytest.mark.parametrize(
    "replica_id",
    ["", ".", "..", "product-a-1/../product-a-2", "product-a-1\\other"],
)
def test_broad_or_traversing_replica_id_is_rejected(
    tmp_path: Path,
    replica_id: str,
) -> None:
    season = make_season(tmp_path)

    with pytest.raises(IsolationError) as exc:
        prepare_replica_launch(
            season,
            replica_id,
            host_environment=sanitized_host_environment(),
        )

    assert exc.value.path == "replica_id"


def test_missing_workspace_contract_path_is_rejected(tmp_path: Path) -> None:
    season = make_season(tmp_path)
    (season / "replicas" / "product-a-1" / "PROMPT.md").unlink()

    with pytest.raises(IsolationError) as exc:
        prepare_replica_launch(
            season,
            "product-a-1",
            host_environment=sanitized_host_environment(),
        )

    assert exc.value.path == "workspace.PROMPT.md"


def test_unexpected_top_level_workspace_path_is_rejected(tmp_path: Path) -> None:
    season = make_season(tmp_path)
    (season / "replicas" / "product-a-1" / "extra").mkdir()

    with pytest.raises(IsolationError) as exc:
        prepare_replica_launch(
            season,
            "product-a-1",
            host_environment=sanitized_host_environment(),
        )

    assert exc.value.path == "workspace.extra"


def test_symlinked_workspace_is_rejected(tmp_path: Path) -> None:
    season = make_season(tmp_path, replica_ids=("product-a-2",))
    external = tmp_path / "external-workspace"
    external.mkdir()
    link = season / "replicas" / "product-a-1"
    _directory_link(external, link)

    with pytest.raises(IsolationError) as caught:
        prepare_replica_launch(
            season,
            "product-a-1",
            host_environment=sanitized_host_environment(),
        )

    assert caught.value.path == "workspace"


def test_internal_symlink_escape_is_rejected(tmp_path: Path) -> None:
    season = make_season(tmp_path)
    external = tmp_path / "external"
    external.mkdir()
    link = season / "replicas" / "product-a-1" / "agent" / "notes" / "outside"
    _directory_link(external, link)

    with pytest.raises(IsolationError) as caught:
        prepare_replica_launch(
            season,
            "product-a-1",
            host_environment=sanitized_host_environment(),
        )

    assert caught.value.path.startswith("workspace.agent/notes/outside")
