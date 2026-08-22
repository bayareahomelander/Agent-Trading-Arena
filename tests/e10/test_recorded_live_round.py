"""E10: one recorded live-shaped round through the operator glue."""

from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from arena_kernel.calendar import clock_for_round, parse_calendar, rounds_for_day
from arena_kernel.marketdata import CommonDataUnavailable
from arena_kernel.schema._dump import dump_json
from arena_kernel.schema.fills import FillsFile
from arena_kernel.schema.market import (
    Snapshot,
    parse_bar,
    parse_history,
    parse_snapshot,
)
from arena_kernel.schema.portfolio import Portfolio
from arena_kernel.workspace import (
    DAILY_FILE,
    INTRADAY_FILE,
    SNAPSHOT_FILE,
    write_replica_workspace,
)
from arena_runtime import cli
from arena_runtime.cli import EXIT_NOT_COMMITTED, EXIT_OK, EXIT_PAUSED, main
from arena_runtime.orchestrator import (
    mark_official_close,
    reconstruct_published_round,
    run_archived_baselines,
)
from arena_runtime.registration import runtime_registration_to_dict
from tests.r26.conftest import registration

_REPO = Path(__file__).resolve().parents[2]
_CALENDAR_PATH = _REPO / "fixtures" / "golden" / "calendar" / "calendar.json"
_FIXTURE_VENDOR = _REPO / "fixtures" / "golden" / "calendar" / "vendor"
_D13_TAPE = _REPO / "fixtures" / "golden" / "tape"
_SESSION = date(2026, 11, 2)
_DAILY_SESSIONS = (date(2026, 10, 29), date(2026, 10, 30))
_PRODUCTS = (
    ("product-a", ("product-a-1", "product-a-2")),
    ("product-b", ("product-b-1", "product-b-2")),
)


def _bar(symbol: str, bar_start: str, price: str) -> dict[str, str]:
    return {
        "symbol": symbol,
        "bar_start": bar_start,
        "open": price,
        "high": price,
        "low": price,
        "close": price,
        "volume": "1000",
        "vwap": price,
    }


_RECORDS = tuple(
    record
    for symbol, prices in (
        ("AAA", ("8.00", "8.50", "9.00", "10.00")),
        ("SPY", ("98.00", "98.50", "99.00", "100.00")),
    )
    for record in (
        _bar(symbol, "2026-10-29T00:00:00-04:00", prices[0]),
        _bar(symbol, "2026-10-30T00:00:00-04:00", prices[1]),
        _bar(symbol, "2026-11-02T09:58:00-05:00", prices[2]),
        _bar(symbol, "2026-11-02T09:59:00-05:00", prices[2]),
        _bar(symbol, "2026-11-02T10:16:00-05:00", prices[3]),
    )
)


class _RecordedVendor:
    def __init__(
        self,
        *,
        available: bool = True,
        fill_available: bool = True,
    ) -> None:
        self.available = available
        self.fill_available = fill_available
        self.calls: list[tuple[tuple[str, ...], object, object]] = []
        self.raw_archive: list[tuple[str, bytes, str]] = []

    def minute_bars(self, symbols, start, end):
        if not self.available:
            raise CommonDataUnavailable("recorded", "missing")
        if not self.fill_available and start.hour == 10 and start.minute == 16:
            raise CommonDataUnavailable("fill", "missing")
        wanted = set(symbols)
        rows = tuple(
            item
            for item in _RECORDS
            if item["symbol"] in wanted and start <= parse_bar(item).bar_start <= end
        )
        self.calls.append((tuple(symbols), start, end))
        raw = dump_json({"bars": [dict(item) for item in rows]}).encode("utf-8")
        self.raw_archive.append(
            (
                f"recorded://request/{len(self.raw_archive)}",
                raw,
                hashlib.sha256(raw).hexdigest(),
            )
        )
        return rows

    def official_closes(self, session_date):
        assert session_date == _SESSION
        return {"AAA": Decimal("11.00"), "SPY": Decimal("101.00")}


def _book(product_id: str, replica_id: str) -> Portfolio:
    return Portfolio(
        schema_version="1",
        replica_id=replica_id,
        product_id=product_id,
        cash=Decimal("1000.00"),
        positions=(),
        reported_equity=None,
    )


def _decision(round_id: str, replica_id: str) -> str:
    trade = replica_id == "product-a-1"
    return json.dumps(
        {
            "round_id": round_id,
            "action": "trade" if trade else "hold",
            "orders": (
                [
                    {
                        "priority": 1,
                        "symbol": "AAA",
                        "side": "buy",
                        "notional_usd": "100.00",
                    }
                ]
                if trade
                else []
            ),
            "thesis": "recorded E10",
            "confidence": 0.5,
            "risk_note": "recorded E10",
            "invalidation": "recorded E10",
            "intended_horizon": "recorded E10",
        },
        separators=(",", ":"),
    )


def _write_spec(root: Path) -> tuple[Path, object]:
    calendar = parse_calendar(_CALENDAR_PATH.read_text(encoding="utf-8"))
    scheduled = rounds_for_day(calendar, _SESSION)[0]
    season = (root / "season").resolve()
    start_bars = tuple(
        parse_bar(item)
        for item in _RECORDS
        if item["bar_start"] == "2026-11-02T09:59:00-05:00"
    )
    clock = clock_for_round(scheduled, exchange_timestamp=scheduled.start)
    books = [
        _book(product_id, replica_id)
        for product_id, replica_ids in _PRODUCTS
        for replica_id in replica_ids
    ]
    for book in books:
        write_replica_workspace(
            season / "replicas" / book.replica_id,
            rules_md="# frozen E10 rules\n",
            prompt_md="frozen E10 prompt\n",
            clock=clock,
            portfolio=book,
            fills=FillsFile(schema_version="1", fills=()),
            snapshot=Snapshot(
                schema_version="1",
                clock=clock,
                bars=start_bars,
                portfolio=book,
            ),
        )
    duties = [
        {
            "product_id": product_id,
            "replica_id": replica_id,
            "status": "active",
        }
        for product_id, replica_ids in _PRODUCTS
        for replica_id in replica_ids
    ]
    requests = [
        {
            "product_id": product_id,
            "replica_id": replica_id,
            "round_id": scheduled.round_id,
            "workspace": str((season / "replicas" / replica_id).resolve()),
            "deadline": scheduled.deadline.isoformat(),
        }
        for product_id, replica_ids in _PRODUCTS
        for replica_id in replica_ids
    ]
    scripts = [
        {
            "product_id": product_id,
            "replica_id": replica_id,
            "round_id": scheduled.round_id,
            "preflight_started_at": (
                scheduled.start - timedelta(minutes=2)
            ).isoformat(),
            "preflight_finished_at": (
                scheduled.start - timedelta(minutes=1)
            ).isoformat(),
            "run_started_at": scheduled.start.isoformat(),
            "run_finished_at": (scheduled.start + timedelta(minutes=5)).isoformat(),
            "outcome": "completed",
            "exit_status": 0,
            "decision_text": _decision(scheduled.round_id, replica_id),
        }
        for product_id, replica_ids in _PRODUCTS
        for replica_id in replica_ids
    ]
    payload = {
        "live_round": True,
        "wait": False,
        "archive": str((root / "archive").resolve()),
        "books_root": str((root / "books").resolve()),
        "staging_root": str((root / "staging").resolve()),
        "season_root": str(season),
        "workspaces": {
            book.replica_id: str((season / "replicas" / book.replica_id).resolve())
            for book in books
        },
        "calendar": str(_CALENDAR_PATH.resolve()),
        "universe": ["AAA", "SPY"],
        "vendor": {"kind": "fixture", "root": str(_FIXTURE_VENDOR.resolve())},
        "registrations": [
            runtime_registration_to_dict(registration(product_id, replica_ids))
            for product_id, replica_ids in _PRODUCTS
        ],
        "duties": duties,
        "adapters": {product_id: "fake" for product_id, _ids in _PRODUCTS},
        "round_id": scheduled.round_id,
        "requests": requests,
        "books": {
            book.replica_id: str(
                (
                    season / "replicas" / book.replica_id / "state/portfolio.json"
                ).resolve()
            )
            for book in books
        },
        "fake_scripts": scripts,
        "session_open": "2026-11-02T09:30:00-05:00",
        "daily_sessions": [day.isoformat() for day in _DAILY_SESSIONS],
        "now": scheduled.start.isoformat(),
        "decided_at": scheduled.start.isoformat(),
        "published_at": scheduled.reference_minute.isoformat(),
    }
    path = root / "live-round.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path, scheduled


def _artifacts(root: Path, vendor: _RecordedVendor, scheduled) -> dict[str, object]:
    books_root = (root / "books").resolve()
    close = mark_official_close(
        books_root=books_root,
        vendor=vendor,
        session_date=_SESSION,
        replica_ids=tuple(
            replica_id
            for _product_id, replica_ids in _PRODUCTS
            for replica_id in replica_ids
        ),
        marked_at=scheduled.start.replace(hour=16),
    )
    baselines = run_archived_baselines(tape_dir=_D13_TAPE, books_root=books_root)
    raw = root / "season" / "raw" / f"{scheduled.round_id}.bin"
    digest = root / "season" / "raw" / f"{scheduled.round_id}.sha256"
    fill_bars = root / "season" / "rounds" / scheduled.round_id / "fill-bars.json"
    return {
        "books": reconstruct_published_round(books_root, scheduled.round_id),
        "nlvs": {mark.replica_id: str(mark.nlv) for mark in close.marks},
        "raw": raw.read_bytes(),
        "raw_digest": digest.read_text(encoding="ascii"),
        "fill_bars": fill_bars.read_bytes(),
        "baselines": baselines,
    }


def test_recorded_live_round_is_deterministic_and_fills_at_reference_minute(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    vendors = [_RecordedVendor(), _RecordedVendor()]
    constructed_vendors: list[_RecordedVendor] = []
    constructed_runners: list[object] = []
    original_runners = cli._construct_runners

    def construct_vendor(_operator):
        vendor = vendors[len(constructed_vendors)]
        constructed_vendors.append(vendor)
        return vendor

    def construct_runners(*args, **kwargs):
        runners = original_runners(*args, **kwargs)
        constructed_runners.append(runners)
        return runners

    monkeypatch.setattr(cli, "_construct_vendor", construct_vendor)
    monkeypatch.setattr(cli, "_construct_runners", construct_runners)

    results = []
    for index in (1, 2):
        root = tmp_path / f"run-{index}"
        spec, scheduled = _write_spec(root)
        assert main(["run-round", "--spec", str(spec)]) == EXIT_OK
        assert capsys.readouterr().out.strip() == "committed"
        results.append(_artifacts(root, vendors[index - 1], scheduled))

        workspaces = [
            root / "season" / "replicas" / replica_id
            for _product_id, replica_ids in _PRODUCTS
            for replica_id in replica_ids
        ]
        snapshots = [
            parse_snapshot((workspace / SNAPSHOT_FILE).read_text(encoding="utf-8"))
            for workspace in workspaces
        ]
        assert {bar.vwap for bar in snapshots[0].bars} == {
            Decimal("9.00"),
            Decimal("99.00"),
        }
        for relative in (INTRADAY_FILE, DAILY_FILE):
            copies = [(workspace / relative).read_bytes() for workspace in workspaces]
            assert len(set(copies)) == 1
            assert parse_history(copies[0])

        fill_payload = json.loads(results[-1]["fill_bars"])["bars"]
        assert {item["vwap"] for item in fill_payload} == {"10.00", "100.00"}
        events = (root / "books" / "product-a-1" / "events.jsonl").read_text(
            encoding="utf-8"
        )
        assert '"type": "order_filled"' in events
        assert '"fill_price": "10.0050"' in events
        assert '"bar_start": "2026-11-02T10:16:00-05:00"' in events
        assert (
            hashlib.sha256(results[-1]["raw"]).hexdigest() + "\n"
            == results[-1]["raw_digest"]
        )

    assert len(constructed_vendors) == len(constructed_runners) == 2
    assert results[0] == results[1]
    assert results[0]["raw"]


def test_common_data_failure_pauses_before_decision_barrier(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    spec, scheduled = _write_spec(tmp_path)
    monkeypatch.setattr(
        cli, "_construct_vendor", lambda _operator: _RecordedVendor(available=False)
    )
    monkeypatch.setattr(
        cli,
        "run_decision_barrier",
        lambda **_kwargs: pytest.fail("decision barrier was called"),
    )

    assert main(["run-round", "--spec", str(spec)]) == EXIT_PAUSED
    assert capsys.readouterr().out.strip() == "paused"
    assert not (tmp_path / "season" / "rounds" / scheduled.round_id).exists()
    events = (tmp_path / "archive" / "normalized" / "events.jsonl").read_text(
        encoding="utf-8"
    )
    assert '"type":"pause"' in events


def test_missing_common_fill_data_voids_without_publishing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    spec, scheduled = _write_spec(tmp_path)
    monkeypatch.setattr(
        cli,
        "_construct_vendor",
        lambda _operator: _RecordedVendor(fill_available=False),
    )

    assert main(["run-round", "--spec", str(spec)]) == EXIT_NOT_COMMITTED
    assert capsys.readouterr().out.strip() == "not_committed"
    assert not (tmp_path / "books" / ".committed" / scheduled.round_id).exists()
    fill_bars = tmp_path / "season" / "rounds" / scheduled.round_id / "fill-bars.json"
    assert json.loads(fill_bars.read_text(encoding="utf-8")) == {"bars": []}
