"""E9: wait once for the C3 scheduled round start."""

from __future__ import annotations

import inspect
import json
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from arena_kernel.calendar import parse_calendar, rounds_for_day
from arena_kernel.marketdata import (
    FixtureVendor,
    bars_at_reference,
    last_complete_minute,
    publish_round,
)
from arena_kernel.schema.portfolio import Portfolio
from arena_kernel.types import parse_et_timestamp
from arena_runtime import cli
from arena_runtime.cli import EXIT_OK, EXIT_USAGE, cmd_preflight, main
from arena_runtime.orchestrator import published_snapshot_checksum
from arena_runtime.wait import MAX_SLEEP_SECONDS, wait_until

_REPO = Path(__file__).resolve().parents[2]
_CALENDAR = _REPO / "fixtures" / "golden" / "calendar" / "calendar.json"
_VENDOR = _REPO / "fixtures" / "golden" / "calendar" / "vendor"
_OMIT = object()


def _book() -> Portfolio:
    return Portfolio(
        schema_version="1",
        replica_id="product-a-1",
        product_id="product-a",
        cash=Decimal("1000.00"),
        positions=(),
        reported_equity=None,
    )


def _run_spec(
    tmp_path: Path,
    *,
    day: date = date(2026, 11, 2),
    kind: str = "morning",
    wait: object = _OMIT,
) -> tuple[Path, object]:
    calendar = parse_calendar(_CALENDAR.read_text(encoding="utf-8"))
    scheduled = next(
        item for item in rounds_for_day(calendar, day) if item.kind == kind
    )
    season = (tmp_path / "season").resolve()
    book = _book()
    bars = bars_at_reference(
        FixtureVendor(_VENDOR),
        ("AAA",),
        last_complete_minute(scheduled.start),
    )
    publish_round(
        season,
        scheduled=scheduled,
        bars=bars,
        portfolios=(book,),
        raw_vendor_bytes=b"{}",
    )
    workspace = season / "replicas" / book.replica_id
    decision = json.dumps(
        {
            "round_id": scheduled.round_id,
            "action": "hold",
            "orders": [],
            "thesis": "e9",
            "confidence": 0.5,
            "risk_note": "e9",
            "invalidation": "e9",
            "intended_horizon": "e9",
        }
    )
    payload: dict[str, object] = {
        "archive": str((tmp_path / "archive").resolve()),
        "books_root": str((tmp_path / "books").resolve()),
        "staging_root": str((tmp_path / "staging").resolve()),
        "calendar": str(_CALENDAR.resolve()),
        "round_id": scheduled.round_id,
        "snapshot": str((workspace / "state/market/snapshot.json").resolve()),
        "requests": [
            {
                "product_id": "product-a",
                "replica_id": book.replica_id,
                "round_id": scheduled.round_id,
                "workspace": str(workspace.resolve()),
                "deadline": scheduled.deadline.isoformat(),
            }
        ],
        "books": {book.replica_id: str((workspace / "state/portfolio.json").resolve())},
        "fake_scripts": [
            {
                "product_id": "product-a",
                "replica_id": book.replica_id,
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
                "decision_text": decision,
            }
        ],
        "product_ids": ["product-a"],
        "preflight": {
            "round_id": scheduled.round_id,
            "ready": True,
            "reason_codes": [],
            "due_replica_ids": [book.replica_id],
            "preflight_results": [
                {
                    "product_id": "product-a",
                    "replica_id": book.replica_id,
                    "round_id": scheduled.round_id,
                    "ready": True,
                    "started_at": (scheduled.start - timedelta(minutes=2)).isoformat(),
                    "finished_at": (scheduled.start - timedelta(minutes=1)).isoformat(),
                }
            ],
        },
        "snapshot_checksum": published_snapshot_checksum(workspace),
        "common_data_status": "available",
        "published_at": scheduled.reference_minute.isoformat(),
    }
    if wait is not _OMIT:
        payload["wait"] = wait
    path = tmp_path / "run.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path, scheduled


@pytest.mark.parametrize("offset", (0, 1))
def test_at_or_after_target_returns_without_sleep(offset: int) -> None:
    target = parse_et_timestamp("2026-11-02T10:00:00-05:00")
    calls: list[float] = []

    wait_until(
        target,
        clock=lambda: target + timedelta(seconds=offset),
        sleep=calls.append,
    )

    assert calls == []


def test_two_seconds_before_target_sleeps_in_bounded_intervals() -> None:
    target = parse_et_timestamp("2026-11-02T10:00:00-05:00")
    now = target - timedelta(seconds=2)
    calls: list[float] = []

    def advance(seconds: float) -> None:
        nonlocal now
        calls.append(seconds)
        now += timedelta(seconds=seconds)

    wait_until(target, clock=lambda: now, sleep=advance)

    assert calls == [MAX_SLEEP_SECONDS, MAX_SLEEP_SECONDS]


def test_naive_target_or_clock_is_rejected() -> None:
    aware = parse_et_timestamp("2026-11-02T10:00:00-05:00")

    with pytest.raises(ValueError, match="target"):
        wait_until(
            aware.replace(tzinfo=None), clock=lambda: aware, sleep=lambda _s: None
        )
    with pytest.raises(ValueError, match="clock"):
        wait_until(
            aware, clock=lambda: aware.replace(tzinfo=None), sleep=lambda _s: None
        )


def test_backward_clock_never_creates_negative_sleep() -> None:
    target = parse_et_timestamp("2026-11-02T10:00:00-05:00")
    moments = iter(
        (
            target - timedelta(seconds=2),
            target - timedelta(seconds=3),
            target,
        )
    )
    calls: list[float] = []

    wait_until(target, clock=lambda: next(moments), sleep=calls.append)

    assert calls == [MAX_SLEEP_SECONDS, MAX_SLEEP_SECONDS]
    assert all(0 < seconds <= MAX_SLEEP_SECONDS for seconds in calls)


def test_run_round_wait_false_bypasses_wait_and_commits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    spec, _scheduled = _run_spec(tmp_path, wait=False)
    monkeypatch.setattr(
        cli,
        "wait_until",
        lambda _target: pytest.fail("wait_until was called"),
    )

    assert main(["run-round", "--spec", str(spec)]) == EXIT_OK
    assert capsys.readouterr().out.strip() == "committed"


def test_run_round_waits_for_c3_start_before_decision_barrier(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    spec, scheduled = _run_spec(tmp_path, day=date(2026, 11, 3), kind="late")
    calls: list[tuple[str, object]] = []
    original_barrier = cli.run_decision_barrier

    monkeypatch.setattr(
        cli,
        "wait_until",
        lambda target: calls.append(("wait", target)),
    )

    def traced_barrier(**kwargs: object) -> object:
        calls.append(("barrier", None))
        return original_barrier(**kwargs)

    monkeypatch.setattr(cli, "run_decision_barrier", traced_barrier)

    assert main(["run-round", "--spec", str(spec)]) == EXIT_OK
    assert capsys.readouterr().out.strip() == "committed"
    assert calls == [("wait", scheduled.start), ("barrier", None)]
    assert scheduled.start.hour == 12 and scheduled.start.minute == 30


def test_non_boolean_wait_is_usage_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    spec, _scheduled = _run_spec(tmp_path, wait="false")
    monkeypatch.setattr(
        cli,
        "wait_until",
        lambda _target: pytest.fail("wait_until was called"),
    )

    assert main(["run-round", "--spec", str(spec)]) == EXIT_USAGE
    assert "wait must be a boolean" in capsys.readouterr().err


def test_preflight_does_not_wait() -> None:
    assert "wait_until" not in inspect.getsource(cmd_preflight)
