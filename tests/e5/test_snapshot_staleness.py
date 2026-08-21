"""E5: a round-start snapshot older than 60s is common data unavailable."""

from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from arena_kernel.calendar import parse_calendar, rounds_for_day
from arena_kernel.marketdata import (
    TAPE_CLOCK_FILE,
    TAPE_ROUNDS_DIR,
    CommonDataUnavailable,
    FixtureVendor,
    bars_at_reference,
    publish_round,
    require_fresh_snapshot,
)
from arena_kernel.schema.market import parse_bar
from arena_kernel.schema.portfolio import Portfolio
from arena_kernel.types import parse_et_timestamp
from arena_runtime.orchestrator import (
    COMMON_DATA_UNAVAILABLE,
    COMMON_DATA_UNAVAILABLE_REASON,
    OrchestratorError,
    run_decision_barrier,
)
from tests.r17.conftest import PRODUCT_A, PRODUCT_B, REPLICA_A1, REPLICA_B1, run_barrier, script_for

_REPO = Path(__file__).resolve().parents[2]
CALENDAR = _REPO / "fixtures" / "golden" / "calendar" / "calendar.json"
VENDOR_DIR = _REPO / "fixtures" / "golden" / "calendar" / "vendor"
BAR_START = parse_et_timestamp("2026-11-02T09:59:00-05:00")
NOW_59 = BAR_START + timedelta(seconds=59)
NOW_60 = BAR_START + timedelta(seconds=60)
NOW_61 = BAR_START + timedelta(seconds=61)
MISSING_FILL_MINUTE = parse_et_timestamp("2026-11-02T10:17:00-05:00")


def _eligible(*starts: str):
    out = []
    for index, start in enumerate(starts or ("2026-11-02T09:59:00-05:00",)):
        out.append(
            parse_bar(
                {
                    "symbol": "AAA" if index == 0 else "SPY",
                    "bar_start": start,
                    "open": "9.00",
                    "high": "9.00",
                    "low": "9.00",
                    "close": "9.00",
                    "volume": "1000",
                    "vwap": "9.00",
                }
            )
        )
    return tuple(out)


def _ineligible(bar_start: str = "2026-11-02T10:00:00-05:00"):
    return parse_bar(
        {
            "symbol": "HALT",
            "bar_start": bar_start,
            "eligible": False,
        }
    )


def _morning():
    calendar = parse_calendar(CALENDAR.read_text(encoding="utf-8"))
    morning, _late = rounds_for_day(calendar, date(2026, 11, 2))
    return morning


def _book() -> Portfolio:
    return Portfolio(
        schema_version="1",
        replica_id="product-a-1",
        product_id="product-a",
        cash=Decimal("1000.00"),
        positions=(),
        reported_equity=None,
    )


def _publish(root: Path, bars, now: datetime) -> None:
    publish_round(
        root,
        scheduled=_morning(),
        bars=bars,
        portfolios=(_book(),),
        raw_vendor_bytes=b"{}",
        now=now,
    )


def test_now_61s_after_newest_bar_is_unavailable() -> None:
    with pytest.raises(CommonDataUnavailable) as exc:
        require_fresh_snapshot(_eligible(), NOW_61)
    assert exc.value.path == "bar_start"
    assert exc.value.message == "stale"


def test_now_59s_after_newest_bar_proceeds() -> None:
    require_fresh_snapshot(_eligible(), NOW_59)


def test_now_60s_after_newest_bar_proceeds() -> None:
    require_fresh_snapshot(_eligible(), NOW_60)


def test_stale_publish_writes_no_tape(tmp_path: Path) -> None:
    with pytest.raises(CommonDataUnavailable) as exc:
        _publish(tmp_path, _eligible(), NOW_61)
    assert exc.value.path == "bar_start"
    assert not (tmp_path / TAPE_ROUNDS_DIR).exists()


def test_fresh_publish_writes_tape(tmp_path: Path) -> None:
    _publish(tmp_path, _eligible(), NOW_59)
    clock = tmp_path / TAPE_ROUNDS_DIR / _morning().round_id / TAPE_CLOCK_FILE
    assert clock.is_file()


def test_naive_now_is_rejected() -> None:
    with pytest.raises(ValueError, match="offset"):
        require_fresh_snapshot(_eligible(), datetime(2026, 11, 2, 10, 0, 1))


def test_no_eligible_bar_is_unavailable() -> None:
    with pytest.raises(CommonDataUnavailable) as exc:
        require_fresh_snapshot((_ineligible(),), NOW_59)
    assert exc.value.path == "bars"


def test_ineligible_bars_do_not_count_as_latest() -> None:
    bars = (*_eligible(), _ineligible("2026-11-02T10:00:00-05:00"))
    with pytest.raises(CommonDataUnavailable) as exc:
        require_fresh_snapshot(bars, NOW_61)
    assert exc.value.path == "bar_start"


def test_missing_fill_minute_is_still_c6_ineligible() -> None:
    (bar,) = bars_at_reference(
        FixtureVendor(VENDOR_DIR), ("AAA",), MISSING_FILL_MINUTE
    )
    assert bar.eligible is False
    assert bar.bar_start == MISSING_FILL_MINUTE


def test_stale_snapshot_pauses_and_does_not_launch(tmp_path: Path) -> None:
    with pytest.raises(CommonDataUnavailable):
        require_fresh_snapshot(_eligible(), NOW_61)
    preflight, _archive, runner = run_barrier(
        tmp_path,
        scripts=(
            script_for(PRODUCT_A, REPLICA_A1),
            script_for(PRODUCT_B, REPLICA_B1),
        ),
        common_data_status=COMMON_DATA_UNAVAILABLE,
    )
    assert preflight.ready is False
    assert COMMON_DATA_UNAVAILABLE_REASON in preflight.reason_codes
    with pytest.raises(OrchestratorError) as exc:
        run_decision_barrier(
            preflight=preflight,
            requests=(),
            runners={PRODUCT_A: runner, PRODUCT_B: runner},
            snapshot_checksum="a" * 64,
        )
    assert exc.value.path == "preflight"
    assert runner._completed_requests == set()  # noqa: SLF001
