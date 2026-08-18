"""R21: an evaluator exception yields no publishable candidates."""

from pathlib import Path

from arena_kernel.schema.portfolio import dump_portfolio
from tests.r20.conftest import make_result

from .conftest import SPY_BUY, cash_book, evaluate


def test_injected_evaluator_exception_returns_no_publishable_set(
    tmp_path: Path,
    monkeypatch,
) -> None:
    book = cash_book()

    def boom(*_args, **_kwargs):
        raise RuntimeError("injected evaluator defect")

    monkeypatch.setattr("arena_runtime.orchestrator.apply_decision", boom)

    result, _collection = evaluate(
        tmp_path,
        (make_result(payload=SPY_BUY),),
        payloads={"product-a-1": SPY_BUY},
        books={"product-a-1": book},
    )

    assert result.publishable is False
    assert result.candidates == ()
    assert dump_portfolio(book) == dump_portfolio(cash_book())
