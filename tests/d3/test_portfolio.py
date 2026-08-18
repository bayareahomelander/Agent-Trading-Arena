"""D3: portfolio.json schema. Missing cash is not defaulted."""

from decimal import Decimal

import pytest

from arena_kernel.schema import SchemaError, parse_portfolio

from .conftest import read_fixture


def test_valid_portfolio_fixture_parses() -> None:
    portfolio = parse_portfolio(read_fixture("valid", "portfolio.json"))
    assert portfolio.replica_id == "product-a-1"
    assert portfolio.product_id == "product-a"
    assert portfolio.cash == Decimal("1000.00")
    assert len(portfolio.positions) == 1
    assert portfolio.positions[0].symbol == "SPY"
    assert portfolio.positions[0].quantity == Decimal("2.500")
    assert portfolio.reported_equity == Decimal("2250.00")


def test_portfolio_negative_cash_fails_with_field_path() -> None:
    with pytest.raises(SchemaError) as exc:
        parse_portfolio(read_fixture("invalid", "portfolio_negative_cash.json"))
    assert exc.value.path == "cash"


def test_portfolio_missing_cash_is_not_invented() -> None:
    with pytest.raises(SchemaError) as exc:
        parse_portfolio(read_fixture("invalid", "portfolio_missing_cash.json"))
    assert exc.value.path == "cash"


def test_portfolio_bad_quantity_uses_d2_rule_with_path() -> None:
    with pytest.raises(SchemaError) as exc:
        parse_portfolio(read_fixture("invalid", "portfolio_bad_quantity.json"))
    assert exc.value.path == "positions.0.quantity"


def test_portfolio_reported_equity_may_be_omitted() -> None:
    portfolio = parse_portfolio(
        {
            "schema_version": "1",
            "replica_id": "product-a-1",
            "product_id": "product-a",
            "cash": "1000.00",
            "positions": [],
        }
    )
    assert portfolio.positions == ()
    assert portfolio.reported_equity is None


def test_portfolio_rejects_duplicate_symbols() -> None:
    with pytest.raises(SchemaError) as exc:
        parse_portfolio(
            {
                "schema_version": "1",
                "replica_id": "product-a-1",
                "product_id": "product-a",
                "cash": "1000.00",
                "positions": [
                    {"symbol": "SPY", "quantity": "1.000", "cost_basis": "1.0000"},
                    {"symbol": "SPY", "quantity": "1.000", "cost_basis": "1.0000"},
                ],
            }
        )
    assert exc.value.path == "positions.1.symbol"


def test_portfolio_rejects_ieee_float_cash_in_already_loaded_dict() -> None:
    with pytest.raises(SchemaError) as exc:
        parse_portfolio(
            {
                "schema_version": "1",
                "replica_id": "product-a-1",
                "product_id": "product-a",
                "cash": 1000.50,
                "positions": [],
            }
        )
    assert exc.value.path == "cash"
