"""D3: fills.json schema. Empty list is valid."""

from decimal import Decimal

import pytest

from arena_kernel.schema import SchemaError, parse_fills

from .conftest import read_fixture


def test_empty_fills_fixture_is_valid() -> None:
    book = parse_fills(read_fixture("valid", "fills_empty.json"))
    assert book.fills == ()


def test_one_fill_fixture_keeps_stable_id() -> None:
    book = parse_fills(read_fixture("valid", "fills_one.json"))
    assert len(book.fills) == 1
    fill = book.fills[0]
    assert fill.fill_id == "2026-08-17-morning:1"
    assert fill.symbol == "SPY"
    assert fill.side == "buy"
    assert fill.quantity == Decimal("2.500")
    assert fill.fill_price == Decimal("500.0000")


def test_duplicate_fill_id_fails_with_field_path() -> None:
    with pytest.raises(SchemaError) as exc:
        parse_fills(read_fixture("invalid", "fills_duplicate_id.json"))
    assert exc.value.path == "fills.1.fill_id"


def test_fills_must_be_a_list() -> None:
    with pytest.raises(SchemaError) as exc:
        parse_fills({"schema_version": "1", "fills": {}})
    assert exc.value.path == "fills"
