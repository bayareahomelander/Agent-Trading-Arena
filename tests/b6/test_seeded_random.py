"""B6: same seed + same tape is the same path. Invalid seed does not use the clock."""

import json
from pathlib import Path
from random import Random

import pytest

from arena_kernel.baselines import (
    DEFAULT_RANDOM_SEED,
    FirstWindowError,
    SeededRandomError,
    load_random_seed,
    random_decision,
    run_seeded_random,
)
from arena_kernel.schema._dump import dump_json
from arena_kernel.schema._parse import load_json_object
from arena_kernel.schema.clock import parse_clock
from arena_kernel.schema.events import ledger_event_to_dict
from arena_kernel.schema.errors import SchemaError
from arena_kernel.schema.market import parse_bar
from arena_kernel.schema.market import Snapshot

from .conftest import (
    CLOSE_TS,
    CLOSES,
    LATE,
    MORNING,
    UNIVERSE,
    starter,
    two_round_tape,
)

_REPO = Path(__file__).resolve().parents[2]
TAPE = _REPO / "fixtures" / "golden" / "tape"


def _dump(result) -> str:
    return dump_json(
        {"events": [ledger_event_to_dict(event) for event in result.events]}
    )


def _run(rounds, *, seed: int | None = DEFAULT_RANDOM_SEED, **kwargs):
    return run_seeded_random(
        starter(),
        tuple(rounds),
        rounds,
        CLOSES,
        CLOSE_TS,
        UNIVERSE,
        seed=seed,
        **kwargs,
    )


def _d13_snapshots() -> tuple[list[str], dict[str, Snapshot]]:
    book = starter()
    round_ids = json.loads((TAPE / "rounds.json").read_text(encoding="utf-8"))
    snapshots: dict[str, Snapshot] = {}
    for round_id in round_ids:
        clock = parse_clock(
            (TAPE / "rounds" / round_id / "clock.json").read_text(encoding="utf-8")
        )
        payload = load_json_object(
            (TAPE / "rounds" / round_id / "bars.json").read_text(encoding="utf-8")
        )
        bars = tuple(parse_bar(item) for item in payload["bars"])
        snapshots[round_id] = Snapshot(
            schema_version="1",
            clock=clock,
            bars=bars,
            portfolio=book,
        )
    return round_ids, snapshots


def test_tape_baselines_json_uses_the_documented_default_seed() -> None:
    assert load_random_seed(TAPE / "baselines.json") == DEFAULT_RANDOM_SEED
    assert DEFAULT_RANDOM_SEED == 20260817


def test_same_seed_and_same_tape_emit_identical_event_dumps() -> None:
    tape = two_round_tape()
    first = _dump(_run(tape, seed=DEFAULT_RANDOM_SEED))
    second = _dump(_run(tape, seed=DEFAULT_RANDOM_SEED))
    assert first == second


def test_different_seed_changes_at_least_one_decision() -> None:
    tape = two_round_tape()
    default = _dump(_run(tape, seed=DEFAULT_RANDOM_SEED))
    other = _dump(_run(tape, seed=1))
    assert default != other


def test_d13_tape_is_deterministic_from_baselines_json() -> None:
    round_ids, snapshots = _d13_snapshots()
    path = TAPE / "baselines.json"
    first = run_seeded_random(
        starter(),
        round_ids,
        snapshots,
        CLOSES,
        CLOSE_TS,
        UNIVERSE,
        baselines_path=path,
    )
    second = run_seeded_random(
        starter(),
        round_ids,
        snapshots,
        CLOSES,
        CLOSE_TS,
        UNIVERSE,
        baselines_path=path,
    )
    assert _dump(first) == _dump(second)
    assert first.replica_id == "baseline:seeded_random"


def test_invalid_seed_file_is_an_error_with_no_time_fallback(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "baselines.json"
    with pytest.raises(SeededRandomError) as exc:
        load_random_seed(missing)
    assert exc.value.path == "baselines.json"
    assert "missing" in exc.value.message

    bad = tmp_path / "bad.json"
    bad.write_text('{"random_seed": "7"}\n', encoding="utf-8")
    with pytest.raises(SeededRandomError) as exc:
        load_random_seed(bad)
    assert exc.value.path == "random_seed"
    assert "integer" in exc.value.message


def test_bool_and_float_seeds_are_rejected(tmp_path: Path) -> None:
    flag = tmp_path / "bool.json"
    flag.write_text('{"random_seed": true}\n', encoding="utf-8")
    with pytest.raises(SeededRandomError) as exc:
        load_random_seed(flag)
    assert exc.value.path == "random_seed"

    frac = tmp_path / "float.json"
    frac.write_text('{"random_seed": 1.5}\n', encoding="utf-8")
    with pytest.raises(SeededRandomError) as exc:
        load_random_seed(frac)
    assert exc.value.path == "random_seed"


def test_missing_seed_key_is_an_error(tmp_path: Path) -> None:
    empty = tmp_path / "baselines.json"
    empty.write_text("{}\n", encoding="utf-8")
    with pytest.raises(SeededRandomError) as exc:
        load_random_seed(empty)
    assert exc.value.path == "random_seed"
    assert "missing" in exc.value.message


def test_run_without_seed_or_file_is_an_error() -> None:
    with pytest.raises(SeededRandomError) as exc:
        _run(two_round_tape(), seed=None)
    assert exc.value.path == "random_seed"


def test_random_decision_is_deterministic_for_a_fixed_seed() -> None:
    book = starter()
    first = random_decision(Random(DEFAULT_RANDOM_SEED), book, UNIVERSE, MORNING)
    second = random_decision(Random(DEFAULT_RANDOM_SEED), book, UNIVERSE, MORNING)
    assert first == second
    assert 0 <= first.confidence <= 1


def test_zero_cash_is_a_hold() -> None:
    book = starter(cash="0.00")
    decision = random_decision(Random(1), book, UNIVERSE, LATE)
    assert decision.action == "hold"
    assert decision.orders == ()


def test_invalid_round_id_is_a_schema_error() -> None:
    with pytest.raises(SchemaError) as exc:
        random_decision(Random(1), starter(), UNIVERSE, "not-a-round")
    assert exc.value.path == "round_id"


def test_empty_universe_is_an_error() -> None:
    with pytest.raises(SeededRandomError) as exc:
        run_seeded_random(
            starter(),
            (MORNING,),
            two_round_tape(),
            CLOSES,
            CLOSE_TS,
            (),
            seed=DEFAULT_RANDOM_SEED,
        )
    assert exc.value.path == "universe"


def test_empty_rounds_still_names_rounds_json() -> None:
    with pytest.raises(FirstWindowError) as exc:
        run_seeded_random(
            starter(),
            (),
            {},
            CLOSES,
            CLOSE_TS,
            UNIVERSE,
            seed=DEFAULT_RANDOM_SEED,
        )
    assert exc.value.path == "rounds.json"


def test_seeded_random_does_not_mutate_input_portfolio() -> None:
    book = starter()
    result = run_seeded_random(
        book,
        (MORNING, LATE),
        two_round_tape(),
        CLOSES,
        CLOSE_TS,
        UNIVERSE,
        seed=DEFAULT_RANDOM_SEED,
    )
    assert book.replica_id == "product-a-1"
    assert book.product_id == "product-a"
    assert result.final_portfolio is not book
    assert result.final_portfolio.product_id == "baseline"
