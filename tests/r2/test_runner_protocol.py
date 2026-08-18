"""R2: all adapters share one structural runner boundary."""

from pathlib import Path

import pytest

from arena_runtime.runner import (
    PreflightResult,
    Runner,
    RunnerContractError,
    RunnerRequest,
    RunnerResult,
    require_matching_identity,
)

from .conftest import make_preflight, make_request, make_result


class InMemoryRunner:
    def preflight(self, request: RunnerRequest) -> PreflightResult:
        return make_preflight(
            product_id=request.product_id,
            replica_id=request.replica_id,
            round_id=request.round_id,
        )

    def run(self, request: RunnerRequest) -> RunnerResult:
        return make_result(
            product_id=request.product_id,
            replica_id=request.replica_id,
            round_id=request.round_id,
        )


def test_in_memory_runner_satisfies_shared_protocol(tmp_path: Path) -> None:
    runner = InMemoryRunner()
    request = make_request(tmp_path / "replica")

    assert isinstance(runner, Runner)
    assert require_matching_identity(request, runner.preflight(request)).ready
    assert require_matching_identity(request, runner.run(request)).outcome == "completed"


@pytest.mark.parametrize(
    "field",
    ["product_id", "replica_id", "round_id"],
)
def test_mismatched_result_identity_fails_with_named_field(
    tmp_path: Path,
    field: str,
) -> None:
    request = make_request(tmp_path / "replica")
    changes = {field: "2026-08-17-late" if field == "round_id" else "other"}
    response = make_result(**changes)

    with pytest.raises(RunnerContractError) as exc:
        require_matching_identity(request, response)

    assert exc.value.path == field
