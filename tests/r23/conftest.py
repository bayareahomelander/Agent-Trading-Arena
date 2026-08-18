"""Helpers for official-close mark fixtures."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from arena_kernel.marketdata import FixtureVendor
from arena_kernel.schema.portfolio import dump_portfolio
from arena_kernel.schema.portfolio import Position
from arena_runtime.orchestrator import AUTHORITATIVE_PORTFOLIO, mark_official_close
from tests.r21.conftest import cash_book

ET = ZoneInfo("America/New_York")
SESSION = date(2026, 11, 2)
MARKED_AT = datetime(2026, 11, 2, 16, 0, tzinfo=ET)
VENDOR_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "golden" / "calendar" / "vendor"


def write_book(books_root: Path, book) -> Path:
    dest = books_root / book.replica_id
    dest.mkdir(parents=True, exist_ok=True)
    (dest / AUTHORITATIVE_PORTFOLIO).write_text(
        dump_portfolio(book),
        encoding="utf-8",
        newline="\n",
    )
    return dest


def fixture_vendor() -> FixtureVendor:
    return FixtureVendor(VENDOR_DIR)


def positioned_book(replica_id: str = "product-a-1", symbol: str = "SPY"):
    return cash_book(replica_id).__class__(
        schema_version="1",
        replica_id=replica_id,
        product_id="product-a" if replica_id.startswith("product-a") else "product-b",
        cash=Decimal("500.00"),
        positions=(
            Position(
                symbol=symbol,
                quantity=Decimal("1.000"),
                cost_basis=Decimal("100.0000"),
            ),
        ),
        reported_equity=None,
    )


def close_session(books_root: Path, *books, session_date: date = SESSION):
    for book in books:
        write_book(books_root, book)
    return mark_official_close(
        books_root=books_root,
        vendor=fixture_vendor(),
        session_date=session_date,
        replica_ids=tuple(book.replica_id for book in books),
        marked_at=MARKED_AT,
    )
