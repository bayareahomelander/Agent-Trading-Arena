from decimal import Decimal

from arena_kernel.schema.market import Bar
from arena_kernel.types import parse_et_timestamp

BAR_START = parse_et_timestamp("2026-08-17T10:15:00-04:00")


def bar(
    *,
    vwap: Decimal | None = None,
    high: Decimal | None = Decimal("101"),
    low: Decimal | None = Decimal("99"),
    eligible: bool = True,
    open_: Decimal | None = Decimal("100"),
    close: Decimal | None = Decimal("100"),
) -> Bar:
    return Bar(
        symbol="AAA",
        bar_start=BAR_START,
        eligible=eligible,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=Decimal("1000") if eligible else None,
        vwap=vwap,
    )
