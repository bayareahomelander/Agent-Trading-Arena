"""R20: a voided round may archive bytes but does not expose them to the kernel."""

import inspect
from pathlib import Path

from arena_runtime.disposition import (
    REPLICA_TREATMENT_VOIDED,
    ROUND_TREATMENT_VOID_AND_PAUSE,
)
from arena_runtime.orchestrator import collect_sealed_decisions

from .conftest import DECISION_A, collect, make_result


def test_voided_round_archives_bytes_but_does_not_expose_them(tmp_path: Path) -> None:
    results = (
        make_result(
            product_id="product-a",
            replica_id="product-a-1",
            payload=DECISION_A,
        ),
        make_result(
            product_id="product-b",
            replica_id="product-b-1",
            outcome="quota_exhausted",
        ),
    )

    collection = collect(
        tmp_path,
        results,
        payloads={"product-a-1": DECISION_A, "product-b-1": None},
    )

    assert collection.round_treatment == ROUND_TREATMENT_VOID_AND_PAUSE
    assert [item.treatment for item in collection.records] == [
        REPLICA_TREATMENT_VOIDED,
        REPLICA_TREATMENT_VOIDED,
    ]
    archived = collection.records[0]
    assert archived.staged_path is not None
    assert archived.staged_path.read_bytes() == DECISION_A
    assert archived.exposed_to_kernel is False
    assert collection.records[1].staged_path is None
    assert collection.kernel_records() == ()


def test_voided_round_has_no_kernel_call() -> None:
    source = inspect.getsource(collect_sealed_decisions)

    assert "parse_decision" not in source
    assert "apply_decision" not in source
    assert "validate_decision" not in source
    assert "apply_order" not in source
    assert "mark_to_close" not in source
