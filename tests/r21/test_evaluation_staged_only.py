"""R21: evaluation reads staged bytes, never the live outbox."""

from pathlib import Path

from arena_kernel.matching import apply_decision
from arena_kernel.schema.decision import parse_decision
from arena_kernel.schema.events import dump_ledger_event
from arena_kernel.workspace import OUTBOX_DECISION_FILE
from tests.r20.conftest import make_result

from .conftest import HOLD_DECISION, SPY_BUY, cash_book, evaluate, evaluation_snapshot


def test_later_outbox_write_cannot_change_candidate_evaluation(tmp_path: Path) -> None:
    book = cash_book()
    snapshot = evaluation_snapshot(book)
    expected_events, _expected_book = apply_decision(
        book,
        parse_decision(SPY_BUY),
        snapshot,
    )
    result, collection = evaluate(
        tmp_path,
        (make_result(payload=SPY_BUY),),
        payloads={"product-a-1": SPY_BUY},
        books={"product-a-1": book},
        snapshot=snapshot,
    )

    live = tmp_path / "workspaces" / "product-a-1" / OUTBOX_DECISION_FILE
    live.write_bytes(HOLD_DECISION)

    candidate = result.candidates[0]
    assert collection.records[0].staged_path.read_bytes() == SPY_BUY
    assert live.read_bytes() == HOLD_DECISION
    assert [dump_ledger_event(event) for event in candidate.events] == [
        dump_ledger_event(event) for event in expected_events
    ]
    assert any(event.event_type == "order_filled" for event in candidate.events)
