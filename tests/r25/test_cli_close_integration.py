"""R25: close delegates to the existing official-close operation."""

import json
from pathlib import Path

from arena_runtime.cli import EXIT_DEFERRED, EXIT_OK, main
from tests.r23.conftest import SESSION, VENDOR_DIR, positioned_book, write_book
from tests.r21.conftest import cash_book


def test_close_command_marks_published_books(tmp_path: Path, capsys) -> None:
    books_root = (tmp_path / "books").resolve()
    write_book(books_root, cash_book())
    spec = tmp_path / "close.json"
    spec.write_text(
        json.dumps(
            {
                "books_root": str(books_root),
                "vendor": str(VENDOR_DIR),
                "session_date": SESSION.isoformat(),
                "replica_ids": ["product-a-1"],
                "marked_at": "2026-11-02T16:00:00-05:00",
            }
        ),
        encoding="utf-8",
    )

    assert main(["close", "--spec", str(spec)]) == EXIT_OK
    assert capsys.readouterr().out.strip() == "marked"
    assert (books_root / ".close" / "2026-11-02" / "status.json").is_file()


def test_close_command_defers_missing_date(tmp_path: Path, capsys) -> None:
    books_root = (tmp_path / "books").resolve()
    write_book(books_root, positioned_book())
    spec = tmp_path / "close.json"
    spec.write_text(
        json.dumps(
            {
                "books_root": str(books_root),
                "vendor": str(VENDOR_DIR),
                "session_date": "2026-11-04",
                "replica_ids": ["product-a-1"],
                "marked_at": "2026-11-04T16:00:00-05:00",
            }
        ),
        encoding="utf-8",
    )

    assert main(["close", "--spec", str(spec)]) == EXIT_DEFERRED
    assert capsys.readouterr().out.strip() == "deferred"
