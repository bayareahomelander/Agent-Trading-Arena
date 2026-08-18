"""R26: deterministic two-product fixture through the Phase D path."""

from pathlib import Path

from arena_runtime.orchestrator import (
    mark_official_close,
    reconstruct_published_round,
    run_archived_baselines,
)
from tests.r26.conftest import SESSION, VENDOR, run_fixture_season
from arena_kernel.marketdata import FixtureVendor


def test_fixture_round_commits_four_replicas_and_reproduces_from_archive(
    tmp_path: Path,
) -> None:
    first = run_fixture_season(tmp_path / "run-1")

    assert first["preflight"].ready is True
    assert first["publication"].committed is True
    assert first["publication"].published_replica_ids == (
        "product-a-1",
        "product-a-2",
        "product-b-1",
        "product-b-2",
    )
    assert first["close"].status == "marked"
    assert first["nlvs"] == {
        "product-a-1": "1000.00",
        "product-a-2": "1000.00",
        "product-b-1": "1000.00",
        "product-b-2": "1000.00",
    }
    assert "baseline:cash" in first["baselines"]

    books_root = first["books_root"]
    replayed = reconstruct_published_round(books_root, "2026-11-02-morning")
    assert replayed == first["books"]
    second_close = mark_official_close(
        books_root=books_root,
        vendor=FixtureVendor(VENDOR),
        session_date=SESSION,
        replica_ids=tuple(first["nlvs"]),
        marked_at=first["close"].marks[0].events[0].timestamp,
    )
    assert {mark.replica_id: str(mark.nlv) for mark in second_close.marks} == first["nlvs"]
    second_baselines = run_archived_baselines(
        tape_dir=first["tape"],
        books_root=tmp_path / "run-1-baselines-again",
    )
    assert second_baselines == first["baselines"]

    second = run_fixture_season(tmp_path / "run-2")
    assert second["events"] == first["events"]
    assert second["books"] == first["books"]
    assert second["nlvs"] == first["nlvs"]
    assert second["baselines"] == first["baselines"]
