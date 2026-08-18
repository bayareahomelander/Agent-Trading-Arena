"""R23: fixture close marks equal a direct D12 call."""

from datetime import date
from decimal import Decimal
from pathlib import Path

from arena_kernel.ledger import final_nlv, mark_to_close
from arena_kernel.schema.events import dump_ledger_event

from .conftest import MARKED_AT, close_session, fixture_vendor, positioned_book
from tests.r21.conftest import cash_book


def test_fixture_marks_equal_direct_d12_byte_for_byte(tmp_path: Path) -> None:
    cash = cash_book()
    spy = positioned_book("product-b-1", "SPY")
    books_root = (tmp_path / "books").resolve()
    closes = fixture_vendor().official_closes(date(2026, 11, 2))

    result = close_session(books_root, cash, spy)

    assert result.status == "marked"
    assert result.reason is None
    assert [item.replica_id for item in result.marks] == ["product-a-1", "product-b-1"]
    for book, mark in zip((cash, spy), result.marks, strict=True):
        equity, mark_event = mark_to_close(book, closes, timestamp=MARKED_AT)
        nlv, nlv_event = final_nlv(book, closes, timestamp=MARKED_AT)
        assert mark.equity == equity
        assert mark.nlv == nlv
        assert [dump_ledger_event(event) for event in mark.events] == [
            dump_ledger_event(mark_event),
            dump_ledger_event(nlv_event),
        ]
    assert result.marks[0].equity == Decimal("1000.00")
    assert result.marks[0].nlv == Decimal("1000.00")
    archived = (
        books_root / ".close" / "2026-11-02" / "product-b-1" / "events.jsonl"
    )
    assert archived.read_text(encoding="utf-8") == "".join(
        dump_ledger_event(event) for event in result.marks[1].events
    )
