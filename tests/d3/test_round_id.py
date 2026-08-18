"""D3: round_id is YYYY-MM-DD-morning or YYYY-MM-DD-late."""

import pytest

from arena_kernel.schema import SchemaError, parse_round_id


def test_parse_round_id_accepts_morning_and_late() -> None:
    assert parse_round_id("2026-08-17-morning") == "2026-08-17-morning"
    assert parse_round_id("2026-08-17-late") == "2026-08-17-late"


def test_parse_round_id_rejects_unknown_kind() -> None:
    with pytest.raises(SchemaError) as exc:
        parse_round_id("2026-08-17-evening")
    assert exc.value.path == "round_id"


def test_parse_round_id_rejects_impossible_date() -> None:
    with pytest.raises(SchemaError) as exc:
        parse_round_id("2026-02-30-morning")
    assert exc.value.path == "round_id"
