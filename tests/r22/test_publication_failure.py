"""R22: a void set or pre-finalize failure publishes nothing."""

from pathlib import Path

from tests.r20.conftest import make_result
from tests.r21.conftest import HOLD_DECISION, cash_book, evaluate

from .conftest import publish, two_candidate_evaluation


def test_void_disposition_publishes_neither_book(tmp_path: Path) -> None:
    candidates, collection = evaluate(
        tmp_path / "eval",
        (
            make_result(payload=HOLD_DECISION),
            make_result(
                product_id="product-b",
                replica_id="product-b-1",
                outcome="quota_exhausted",
            ),
        ),
        payloads={"product-a-1": HOLD_DECISION, "product-b-1": None},
        books={
            "product-a-1": cash_book(),
            "product-b-1": cash_book("product-b-1", product_id="product-b"),
        },
    )
    assert collection.kernel_records() == ()
    assert candidates.publishable is False

    publication, books_root, archive = publish(tmp_path, candidates)

    assert publication.committed is False
    assert publication.published_replica_ids == ()
    assert not (books_root / "product-a-1").exists()
    assert not (books_root / "product-b-1").exists()
    assert not (books_root / ".committed").exists()
    assert not archive.events_path.exists()


def test_injected_failure_before_finalization_publishes_neither(
    tmp_path: Path,
    monkeypatch,
) -> None:
    candidates, _collection, _book_a, _book_b, _snapshot = two_candidate_evaluation(
        tmp_path / "eval"
    )

    def boom(*_args, **_kwargs):
        raise RuntimeError("injected pre-publish failure")

    monkeypatch.setattr(
        "arena_runtime.orchestrator._finalize_candidate_publication",
        boom,
    )

    try:
        publish(tmp_path, candidates)
    except RuntimeError:
        books_root = (tmp_path / "books").resolve()
        assert not (books_root / "product-a-1").exists()
        assert not (books_root / "product-b-1").exists()
        assert not (books_root / ".committed" / candidates.round_id).exists()
    else:
        raise AssertionError("expected the injected finalization failure")
