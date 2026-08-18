"""R2: runner requests freeze provider-neutral round inputs."""

from dataclasses import FrozenInstanceError
from datetime import datetime
from pathlib import Path

import pytest

from arena_runtime.runner import RunnerContractError

from .conftest import make_request


def test_valid_runner_request_is_frozen_and_preserves_instruction_bytes(
    tmp_path: Path,
) -> None:
    request = make_request(tmp_path / "replica")

    assert request.launch_instruction == b"Frozen launch instruction"
    assert request.workspace == tmp_path / "replica"
    with pytest.raises(FrozenInstanceError):
        request.replica_id = "other"  # type: ignore[misc]


def test_naive_deadline_fails_with_named_field(tmp_path: Path) -> None:
    with pytest.raises(RunnerContractError) as exc:
        make_request(
            tmp_path / "replica",
            deadline=datetime(2026, 8, 17, 10, 15),
        )

    assert exc.value.path == "deadline"


def test_relative_workspace_fails_with_named_field() -> None:
    with pytest.raises(RunnerContractError) as exc:
        make_request(Path("replicas/product-a-1"))

    assert exc.value.path == "workspace"


def test_unresolved_workspace_fails_with_named_field(tmp_path: Path) -> None:
    with pytest.raises(RunnerContractError) as exc:
        make_request(tmp_path / "season" / ".." / "replica")

    assert exc.value.path == "workspace"


@pytest.mark.parametrize(
    ("changes", "path"),
    [
        ({"contract_version": "2"}, "contract_version"),
        ({"product_id": " product-a"}, "product_id"),
        ({"replica_id": ""}, "replica_id"),
        ({"round_id": "2026-08-17-evening"}, "round_id"),
        ({"model_reference": ""}, "model_reference"),
        ({"configuration_reference": " "}, "configuration_reference"),
        ({"launch_instruction": b""}, "launch_instruction"),
        ({"session_reference": " session"}, "session_reference"),
    ],
)
def test_invalid_request_fields_fail_by_name(
    tmp_path: Path,
    changes: dict[str, object],
    path: str,
) -> None:
    with pytest.raises(RunnerContractError) as exc:
        make_request(tmp_path / "replica", **changes)

    assert exc.value.path == path
