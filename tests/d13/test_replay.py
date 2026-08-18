"""D13: canned tape replay. If this fails, bisect D9–D12; do not edit goldens."""

import json
import shutil
from decimal import Decimal
from pathlib import Path

from arena_kernel.replay import dump_replay_result, replay_tape
from arena_kernel.workspace import CLOCK_FILE, SNAPSHOT_FILE

_REPO = Path(__file__).resolve().parents[2]
TAPE = _REPO / "fixtures" / "golden" / "tape"
EXPECTED = (TAPE / "expected" / "result.json").read_text(encoding="utf-8").replace(
    "\r\n", "\n"
)


def test_replay_matches_golden_result(tmp_path: Path) -> None:
    result = replay_tape(TAPE, tmp_path / "work")
    assert dump_replay_result(result) == EXPECTED
    assert result.nlv_by_replica["product-a-1"] == Decimal("1059.43")
    assert result.median == Decimal("1029.72")


def test_replay_is_deterministic_twice(tmp_path: Path) -> None:
    first = dump_replay_result(replay_tape(TAPE, tmp_path / "a"))
    second = dump_replay_result(replay_tape(TAPE, tmp_path / "b"))
    assert first == second == EXPECTED


def test_replay_writes_workspace_trees(tmp_path: Path) -> None:
    work = tmp_path / "work"
    replay_tape(TAPE, work)
    assert (work / "product-a-1" / CLOCK_FILE).is_file()
    assert (work / "product-a-2" / SNAPSHOT_FILE).is_file()
    assert not (work / "product-a-1" / "outbox" / "decision.json").exists()


def test_changing_morning_spy_vwap_without_updating_golden_fails(
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
    dumped = dump_replay_result(replay_tape(mutated, tmp_path / "work"))
    assert dumped != EXPECTED
