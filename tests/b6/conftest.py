from decimal import Decimal

from arena_kernel.schema import Portfolio, Snapshot
from arena_kernel.schema.clock import Clock
from arena_kernel.schema.market import Bar
from arena_kernel.types import EXCHANGE_TIMEZONE_NAME, parse_et_timestamp

MORNING = "2026-08-17-morning"
LATE = "2026-08-17-late"
CLOSE_TS = parse_et_timestamp("2026-08-17T16:00:00-04:00")
CLOSES = {"SPY": Decimal("112"), "AAA": Decimal("10")}
UNIVERSE = ("AAA", "SPY")


def starter(
    *,
    replica_id: str = "product-a-1",
    product_id: str = "product-a",
    cash: str = "1000.00",
) -> Portfolio:
    return Portfolio(
        schema_version="1",
        replica_id=replica_id,
        product_id=product_id,
        cash=Decimal(cash),
        positions=(),
        reported_equity=None,
    )


def priced_bar(
    symbol: str,
    *,
    vwap: str = "100",
    bar_start: str = "2026-08-17T10:16:00-04:00",
) -> Bar:
    price = Decimal(vwap)
    return Bar(
        symbol=symbol,
        bar_start=parse_et_timestamp(bar_start),
        eligible=True,
        open=price,
        high=price,
        low=price,
        close=price,
        volume=Decimal("1000"),
        vwap=price,
    )


def snapshot_for(round_id: str, *bars: Bar) -> Snapshot:
    if round_id.endswith("late"):
        start = parse_et_timestamp("2026-08-17T15:30:00-04:00")
        deadline = parse_et_timestamp("2026-08-17T15:45:00-04:00")
        bar_start = "2026-08-17T15:46:00-04:00"
        if not bars:
            bars = (
                priced_bar("AAA", bar_start=bar_start),
                priced_bar("SPY", bar_start=bar_start),
            )
    else:
        start = parse_et_timestamp("2026-08-17T10:00:00-04:00")
        deadline = parse_et_timestamp("2026-08-17T10:15:00-04:00")
        if not bars:
            bars = (priced_bar("AAA"), priced_bar("SPY"))
    return Snapshot(
        schema_version="1",
        clock=Clock(
            schema_version="1",
            exchange_timestamp=start,
            timezone=EXCHANGE_TIMEZONE_NAME,
            session_status="open",
            round_id=round_id,
            round_start=start,
            deadline=deadline,
        ),
        bars=bars,
        portfolio=starter(),
    )


def two_round_tape() -> dict[str, Snapshot]:
    return {
        MORNING: snapshot_for(MORNING),
        LATE: snapshot_for(LATE),
    }
