"""R20: present decisions are copied byte-for-byte with matching checksums."""

from pathlib import Path

from tests.r6.conftest import EXACT_DECISION
from tests.r18.conftest import launch_barrier

from arena_runtime.disposition import (
    COMMON_DATA_AVAILABLE,
    REPLICA_TREATMENT_EVALUATE,
    ROUND_TREATMENT_EVALUATE,
    decide_round_disposition,
)
from arena_runtime.orchestrator import collect_sealed_decisions

from .conftest import DECISION_A, DECISION_B, checksum_of, collect, make_result


def test_present_files_are_copied_byte_for_byte_and_checksummed(tmp_path: Path) -> None:
    results = (
        make_result(replica_id="product-a-1", payload=DECISION_A),
        make_result(
            product_id="product-b",
            replica_id="product-b-1",
            payload=DECISION_B,
        ),
    )

    collection = collect(
        tmp_path,
        results,
        payloads={"product-a-1": DECISION_A, "product-b-1": DECISION_B},
    )

    assert collection.round_treatment == ROUND_TREATMENT_EVALUATE
    assert [item.replica_id for item in collection.records] == [
        "product-a-1",
        "product-b-1",
    ]
    assert [item.staged_path.read_bytes() for item in collection.records] == [
        DECISION_A,
        DECISION_B,
    ]
    assert [item.byte_length for item in collection.records] == [
        len(DECISION_A),
        len(DECISION_B),
    ]
    assert [item.checksum for item in collection.records] == [
        checksum_of(DECISION_A),
        checksum_of(DECISION_B),
    ]
    assert all(item.treatment == REPLICA_TREATMENT_EVALUATE for item in collection.records)
    assert all(item.exposed_to_kernel for item in collection.records)
    assert collection.kernel_records() == collection.records


def test_barrier_completed_decisions_are_copied_from_the_outbox(tmp_path: Path) -> None:
    barrier, _, _, requests, _ = launch_barrier(tmp_path)
    disposition = decide_round_disposition(barrier.results, COMMON_DATA_AVAILABLE)

    collection = collect_sealed_decisions(
        barrier=barrier,
        disposition=disposition,
        workspaces={request.replica_id: request.workspace for request in requests},
        staging_root=(tmp_path / "staging").resolve(),
    )

    assert [item.staged_path.read_bytes() for item in collection.kernel_records()] == [
        EXACT_DECISION,
        EXACT_DECISION,
    ]
    assert {item.checksum for item in collection.kernel_records()} == {
        checksum_of(EXACT_DECISION)
    }
