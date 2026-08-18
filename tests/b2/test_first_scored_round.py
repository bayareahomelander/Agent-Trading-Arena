"""B2: first scored window is one function on tape order, not a calendar."""

import json
from pathlib import Path

import pytest

from arena_kernel.baselines import FirstWindowError, first_scored_round_id
from arena_kernel.schema.market import parse_bar
from arena_kernel.schema._parse import load_json_object

from .conftest import priced_bar, snapshot_for

_REPO = Path(__file__).resolve().parents[2]
TAPE = _REPO / "fixtures" / "golden" / "tape"
MORNING = "2026-08-17-morning"
LATE = "2026-08-17-late"


def _tape_round_ids() -> list[str]:
    return json.loads((TAPE / "rounds.json").read_text(encoding="utf-8"))


def _tape_bars() -> dict[str, tuple]:
    bars: dict[str, tuple] = {}
    for round_id in _tape_round_ids():
        payload = load_json_object(
            (TAPE / "rounds" / round_id / "bars.json").read_text(encoding="utf-8")
        )
        bars[round_id] = tuple(parse_bar(item) for item in payload["bars"])
    return bars


def test_d13_tape_first_scored_window_is_morning() -> None:
    assert first_scored_round_id(_tape_round_ids(), _tape_bars()) == MORNING


def test_empty_required_symbols_takes_first_listed_round() -> None:
    assert first_scored_round_id((LATE, MORNING), {}, required_symbols=()) == LATE


def test_empty_rounds_json_is_an_error_with_path_and_message(tmp_path: Path) -> None:
    rounds_file = tmp_path / "rounds.json"
    rounds_file.write_text("[]\n", encoding="utf-8")
    round_ids = json.loads(rounds_file.read_text(encoding="utf-8"))
    with pytest.raises(FirstWindowError) as exc:
        first_scored_round_id(round_ids, {})
    assert exc.value.path == "rounds.json"
    assert "at least one round" in exc.value.message
    assert str(exc.value).startswith("rounds.json:")


def test_first_scored_window_follows_rounds_json_order_not_clock() -> None:
    bars = {
        LATE: (priced_bar("SPY"), priced_bar("AAA")),
        MORNING: (priced_bar("SPY"), priced_bar("AAA")),
    }
    assert first_scored_round_id((LATE, MORNING), bars) == LATE


def test_first_scored_window_skips_round_missing_required_eligible_bar() -> None:
    bars = {
        MORNING: (priced_bar("SPY", eligible=False), priced_bar("AAA")),
        LATE: (priced_bar("SPY"), priced_bar("AAA")),
    }
    assert (
        first_scored_round_id(
            (MORNING, LATE), bars, required_symbols=("SPY",)
        )
        == LATE
    )


def test_no_round_with_eligible_bar_for_every_required_symbol_is_an_error() -> None:
    bars = {
        MORNING: (priced_bar("AAA"),),
        LATE: (priced_bar("AAA"),),
    }
    with pytest.raises(FirstWindowError) as exc:
        first_scored_round_id(
            (MORNING, LATE), bars, required_symbols=("SPY",)
        )
    assert exc.value.path == "rounds.json"
    assert exc.value.required_symbols == ("SPY",)
    assert "eligible bar" in exc.value.message


def test_snapshots_are_accepted_in_place_of_bars() -> None:
    snapshots = {
        MORNING: snapshot_for(MORNING, priced_bar("SPY"), priced_bar("AAA")),
        LATE: snapshot_for(LATE, priced_bar("SPY"), priced_bar("AAA")),
    }
    assert first_scored_round_id((MORNING, LATE), snapshots) == MORNING


def test_snapshots_or_bars_must_be_keyed_by_round_id() -> None:
    with pytest.raises(TypeError, match="mapping keyed by round_id"):
        first_scored_round_id((MORNING,), (priced_bar("SPY"),))  # type: ignore[arg-type]