"""R20: incomplete or drifted sealed files fail explicitly."""

from pathlib import Path

import pytest

from arena_runtime.orchestrator import OrchestratorError

from .conftest import DECISION_A, collect, make_result, make_workspace


def test_missing_completed_file_is_rejected(tmp_path: Path) -> None:
    result = make_result(payload=DECISION_A)

    with pytest.raises(OrchestratorError) as exc:
        collect(tmp_path, (result,), payloads={"product-a-1": None})

    assert exc.value.path == "workspaces.product-a-1.outbox.decision"


def test_checksum_drift_before_staging_is_rejected(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path, "product-a-1", b"not the sealed bytes")
    result = make_result(payload=DECISION_A)

    with pytest.raises(OrchestratorError) as exc:
        collect(tmp_path, (result,), workspaces={"product-a-1": workspace})

    assert exc.value.path == "workspaces.product-a-1.outbox.decision"


def test_missing_workspace_is_rejected(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path, "product-a-1", DECISION_A)

    with pytest.raises(OrchestratorError) as exc:
        collect(
            tmp_path,
            (
                make_result(replica_id="product-a-1", payload=DECISION_A),
                make_result(replica_id="product-a-2", outcome="timeout"),
            ),
            workspaces={"product-a-1": workspace},
        )

    assert exc.value.path == "workspaces"
