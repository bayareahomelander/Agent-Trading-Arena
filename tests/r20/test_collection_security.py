"""R20: traversal and symlink escapes are rejected before any copy."""

import os
import subprocess
from pathlib import Path

import pytest

from arena_runtime.orchestrator import OrchestratorError

from .conftest import DECISION_A, collect, make_result, make_workspace, write_decision


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


def _file_link(target: Path, link: Path) -> None:
    try:
        os.symlink(target, link)
        return
    except OSError as symlink_error:
        if os.name != "nt":
            pytest.skip(f"symlink creation unavailable: {symlink_error}")
    completed = subprocess.run(
        ["cmd", "/c", "mklink", str(link), str(target)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
        check=False,
    )
    if completed.returncode != 0:
        pytest.skip(
            "file symlink creation unavailable: "
            + completed.stderr.decode(errors="replace")
        )


def test_unresolved_workspace_traversal_is_rejected(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path, "product-a-1", DECISION_A)
    escaping = workspace / ".." / "product-a-1"

    with pytest.raises(OrchestratorError) as exc:
        collect(
            tmp_path,
            (make_result(payload=DECISION_A),),
            workspaces={"product-a-1": escaping},
        )

    assert exc.value.path == "workspaces.product-a-1"


def test_staging_root_traversal_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(OrchestratorError) as exc:
        collect(
            tmp_path,
            (make_result(payload=DECISION_A),),
            payloads={"product-a-1": DECISION_A},
            staging_root=tmp_path / "staging" / "..",
        )

    assert exc.value.path == "staging_root"


def test_symlinked_decision_file_is_rejected(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path, "product-a-1")
    external = tmp_path / "outside" / "decision.json"
    external.parent.mkdir(parents=True)
    external.write_bytes(DECISION_A)
    _file_link(external, workspace / "outbox" / "decision.json")

    with pytest.raises(OrchestratorError) as exc:
        collect(
            tmp_path,
            (make_result(payload=DECISION_A),),
            workspaces={"product-a-1": workspace},
        )

    assert exc.value.path == "workspaces.product-a-1.outbox.decision"
    staging = tmp_path / "staging" / "2026-08-17-morning" / "product-a-1"
    assert not staging.exists()


def test_symlinked_outbox_escape_is_rejected(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path, "product-a-1")
    (workspace / "outbox").rmdir()
    external = tmp_path / "outside-outbox"
    external.mkdir()
    write_decision(external, DECISION_A)
    _directory_link(external, workspace / "outbox")

    with pytest.raises(OrchestratorError) as exc:
        collect(
            tmp_path,
            (make_result(payload=DECISION_A),),
            workspaces={"product-a-1": workspace},
        )

    assert exc.value.path == "workspaces.product-a-1.outbox.decision"
