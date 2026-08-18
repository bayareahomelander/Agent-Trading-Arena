"""C7: publish one round. Same bars, different books, checksummed raw bytes."""

import hashlib
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from arena_kernel.calendar import parse_calendar, rounds_for_day
from arena_kernel.marketdata import (
    TAPE_BARS_FILE,
    TAPE_CLOCK_FILE,
    TAPE_RAW_DIR,
    TAPE_REPLICAS_DIR,
    TAPE_ROUNDS_DIR,
    FixtureVendor,
    bars_at_reference,
    publish_round,
)
from arena_kernel.schema._dump import dump_json
from arena_kernel.schema._parse import load_json_object
from arena_kernel.schema.clock import parse_clock
from arena_kernel.schema.market import parse_bar, parse_snapshot
from arena_kernel.schema.portfolio import Portfolio, dump_portfolio, parse_portfolio
from arena_kernel.workspace import PORTFOLIO_FILE, SNAPSHOT_FILE

_REPO = Path(__file__).resolve().parents[2]
CALENDAR_PATH = _REPO / "fixtures" / "golden" / "calendar" / "calendar.json"
VENDOR_DIR = _REPO / "fixtures" / "golden" / "calendar" / "vendor"
REGULAR = date(2026, 11, 2)
RAW = b'{"vendor":"fixture","note":"c7-raw"}'


def _morning():
    calendar = parse_calendar(CALENDAR_PATH.read_text(encoding="utf-8"))
    morning, _late = rounds_for_day(calendar, REGULAR)
    return morning


def _bars():
    return bars_at_reference(
        FixtureVendor(VENDOR_DIR),
        ("SPY", "AAA"),
        _morning().reference_minute,
    )


def _book(replica_id: str, cash: str) -> Portfolio:
    return Portfolio(
        schema_version="1",
        replica_id=replica_id,
        product_id="product-a",
        cash=Decimal(cash),
        positions=(),
        reported_equity=None,
    )


def _publish(root: Path, portfolios: tuple[Portfolio, ...]):
    publish_round(
        root,
        scheduled=_morning(),
        bars=_bars(),
        portfolios=portfolios,
        raw_vendor_bytes=RAW,
        rules_md="# rules\n",
        prompt_md="prompt\n",
    )


def test_two_replicas_one_round_reparses_clock_bars_and_portfolios(
    tmp_path: Path,
) -> None:
    book_a = _book("product-a-1", "1000.00")
    book_b = _book("product-a-2", "500.00")
    _publish(tmp_path, (book_a, book_b))
    morning = _morning()
    round_dir = tmp_path / TAPE_ROUNDS_DIR / morning.round_id
    clock = parse_clock((round_dir / TAPE_CLOCK_FILE).read_text(encoding="utf-8"))
    payload = load_json_object((round_dir / TAPE_BARS_FILE).read_text(encoding="utf-8"))
    bars = tuple(parse_bar(item) for item in payload["bars"])
    parsed_a = parse_portfolio(
        (tmp_path / TAPE_REPLICAS_DIR / "product-a-1" / PORTFOLIO_FILE).read_text(
            encoding="utf-8"
        )
    )
    parsed_b = parse_portfolio(
        (tmp_path / TAPE_REPLICAS_DIR / "product-a-2" / PORTFOLIO_FILE).read_text(
            encoding="utf-8"
        )
    )
    assert clock.round_id == morning.round_id
    assert clock.deadline > clock.round_start
    assert [bar.symbol for bar in bars] == ["AAA", "SPY"]
    assert parsed_a.replica_id == "product-a-1"
    assert parsed_b.replica_id == "product-a-2"
    assert parsed_a.cash == Decimal("1000.00")
    assert parsed_b.cash == Decimal("500.00")


def test_snapshot_bars_are_byte_identical_across_replicas(tmp_path: Path) -> None:
    _publish(tmp_path, (_book("product-a-1", "1000.00"), _book("product-a-2", "500.00")))
    morning = _morning()
    texts = [
        (
            tmp_path / TAPE_REPLICAS_DIR / replica / SNAPSHOT_FILE
        ).read_text(encoding="utf-8")
        for replica in ("product-a-1", "product-a-2")
    ]
    dumped = [
        dump_json({"bars": json.loads(text)["bars"]}) for text in texts
    ]
    assert dumped[0] == dumped[1]
    for text in texts:
        snapshot = parse_snapshot(text)
        assert [bar.symbol for bar in snapshot.bars] == ["AAA", "SPY"]
        assert snapshot.clock.round_id == morning.round_id


def test_raw_archive_checksum_matches_sha256(tmp_path: Path) -> None:
    _publish(tmp_path, (_book("product-a-1", "1000.00"), _book("product-a-2", "500.00")))
    morning = _morning()
    blob = tmp_path / TAPE_RAW_DIR / f"{morning.round_id}.bin"
    digest = tmp_path / TAPE_RAW_DIR / f"{morning.round_id}.sha256"
    assert blob.read_bytes() == RAW
    assert digest.read_text(encoding="ascii").strip() == hashlib.sha256(RAW).hexdigest()


def test_input_portfolios_are_not_mutated(tmp_path: Path) -> None:
    book_a = _book("product-a-1", "1000.00")
    book_b = _book("product-a-2", "500.00")
    before = (dump_portfolio(book_a), dump_portfolio(book_b))
    _publish(tmp_path, (book_a, book_b))
    assert dump_portfolio(book_a) == before[0]
    assert dump_portfolio(book_b) == before[1]
    assert book_a.cash == Decimal("1000.00")
    assert book_b.positions == ()


def test_empty_portfolios_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="portfolios"):
        publish_round(
            tmp_path,
            scheduled=_morning(),
            bars=_bars(),
            portfolios=(),
            raw_vendor_bytes=RAW,
        )


def test_duplicate_replica_id_is_rejected(tmp_path: Path) -> None:
    book = _book("product-a-1", "1000.00")
    with pytest.raises(ValueError, match="duplicate replica_id"):
        publish_round(
            tmp_path,
            scheduled=_morning(),
            bars=_bars(),
            portfolios=(book, book),
            raw_vendor_bytes=RAW,
        )
