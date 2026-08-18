"""R19: incomplete or inconsistent sealed sets fail explicitly."""

import pytest

from arena_runtime.disposition import (
    COMMON_DATA_AVAILABLE,
    DispositionError,
    decide_round_disposition,
)

from .conftest import make_result


def test_empty_results_are_rejected() -> None:
    with pytest.raises(DispositionError) as exc:
        decide_round_disposition((), COMMON_DATA_AVAILABLE)

    assert exc.value.path == "results"


def test_duplicate_replica_is_rejected() -> None:
    with pytest.raises(DispositionError) as exc:
        decide_round_disposition(
            (
                make_result(replica_id="product-a-1"),
                make_result(replica_id="product-a-1", outcome="timeout"),
            ),
            COMMON_DATA_AVAILABLE,
        )

    assert exc.value.path == "results.1"


def test_unknown_common_data_status_is_rejected() -> None:
    with pytest.raises(DispositionError) as exc:
        decide_round_disposition((make_result(),), "guessed")

    assert exc.value.path == "common_data_status"
