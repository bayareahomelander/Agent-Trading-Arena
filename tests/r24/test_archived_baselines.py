"""R24: archived baselines match a direct B7 dump."""

import shutil
from pathlib import Path

import pytest

from arena_kernel.baselines import (
    BASELINE_REPLICA_IDS,
    BaselineTapeError,
    SeededRandomError,
    dump_baselines_result,
    run_baselines,
)
from arena_runtime.orchestrator import run_archived_baselines

TAPE = Path(__file__).resolve().parents[2] / "fixtures" / "golden" / "tape"


def test_archived_baselines_equal_direct_b7_dump(tmp_path: Path) -> None:
    books_root = (tmp_path / "books").resolve()
    expected = dump_baselines_result(run_baselines(TAPE))

    dumped = run_archived_baselines(tape_dir=TAPE, books_root=books_root)

    assert dumped == expected
    archived = books_root / ".baselines" / "baselines.json"
    assert archived.read_text(encoding="utf-8") == expected
    assert tuple(run_baselines(TAPE)) == BASELINE_REPLICA_IDS
    assert "product-a-1" not in dumped


def test_missing_tape_raises_existing_baseline_error(tmp_path: Path) -> None:
    with pytest.raises(BaselineTapeError) as exc:
        run_archived_baselines(
            tape_dir=tmp_path / "missing-tape",
            books_root=(tmp_path / "books").resolve(),
        )
    assert "missing" in exc.value.message


def test_missing_seed_raises_existing_seed_error(tmp_path: Path) -> None:
    tape = tmp_path / "tape"
    shutil.copytree(TAPE, tape)
    (tape / "baselines.json").unlink()
    with pytest.raises(SeededRandomError) as exc:
        run_archived_baselines(
            tape_dir=tape,
            books_root=(tmp_path / "books").resolve(),
        )
    assert exc.value.path == "baselines.json"
