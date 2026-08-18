"""D10: one order. Look at D2/D9 first if fill math is wrong."""

from decimal import Decimal

from arena_kernel.matching import (
    REASON_BUY_QTY_ZERO,
    REASON_INSUFFICIENT_CASH,
    REASON_INSUFFICIENT_HOLDINGS,
    apply_order,
    realized_pnl,
)
from arena_kernel.pricing import REASON_INELIGIBLE
from arena_kernel.schema.events import OrderFilledPayload, OrderRejectedPayload
from arena_kernel.schema.market import Bar

from .conftest import ROUND_ID, TS, buy, cash_book, position, priced_bar, sell


def _apply(book, order, bar, fill_id: str = "2026-08-17-morning:1"):
    return apply_order(
        book, order, bar, round_id=ROUND_ID, timestamp=TS, fill_id=fill_id
    )


def test_buy_exact_afford_spends_cash_and_opens_position() -> None:
    # vwap 100 → buy 100.0500. 1000/100.0500 floors to 9.995. cost 999.99975 → 1000.00
    event, after = _apply(cash_book("1000.00"), buy(notional="1000.00"), priced_bar())
    assert isinstance(event.payload, OrderFilledPayload)
    assert after.cash == Decimal("0.00")
    assert after.positions[0].symbol == "SPY"
    assert after.positions[0].quantity == Decimal("9.995")
    assert after.positions[0].cost_basis == Decimal("100.0500")
    assert event.payload.fill_price == Decimal("100.0500")


def test_buy_rejected_when_cash_short_by_one_cent() -> None:
    event, after = _apply(cash_book("999.99"), buy(notional="1000.00"), priced_bar())
    assert isinstance(event.payload, OrderRejectedPayload)
    assert event.payload.reason == REASON_INSUFFICIENT_CASH
    assert after.cash == Decimal("999.99")
    assert after.positions == ()


def test_buy_notional_too_small_for_0_001_share_is_rejected() -> None:
    event, after = _apply(cash_book("1000.00"), buy(notional="0.05"), priced_bar())
    assert isinstance(event.payload, OrderRejectedPayload)
    assert event.payload.reason == REASON_BUY_QTY_ZERO
    assert after.cash == Decimal("1000.00")


def test_sell_too_many_shares_is_rejected() -> None:
    book = cash_book("100.00", position("SPY", "1.000", "100.0500"))
    event, after = _apply(book, sell(quantity="1.001"), priced_bar())
    assert isinstance(event.payload, OrderRejectedPayload)
    assert event.payload.reason == REASON_INSUFFICIENT_HOLDINGS
    assert after.positions[0].quantity == Decimal("1.000")
    assert after.cash == Decimal("100.00")


def test_sell_entire_position_removes_the_row() -> None:
    book = cash_book("0.00", position("SPY", "2.500", "100.0500"))
    event, after = _apply(book, sell(quantity="2.500"), priced_bar())
    assert isinstance(event.payload, OrderFilledPayload)
    assert after.positions == ()
    # sell fill 99.9500 × 2.500 = 249.875 → 249.88
    assert after.cash == Decimal("249.88")


def test_cannot_fill_rejects_and_leaves_portfolio_unchanged() -> None:
    bar = Bar(
        symbol="SPY",
        bar_start=priced_bar().bar_start,
        eligible=False,
        open=None,
        high=None,
        low=None,
        close=None,
        volume=None,
        vwap=None,
    )
    book = cash_book("1000.00")
    event, after = _apply(book, buy(notional="100.00"), bar)
    assert isinstance(event.payload, OrderRejectedPayload)
    assert event.payload.reason == REASON_INELIGIBLE
    assert after is book
    assert after.positions == ()


def test_second_buy_uses_average_cost() -> None:
    first, book = _apply(
        cash_book("1000.00"),
        buy(notional="100.05"),
        priced_bar(vwap="100"),
        fill_id="f1",
    )
    assert isinstance(first.payload, OrderFilledPayload)
    assert book.positions[0].quantity == Decimal("1.000")
    second, book = _apply(
        book,
        buy(notional="110.06"),
        priced_bar(vwap="110"),
        fill_id="f2",
    )
    assert isinstance(second.payload, OrderFilledPayload)
    # 1 @ 100.0500 + 1 @ 110.0550 → 2 @ 105.0525
    assert book.positions[0].quantity == Decimal("2.000")
    assert book.positions[0].cost_basis == Decimal("105.0525")


def test_sell_keeps_average_cost_and_realized_pnl_formula() -> None:
    book = cash_book("0.00", position("SPY", "2.000", "100.0500"))
    event, after = _apply(book, sell(quantity="1.000"), priced_bar())
    assert isinstance(event.payload, OrderFilledPayload)
    assert after.positions[0].quantity == Decimal("1.000")
    assert after.positions[0].cost_basis == Decimal("100.0500")
    assert realized_pnl(
        Decimal("99.9500"), Decimal("100.0500"), Decimal("1.000")
    ) == Decimal("-0.1000")


def test_apply_order_does_not_mutate_input() -> None:
    book = cash_book("1000.00")
    _apply(book, buy(notional="100.05"), priced_bar())
    assert book.cash == Decimal("1000.00")
    assert book.positions == ()
