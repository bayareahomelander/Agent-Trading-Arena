"""R23: missing date or symbol defers and writes no valuation event."""

from datetime import date
from pathlib import Path

from .conftest import SESSION, close_session, positioned_book, write_book
from tests.r21.conftest import cash_book


def test_missing_session_date_defers_without_valuation(tmp_path: Path) -> None:
    books_root = (tmp_path / "books").resolve()
    book = cash_book()
    result = close_session(books_root, book, session_date=date(2026, 11, 4))

    assert result.status == "deferred"
    assert result.marks == ()
    assert result.reason is not None
    assert "2026-11-04" in result.reason
    close_dir = books_root / ".close" / "2026-11-04"
    assert (close_dir / "status.json").is_file()
    assert not (close_dir / book.replica_id).exists()


def test_missing_symbol_close_defers_without_valuation(tmp_path: Path) -> None:
    books_root = (tmp_path / "books").resolve()
    book = positioned_book(symbol="QQQ")
    result = close_session(books_root, book, session_date=SESSION)

    assert result.status == "deferred"
    assert result.marks == ()
    assert result.reason == "missing_close:QQQ"
    assert not (books_root / ".close" / "2026-11-02" / book.replica_id).exists()
    write_book(books_root, book)
    assert (books_root / book.replica_id / "portfolio.json").is_file()
