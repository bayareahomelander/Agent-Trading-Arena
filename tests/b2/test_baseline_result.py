"""B2: BaselineResult is a D12 close pair, not a trade."""

from dataclasses import FrozenInstanceError
from decimal import Decimal

import pytest

from arena_kernel.baselines import BaselineResult
from arena_kernel.ledger import final_nlv, mark_to_close

from .conftest import CLOSE_TS, cash_book


def test_baseline_result_can_be_built_from_cash_only_d12_pair_without_trading() -> None:
    portfolio = cash_book()
    equity, mark_event = mark_to_close(portfolio, {}, timestamp=CLOSE_TS)
    nlv, nlv_event = final_nlv(portfolio, {}, timestamp=CLOSE_TS)
    result = BaselineResult(
        replica_id=portfolio.replica_id,
        events=(mark_event, nlv_event),
        final_portfolio=portfolio,
        marked_equity=equity,
        nlv=nlv,
    )
    assert result.replica_id == "baseline:cash"
    assert result.final_portfolio is portfolio
    assert result.final_portfolio.positions == ()
    assert result.marked_equity == Decimal("1000.00")
    assert result.nlv == Decimal("1000.00")
    assert result.events == (mark_event, nlv_event)


def test_baseline_result_is_frozen() -> None:
    portfolio = cash_book()
    equity, mark_event = mark_to_close(portfolio, {}, timestamp=CLOSE_TS)
    nlv, nlv_event = final_nlv(portfolio, {}, timestamp=CLOSE_TS)
    result = BaselineResult(
        replica_id=portfolio.replica_id,
        events=(mark_event, nlv_event),
        final_portfolio=portfolio,
        marked_equity=equity,
        nlv=nlv,
    )
    with pytest.raises(FrozenInstanceError):
        result.nlv = Decimal("0.00")  # type: ignore[misc]