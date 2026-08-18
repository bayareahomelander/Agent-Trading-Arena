from decimal import Decimal
from pathlib import Path

from arena_kernel.schema import make_order_filled, make_order_rejected
from arena_kernel.types import parse_et_timestamp

FIXTURES = Path(__file__).parent / "fixtures"

TS = parse_et_timestamp("2026-08-17T10:16:00-04:00")
BAR_START = parse_et_timestamp("2026-08-17T10:15:00-04:00")


def read_fixture(*parts: str) -> str:
    return (FIXTURES.joinpath(*parts)).read_text(encoding="utf-8").replace("\r\n", "\n")


def sample_fill():
    return make_order_filled(
        replica_id="product-a-1",
        round_id="2026-08-17-morning",
        timestamp=TS,
        fill_id="2026-08-17-morning:1",
        symbol="SPY",
        side="buy",
        quantity=Decimal("1.000"),
        notional_usd=Decimal("100.05"),
        reference_source="vwap",
        bar_start=BAR_START,
        raw_fill=Decimal("100.0500"),
        fill_price=Decimal("100.0500"),
        cash_before=Decimal("1000.00"),
        cash_after=Decimal("899.95"),
    )


def sample_reject():
    return make_order_rejected(
        replica_id="product-a-1",
        round_id="2026-08-17-morning",
        timestamp=TS,
        reason="insufficient_cash",
        symbol="SPY",
        side="buy",
        priority=1,
    )
