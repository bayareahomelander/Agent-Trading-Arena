"""R21: a voided collection never calls the kernel."""

from pathlib import Path

from tests.r20.conftest import make_result

from .conftest import HOLD_DECISION, cash_book, evaluate


def test_voided_round_returns_no_publishable_candidates(tmp_path: Path, monkeypatch) -> None:
    called = {"parse": False, "apply": False}

    def parse_boom(*_args, **_kwargs):
        called["parse"] = True
        raise AssertionError("voided rounds must not parse staged bytes")

    def apply_boom(*_args, **_kwargs):
        called["apply"] = True
        raise AssertionError("voided rounds must not apply decisions")

    monkeypatch.setattr("arena_runtime.orchestrator.parse_decision", parse_boom)
    monkeypatch.setattr("arena_runtime.orchestrator.apply_decision", apply_boom)

    result, collection = evaluate(
        tmp_path,
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
    assert result.publishable is False
    assert result.candidates == ()
    assert called == {"parse": False, "apply": False}
