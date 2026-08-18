"""B7: all four baselines on the D13 tape. Do not edit expected/result.json."""

import json
import shutil
from decimal import Decimal
from pathlib import Path

import pytest

from arena_kernel.baselines import (
    BASELINE_REPLICA_IDS,
    BaselineTapeError,
    FirstWindowError,
    dump_baselines_result,
    run_baselines,
)
from arena_kernel.replay import dump_replay_result, replay_tape

_REPO = Path(__file__).resolve().parents[2]
TAPE = _REPO / "fixtures" / "golden" / "tape"
EXPECTED = (TAPE / "expected" / "baselines.json").read_text(encoding="utf-8").replace(
    "\r\n", "\n"
)
AGENT_EXPECTED = (TAPE / "expected" / "result.json").read_text(encoding="utf-8").replace(
    "\r\n", "\n"
)


def test_baselines_match_golden_dump() -> None:
    dumped = dump_baselines_result(run_baselines(TAPE))
    assert dumped == EXPECTED


def test_baselines_replay_is_deterministic_twice() -> None:
    first = dump_baselines_result(run_baselines(TAPE))
    second = dump_baselines_result(run_baselines(TAPE))
    assert first == second == EXPECTED


def test_changing_morning_spy_vwap_without_updating_baselines_golden_fails(
    tmp_path: Path,
) -> None:
    mutated = tmp_path / "tape"
    shutil.copytree(TAPE, mutated)
    bars_path = mutated / "rounds" / "2026-08-17-morning" / "bars.json"
    payload = json.loads(bars_path.read_text(encoding="utf-8"))
    for bar in payload["bars"]:
        if bar["symbol"] == "SPY":
            bar["vwap"] = "101.00"
    bars_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    dumped = dump_baselines_result(run_baselines(mutated))
    assert dumped != EXPECTED


def test_d13_agent_golden_is_unchanged(tmp_path: Path) -> None:
    dumped = dump_replay_result(replay_tape(TAPE, tmp_path / "work"))
    assert dumped == AGENT_EXPECTED


def test_hand_calc_nlvs_on_the_d13_tape() -> None:
    results = run_baselines(TAPE)
    assert tuple(results) == BASELINE_REPLICA_IDS
    assert results["baseline:cash"].nlv == Decimal("1000.00")
    assert results["baseline:spy_buy_and_hold"].nlv == Decimal("1118.88")
    assert results["baseline:equal_weight"].nlv == Decimal("1058.93")
    assert results["baseline:seeded_random"].nlv == Decimal("999.92")


def test_missing_tape_directory_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(BaselineTapeError) as exc:
        run_baselines(tmp_path / "no-such-tape")
    assert "missing" in exc.value.message


def test_missing_rounds_json_is_an_error(tmp_path: Path) -> None:
    empty = tmp_path / "tape"
    empty.mkdir()
    with pytest.raises(BaselineTapeError) as exc:
        run_baselines(empty)
    assert exc.value.path == "rounds.json"
    assert "missing" in exc.value.message


def test_empty_rounds_json_is_an_error(tmp_path: Path) -> None:
    tape = tmp_path / "tape"
    shutil.copytree(TAPE, tape)
    (tape / "rounds.json").write_text("[]\n", encoding="utf-8")
    with pytest.raises(FirstWindowError) as exc:
        run_baselines(tape)
    assert exc.value.path == "rounds.json"
