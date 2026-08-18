"""Helpers for atomic candidate-publication fixtures."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from arena_kernel.schema.events import dump_ledger_event
from arena_kernel.schema.fills import dump_fills
from arena_kernel.schema.portfolio import dump_portfolio
from arena_runtime.audit import AuditArchive
from arena_runtime.orchestrator import publish_candidates
from tests.r20.conftest import make_result
from tests.r21.conftest import (
    HOLD_DECISION,
    SPY_BUY,
    cash_book,
    evaluate,
    evaluation_snapshot,
)

ET = ZoneInfo("America/New_York")
PUBLISHED_AT = datetime(2026, 8, 17, 10, 16, tzinfo=ET)
HOLD_B = HOLD_DECISION


def two_candidate_evaluation(root: Path):
    book_a = cash_book("product-a-1", product_id="product-a")
    book_b = cash_book("product-b-1", product_id="product-b")
    snapshot = evaluation_snapshot(book_a)
    result, collection = evaluate(
        root,
        (
            make_result(payload=SPY_BUY),
            make_result(
                product_id="product-b",
                replica_id="product-b-1",
                payload=HOLD_B,
            ),
        ),
        payloads={"product-a-1": SPY_BUY, "product-b-1": HOLD_B},
        books={"product-a-1": book_a, "product-b-1": book_b},
        snapshot=snapshot,
    )
    return result, collection, book_a, book_b, snapshot


def publish(root: Path, candidates, *, published_at=PUBLISHED_AT):
    books_root = (root / "books").resolve()
    archive = AuditArchive(root / "archive")
    publication = publish_candidates(
        candidates=candidates,
        books_root=books_root,
        archive=archive,
        published_at=published_at,
    )
    return publication, books_root, archive


def dumps_for(candidate) -> dict[str, str]:
    return {
        "portfolio": dump_portfolio(candidate.portfolio),
        "fills": dump_fills(candidate.fills),
        "events": "".join(dump_ledger_event(event) for event in candidate.events),
    }
