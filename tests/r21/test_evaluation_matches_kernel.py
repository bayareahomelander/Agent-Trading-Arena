"""R21: candidate books and events match a direct D8/D11 call."""

from pathlib import Path

from arena_kernel.matching import apply_decision
from arena_kernel.schema.decision import parse_decision
from arena_kernel.schema.events import dump_ledger_event
from arena_kernel.schema.fills import dump_fills
from arena_kernel.schema.portfolio import dump_portfolio
from tests.r20.conftest import make_result

from .conftest import (
    HOLD_DECISION,
    SPY_BUY,
    cash_book,
    empty_fills,
    evaluate,
    evaluation_snapshot,
)


def test_candidate_book_and_events_match_direct_apply_decision(tmp_path: Path) -> None:
    book = cash_book()
    snapshot = evaluation_snapshot(book)
    expected_events, expected_book = apply_decision(
        book,
        parse_decision(SPY_BUY),
        snapshot,
    )

    result, _collection = evaluate(
        tmp_path,
        (make_result(payload=SPY_BUY),),
        payloads={"product-a-1": SPY_BUY},
        books={"product-a-1": book},
        snapshot=snapshot,
        fills={"product-a-1": empty_fills()},
    )

    assert result.publishable is True
    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert [dump_ledger_event(event) for event in candidate.events] == [
        dump_ledger_event(event) for event in expected_events
    ]
    assert dump_portfolio(candidate.portfolio) == dump_portfolio(expected_book)
    assert dump_fills(candidate.fills) != dump_fills(empty_fills())
    assert dump_portfolio(book) == dump_portfolio(cash_book())


def test_hold_candidate_matches_direct_hold_apply(tmp_path: Path) -> None:
    book = cash_book()
    snapshot = evaluation_snapshot(book)
    expected_events, expected_book = apply_decision(
        book,
        parse_decision(HOLD_DECISION),
        snapshot,
    )

    result, _collection = evaluate(
        tmp_path,
        (make_result(payload=HOLD_DECISION),),
        payloads={"product-a-1": HOLD_DECISION},
        books={"product-a-1": book},
        snapshot=snapshot,
    )

    candidate = result.candidates[0]
    assert [dump_ledger_event(event) for event in candidate.events] == [
        dump_ledger_event(event) for event in expected_events
    ]
    assert dump_portfolio(candidate.portfolio) == dump_portfolio(expected_book)
    assert dump_portfolio(candidate.portfolio) == dump_portfolio(book)
