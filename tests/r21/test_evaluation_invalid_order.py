"""R21: one invalid order rejects only that order under existing D8/D11 rules."""

from pathlib import Path

from arena_kernel.matching import apply_decision
from arena_kernel.schema.decision import parse_decision
from arena_kernel.schema.events import dump_ledger_event
from arena_kernel.schema.portfolio import dump_portfolio
from tests.r20.conftest import make_result

from .conftest import MIXED_ORDERS, cash_book, evaluate, evaluation_snapshot


def test_one_invalid_order_rejects_only_that_order(tmp_path: Path) -> None:
    book = cash_book()
    snapshot = evaluation_snapshot(book, symbols=("SPY",))
    expected_events, expected_book = apply_decision(
        book,
        parse_decision(MIXED_ORDERS),
        snapshot,
    )

    result, _collection = evaluate(
        tmp_path,
        (make_result(payload=MIXED_ORDERS),),
        payloads={"product-a-1": MIXED_ORDERS},
        books={"product-a-1": book},
        snapshot=snapshot,
    )

    candidate = result.candidates[0]
    assert [event.event_type for event in candidate.events] == [
        event.event_type for event in expected_events
    ]
    assert [dump_ledger_event(event) for event in candidate.events] == [
        dump_ledger_event(event) for event in expected_events
    ]
    assert dump_portfolio(candidate.portfolio) == dump_portfolio(expected_book)
    assert any(event.event_type == "order_rejected" for event in candidate.events)
    assert any(event.event_type == "order_filled" for event in candidate.events)
