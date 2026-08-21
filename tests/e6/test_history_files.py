"""E6: common history files are sibling JSON, not Snapshot.bars."""

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from arena_kernel.calendar import parse_calendar, rounds_for_day
from arena_kernel.marketdata import (
    TAPE_RAW_DIR,
    CommonDataUnavailable,
    history_from_vendor,
    last_complete_minute,
    publish_round,
)
from arena_kernel.replay import replay_tape
from arena_kernel.schema.market import parse_bar, parse_history, parse_snapshot
from arena_kernel.schema.portfolio import Portfolio
from arena_kernel.types import parse_et_timestamp
from arena_kernel.workspace import DAILY_FILE, INTRADAY_FILE, SNAPSHOT_FILE

_REPO = Path(__file__).resolve().parents[2]
CALENDAR = _REPO / "fixtures" / "golden" / "calendar" / "calendar.json"
TAPE = _REPO / "fixtures" / "golden" / "tape"
SESSION = date(2026, 11, 2)
OPEN = parse_et_timestamp("2026-11-02T09:30:00-05:00")
DAILY_DAYS = (date(2026, 10, 29), date(2026, 10, 30))
RAW = b"https://vendor.example/v2/aggs?apiKey=SECRET"


def _ohlcv(symbol: str, bar_start: str, px: str) -> dict[str, str]:
    return {
        "symbol": symbol,
        "bar_start": bar_start,
        "open": px,
        "high": px,
        "low": px,
        "close": px,
        "volume": "1000",
        "vwap": px,
    }


_RECORDS = (
    _ohlcv("AAA", "2026-10-29T00:00:00-04:00", "8.00"),
    _ohlcv("AAA", "2026-10-30T00:00:00-04:00", "8.50"),
    _ohlcv("AAA", "2026-11-02T09:58:00-05:00", "8.90"),
    _ohlcv("AAA", "2026-11-02T09:59:00-05:00", "9.00"),
)


class _HistoryVendor:
    def __init__(self, records=_RECORDS) -> None:
        self._records = tuple(records)

    def minute_bars(self, symbols, start, end):
        wanted = set(symbols)
        out = []
        for item in self._records:
            if item["symbol"] not in wanted:
                continue
            bar_start = parse_et_timestamp(item["bar_start"])
            if start <= bar_start <= end:
                out.append(item)
        return tuple(out)

    def official_closes(self, session_date):
        return {"AAA": Decimal("10.50")}


def _morning():
    calendar = parse_calendar(CALENDAR.read_text(encoding="utf-8"))
    morning, _late = rounds_for_day(calendar, SESSION)
    return morning


def _book(replica_id: str) -> Portfolio:
    return Portfolio(
        schema_version="1",
        replica_id=replica_id,
        product_id="product-a",
        cash=Decimal("1000.00"),
        positions=(),
        reported_equity=None,
    )


def _history(vendor=None):
    scheduled = _morning()
    return history_from_vendor(
        vendor or _HistoryVendor(),
        ("AAA",),
        session_open=OPEN,
        through=last_complete_minute(scheduled.start),
        daily_sessions=DAILY_DAYS,
    )


def _publish(root: Path, *, vendor=None, daily=None, raw: bytes = RAW) -> None:
    scheduled = _morning()
    vendor = vendor or _HistoryVendor()
    intraday, fetched_daily = _history(vendor)
    if daily is None:
        daily = fetched_daily
    start_bars = (
        parse_bar(_ohlcv("AAA", "2026-11-02T09:59:00-05:00", "9.00")),
    )
    publish_round(
        root,
        scheduled=scheduled,
        bars=start_bars,
        portfolios=(_book("product-a-1"), _book("product-a-2")),
        raw_vendor_bytes=raw,
        rules_md="# rules\n",
        prompt_md="prompt\n",
        intraday=intraday,
        daily=daily,
    )


def test_two_replicas_get_byte_identical_history_files(tmp_path: Path) -> None:
    _publish(tmp_path)
    replicas = (
        tmp_path / "replicas" / "product-a-1",
        tmp_path / "replicas" / "product-a-2",
    )
    for relative in (INTRADAY_FILE, DAILY_FILE):
        left = (replicas[0] / relative).read_bytes()
        right = (replicas[1] / relative).read_bytes()
        assert left == right
        payload = parse_history(left)
        assert payload[0].symbol == "AAA"
        dumped = (replicas[0] / relative).read_text(encoding="utf-8")
        assert '"schema_version": "1"' in dumped
    intraday = parse_history((replicas[0] / INTRADAY_FILE).read_text(encoding="utf-8"))
    daily = parse_history((replicas[0] / DAILY_FILE).read_text(encoding="utf-8"))
    assert [bar.bar_start for bar in intraday] == [
        parse_et_timestamp("2026-11-02T09:58:00-05:00"),
        parse_et_timestamp("2026-11-02T09:59:00-05:00"),
    ]
    assert [bar.bar_start.date() for bar in daily] == list(DAILY_DAYS)


def test_snapshot_is_round_start_bars_not_history(tmp_path: Path) -> None:
    _publish(tmp_path)
    replica = tmp_path / "replicas" / "product-a-1"
    snapshot = parse_snapshot((replica / SNAPSHOT_FILE).read_text(encoding="utf-8"))
    assert [bar.bar_start for bar in snapshot.bars] == [
        parse_et_timestamp("2026-11-02T09:59:00-05:00")
    ]
    (replica / INTRADAY_FILE).unlink()
    (replica / DAILY_FILE).unlink()
    again = parse_snapshot((replica / SNAPSHOT_FILE).read_text(encoding="utf-8"))
    assert again.bars == snapshot.bars


def test_d13_tape_replays_without_history_files(tmp_path: Path) -> None:
    work = tmp_path / "work"
    replay_tape(TAPE, work)
    assert not (work / "product-a-1" / INTRADAY_FILE).exists()
    assert not (work / "product-a-1" / DAILY_FILE).exists()
    assert (work / "product-a-1" / SNAPSHOT_FILE).is_file()


def test_missing_daily_fetch_writes_no_replica_history(tmp_path: Path) -> None:
    vendor = _HistoryVendor(
        (
            _ohlcv("AAA", "2026-11-02T09:58:00-05:00", "8.90"),
            _ohlcv("AAA", "2026-11-02T09:59:00-05:00", "9.00"),
        )
    )
    with pytest.raises(CommonDataUnavailable) as exc:
        _history(vendor)
    assert exc.value.path == "2026-10-29"
    assert not (tmp_path / "replicas").exists()
    with pytest.raises(CommonDataUnavailable):
        _publish(tmp_path, vendor=vendor)
    assert not (tmp_path / "replicas").exists()
    assert not (tmp_path / "rounds").exists()


def test_empty_daily_does_not_write_partial_history(tmp_path: Path) -> None:
    with pytest.raises(CommonDataUnavailable) as exc:
        _publish(tmp_path, daily=())
    assert exc.value.path == "daily"
    assert not (tmp_path / "replicas").exists()
    assert not (tmp_path / "rounds").exists()


def test_history_json_has_no_vendor_url_or_key(tmp_path: Path) -> None:
    _publish(tmp_path)
    replica = tmp_path / "replicas" / "product-a-1"
    for relative in (INTRADAY_FILE, DAILY_FILE, SNAPSHOT_FILE):
        text = (replica / relative).read_bytes()
        assert b"http" not in text
        assert b"apiKey" not in text
        assert b"SECRET" not in text
    raw = tmp_path / TAPE_RAW_DIR / f"{_morning().round_id}.bin"
    assert raw.read_bytes() == RAW
    assert (tmp_path / TAPE_RAW_DIR / f"{_morning().round_id}.sha256").is_file()


def test_naive_session_open_is_rejected() -> None:
    with pytest.raises(ValueError, match="offset"):
        history_from_vendor(
            _HistoryVendor(),
            ("AAA",),
            session_open=datetime(2026, 11, 2, 9, 30),
            through=parse_et_timestamp("2026-11-02T09:59:00-05:00"),
            daily_sessions=DAILY_DAYS,
        )
