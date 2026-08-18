"""R21: a malformed staged decision follows the kernel missing path."""

from pathlib import Path

from arena_kernel.schema.events import DecisionMissingPayload
from arena_kernel.schema.portfolio import dump_portfolio
from tests.r20.conftest import make_result

from .conftest import MALFORMED_DECISION, cash_book, evaluate


def test_malformed_decision_emits_missing_and_leaves_the_book(tmp_path: Path) -> None:
    book = cash_book()
    result, collection = evaluate(
        tmp_path,
        (make_result(payload=MALFORMED_DECISION),),
        payloads={"product-a-1": MALFORMED_DECISION},
        books={"product-a-1": book},
    )

    assert result.publishable is True
    candidate = result.candidates[0]
    assert collection.records[0].exposed_to_kernel is True
    assert candidate.events[0].event_type == "decision_missing"
    assert isinstance(candidate.events[0].payload, DecisionMissingPayload)
    assert dump_portfolio(candidate.portfolio) == dump_portfolio(book)
