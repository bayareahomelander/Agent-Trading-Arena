"""R21: timeout and missing become recorded no-action without inventing a file."""

from pathlib import Path

from arena_kernel.schema.events import DecisionMissingPayload
from arena_kernel.schema.portfolio import dump_portfolio
from tests.r20.conftest import make_result

from .conftest import HOLD_DECISION, cash_book, evaluate


def test_timeout_is_recorded_no_action_without_a_decision_file(tmp_path: Path) -> None:
    book = cash_book()
    result, collection = evaluate(
        tmp_path,
        (
            make_result(payload=HOLD_DECISION),
            make_result(replica_id="product-a-2", outcome="timeout"),
        ),
        payloads={"product-a-1": HOLD_DECISION, "product-a-2": None},
        books={
            "product-a-1": book,
            "product-a-2": cash_book("product-a-2"),
        },
    )

    timeout = result.candidates[1]
    assert timeout.treatment == "hold_no_action"
    assert timeout.events[0].event_type == "decision_missing"
    assert isinstance(timeout.events[0].payload, DecisionMissingPayload)
    assert timeout.events[0].payload.reason == "timeout"
    assert dump_portfolio(timeout.portfolio) == dump_portfolio(cash_book("product-a-2"))
    assert collection.records[1].staged_path is None
    assert collection.records[1].exposed_to_kernel is False


def test_missing_decision_is_recorded_no_action(tmp_path: Path) -> None:
    result, collection = evaluate(
        tmp_path,
        (make_result(outcome="missing_decision"),),
        payloads={"product-a-1": None},
        books={"product-a-1": cash_book()},
    )

    candidate = result.candidates[0]
    assert candidate.events[0].event_type == "decision_missing"
    assert candidate.events[0].payload.reason == "missing_decision"
    assert collection.kernel_records() == ()
