"""R20: missing, timeout, and refusal create metadata only."""

from pathlib import Path

from arena_runtime.disposition import (
    REPLICA_TREATMENT_DISQUALIFY_REFUSAL,
    REPLICA_TREATMENT_HOLD_NO_ACTION,
    ROUND_TREATMENT_EVALUATE,
)

from .conftest import DECISION_A, collect, make_result


def test_missing_and_timeout_create_metadata_without_inventing_a_file(
    tmp_path: Path,
) -> None:
    results = (
        make_result(replica_id="product-a-1", payload=DECISION_A),
        make_result(replica_id="product-a-2", outcome="missing_decision"),
        make_result(
            product_id="product-b",
            replica_id="product-b-1",
            outcome="timeout",
        ),
    )

    collection = collect(
        tmp_path,
        results,
        payloads={"product-a-1": DECISION_A, "product-a-2": None, "product-b-1": None},
    )

    by_replica = {item.replica_id: item for item in collection.records}
    assert collection.round_treatment == ROUND_TREATMENT_EVALUATE
    assert by_replica["product-a-2"].treatment == REPLICA_TREATMENT_HOLD_NO_ACTION
    assert by_replica["product-b-1"].treatment == REPLICA_TREATMENT_HOLD_NO_ACTION
    assert by_replica["product-a-2"].staged_path is None
    assert by_replica["product-b-1"].staged_path is None
    assert by_replica["product-a-2"].checksum is None
    assert by_replica["product-b-1"].checksum is None
    assert [item.replica_id for item in collection.kernel_records()] == ["product-a-1"]
    staging = collection.staging_root / collection.round_id
    assert not (staging / "product-a-2").exists()
    assert not (staging / "product-b-1").exists()


def test_refusal_creates_metadata_without_inventing_a_file(tmp_path: Path) -> None:
    results = (
        make_result(replica_id="product-a-1", payload=DECISION_A),
        make_result(
            product_id="product-b",
            replica_id="product-b-1",
            outcome="refusal",
        ),
    )

    collection = collect(
        tmp_path,
        results,
        payloads={"product-a-1": DECISION_A, "product-b-1": None},
    )

    refused = collection.records[1]
    assert refused.treatment == REPLICA_TREATMENT_DISQUALIFY_REFUSAL
    assert refused.staged_path is None
    assert refused.exposed_to_kernel is False
    assert not (collection.staging_root / collection.round_id / "product-b-1").exists()
    leftover = tmp_path / "workspaces" / "product-b-1" / "outbox" / "decision.json"
    assert not leftover.exists()
