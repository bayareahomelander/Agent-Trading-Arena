"""D7: write the README replica tree; do not invent a decision."""

from pathlib import Path

from arena_kernel.schema import parse_clock, parse_fills, parse_portfolio, parse_snapshot
from arena_kernel.workspace import (
    CLOCK_FILE,
    FILLS_FILE,
    OUTBOX_DECISION_FILE,
    PORTFOLIO_FILE,
    PROMPT_FILE,
    RULES_FILE,
    SNAPSHOT_FILE,
    write_replica_workspace,
)

_REPO = Path(__file__).resolve().parents[2]
_D3 = _REPO / "tests" / "d3" / "fixtures" / "valid"
_D5 = _REPO / "tests" / "d5" / "fixtures" / "valid"

RULES = "# Frozen rules\nDo not invent strategy.\n"
PROMPT = "Treat terminal simulated wealth as the thing you are accountable for.\n"


def _write(root: Path) -> Path:
    snapshot = parse_snapshot((_D5 / "snapshot_two_symbols.json").read_text(encoding="utf-8"))
    fills = parse_fills((_D3 / "fills_empty.json").read_text(encoding="utf-8"))
    return write_replica_workspace(
        root,
        rules_md=RULES,
        prompt_md=PROMPT,
        clock=snapshot.clock,
        portfolio=snapshot.portfolio,
        fills=fills,
        snapshot=snapshot,
    )


def test_writer_creates_readme_layout_without_decision(tmp_path: Path) -> None:
    root = _write(tmp_path / "replica")
    assert (root / RULES_FILE).is_file()
    assert (root / PROMPT_FILE).is_file()
    assert (root / CLOCK_FILE).is_file()
    assert (root / PORTFOLIO_FILE).is_file()
    assert (root / FILLS_FILE).is_file()
    assert (root / SNAPSHOT_FILE).is_file()
    assert (root / "agent" / "notes").is_dir()
    assert (root / "agent" / "research").is_dir()
    assert (root / "agent" / "tools").is_dir()
    assert (root / "outbox").is_dir()
    assert not (root / OUTBOX_DECISION_FILE).exists()


def test_writer_copies_caller_rules_and_prompt_verbatim(tmp_path: Path) -> None:
    root = _write(tmp_path / "replica")
    assert (root / RULES_FILE).read_text(encoding="utf-8") == RULES
    assert (root / PROMPT_FILE).read_text(encoding="utf-8") == PROMPT


def test_written_state_reparses_with_d3_and_d5(tmp_path: Path) -> None:
    root = _write(tmp_path / "replica")
    clock = parse_clock((root / CLOCK_FILE).read_text(encoding="utf-8"))
    portfolio = parse_portfolio((root / PORTFOLIO_FILE).read_text(encoding="utf-8"))
    fills = parse_fills((root / FILLS_FILE).read_text(encoding="utf-8"))
    snapshot = parse_snapshot((root / SNAPSHOT_FILE).read_text(encoding="utf-8"))
    assert clock.round_id == "2026-08-17-morning"
    assert portfolio.replica_id == "product-a-1"
    assert fills.fills == ()
    assert [bar.symbol for bar in snapshot.bars] == ["AAA", "SPY"]


def test_second_write_is_byte_stable_for_state_json(tmp_path: Path) -> None:
    first = _write(tmp_path / "a")
    second = _write(tmp_path / "b")
    for relative in (CLOCK_FILE, PORTFOLIO_FILE, FILLS_FILE, SNAPSHOT_FILE):
        left = (first / relative).read_bytes()
        right = (second / relative).read_bytes()
        assert left == right
        assert left.endswith(b"\n")
