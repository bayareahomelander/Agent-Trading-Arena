"""C8: calendar + fixture vendor emit a tape the kernel can parse."""

import hashlib
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from arena_kernel.calendar import parse_calendar
from arena_kernel.marketdata import (
    TAPE_BARS_FILE,
    TAPE_CLOCK_FILE,
    TAPE_RAW_DIR,
    TAPE_ROUNDS_DIR,
    CommonDataUnavailable,
    FixtureVendor,
    build_tape,
)
from arena_kernel.replay import replay_tape
from arena_kernel.schema._parse import load_json_object
from arena_kernel.schema.clock import parse_clock
from arena_kernel.schema.market import parse_bar
from arena_kernel.schema.portfolio import Portfolio
from arena_kernel.types import format_et_timestamp

_REPO = Path(__file__).resolve().parents[2]
CALENDAR_PATH = _REPO / "fixtures" / "golden" / "calendar" / "calendar.json"
VENDOR_DIR = _REPO / "fixtures" / "golden" / "calendar" / "vendor"
D13_RESULT = _REPO / "fixtures" / "golden" / "tape" / "expected" / "result.json"
D13_BASELINES = _REPO / "fixtures" / "golden" / "tape" / "expected" / "baselines.json"
REGULAR = date(2026, 11, 2)
HOLIDAY = date(2026, 11, 4)
RULES = "# Frozen rules\n"
PROMPT = "Treat terminal simulated wealth as the thing you are accountable for.\n"


def _calendar():
    return parse_calendar(CALENDAR_PATH.read_text(encoding="utf-8"))


def _vendor() -> FixtureVendor:
    return FixtureVendor(VENDOR_DIR)


def _starter() -> Portfolio:
    return Portfolio(
        schema_version="1",
        replica_id="product-c-1",
        product_id="product-c",
        cash=Decimal("1000.00"),
        positions=(),
        reported_equity=None,
    )


def _build(root: Path, *, dates: tuple[date, ...] = (REGULAR,)):
    return build_tape(
        root,
        _calendar(),
        _vendor(),
        ("SPY", "AAA"),
        dates,
        _starter(),
        rules_md=RULES,
        prompt_md=PROMPT,
    )


def test_one_day_regular_tape_has_morning_and_late(tmp_path: Path) -> None:
    tape = _build(tmp_path / "tape")
    rounds = json.loads((tape / "rounds.json").read_text(encoding="utf-8"))
    assert rounds == ["2026-11-02-morning", "2026-11-02-late"]


def test_built_clock_bars_and_close_parse(tmp_path: Path) -> None:
    tape = _build(tmp_path / "tape")
    morning = parse_clock(
        (tape / TAPE_ROUNDS_DIR / "2026-11-02-morning" / TAPE_CLOCK_FILE).read_text(
            encoding="utf-8"
        )
    )
    late = parse_clock(
        (tape / TAPE_ROUNDS_DIR / "2026-11-02-late" / TAPE_CLOCK_FILE).read_text(
            encoding="utf-8"
        )
    )
    morning_bars = load_json_object(
        (tape / TAPE_ROUNDS_DIR / "2026-11-02-morning" / TAPE_BARS_FILE).read_text(
            encoding="utf-8"
        )
    )
    bars = tuple(parse_bar(item) for item in morning_bars["bars"])
    close = load_json_object((tape / "close.json").read_text(encoding="utf-8"))
    assert format_et_timestamp(morning.round_start) == "2026-11-02T10:00:00-05:00"
    assert format_et_timestamp(morning.deadline) == "2026-11-02T10:15:00-05:00"
    assert format_et_timestamp(late.round_start) == "2026-11-02T15:30:00-05:00"
    assert [bar.symbol for bar in bars] == ["AAA", "SPY"]
    assert all(bar.eligible for bar in bars)
    assert close["timestamp"] == "2026-11-02T16:00:00-05:00"
    assert close["prices"]["AAA"] == "10.50"
    assert close["prices"]["SPY"] == "112.00"


def test_second_build_is_byte_stable_for_clock_and_bars(tmp_path: Path) -> None:
    first = _build(tmp_path / "a")
    second = _build(tmp_path / "b")
    for round_id in ("2026-11-02-morning", "2026-11-02-late"):
        for name in (TAPE_CLOCK_FILE, TAPE_BARS_FILE):
            left = (first / TAPE_ROUNDS_DIR / round_id / name).read_bytes()
            right = (second / TAPE_ROUNDS_DIR / round_id / name).read_bytes()
            assert left == right
            assert left.endswith(b"\n")


def test_replay_tape_applies_hold_decisions(tmp_path: Path) -> None:
    tape = _build(tmp_path / "tape")
    result = replay_tape(tape, tmp_path / "work")
    assert result.nlv_by_replica["product-c-1"] == Decimal("1000.00")
    assert result.median == Decimal("1000.00")


def test_holiday_in_session_dates_emits_no_extra_rounds(tmp_path: Path) -> None:
    tape = _build(tmp_path / "tape", dates=(REGULAR, HOLIDAY))
    rounds = json.loads((tape / "rounds.json").read_text(encoding="utf-8"))
    assert rounds == ["2026-11-02-morning", "2026-11-02-late"]


def test_holiday_only_session_dates_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no trading day"):
        _build(tmp_path / "tape", dates=(HOLIDAY,))


def test_empty_universe_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="universe"):
        build_tape(
            tmp_path / "tape",
            _calendar(),
            _vendor(),
            (),
            (REGULAR,),
            _starter(),
            rules_md=RULES,
            prompt_md=PROMPT,
        )


def test_missing_universe_symbol_raises_common_data_unavailable(
    tmp_path: Path,
) -> None:
    with pytest.raises(CommonDataUnavailable) as exc:
        build_tape(
            tmp_path / "tape",
            _calendar(),
            _vendor(),
            ("AAA", "QQQ"),
            (REGULAR,),
            _starter(),
            rules_md=RULES,
            prompt_md=PROMPT,
        )
    assert exc.value.path == "QQQ"


def test_rules_and_prompt_are_caller_text(tmp_path: Path) -> None:
    tape = _build(tmp_path / "tape")
    assert (tape / "RULES.md").read_text(encoding="utf-8") == RULES
    assert (tape / "PROMPT.md").read_text(encoding="utf-8") == PROMPT


def test_raw_archive_is_written_per_round(tmp_path: Path) -> None:
    tape = _build(tmp_path / "tape")
    for round_id in ("2026-11-02-morning", "2026-11-02-late"):
        blob = tape / TAPE_RAW_DIR / f"{round_id}.bin"
        digest = tape / TAPE_RAW_DIR / f"{round_id}.sha256"
        assert blob.is_file()
        assert digest.is_file()
        assert digest.read_text(encoding="ascii").strip() == hashlib.sha256(
            blob.read_bytes()
        ).hexdigest()


def test_build_tape_does_not_touch_d13_or_b7_goldens(tmp_path: Path) -> None:
    before_result = D13_RESULT.read_bytes()
    before_baselines = D13_BASELINES.read_bytes()
    _build(tmp_path / "tape")
    assert D13_RESULT.read_bytes() == before_result
    assert D13_BASELINES.read_bytes() == before_baselines
