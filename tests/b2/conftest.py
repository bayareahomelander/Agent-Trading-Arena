from decimal import Decimal

from arena_kernel.schema import Portfolio
from arena_kernel.schema.clock import Clock
from arena_kernel.schema.market import Bar, Snapshot
from arena_kernel.types import EXCHANGE_TIMEZONE_NAME, parse_et_timestamp

BAR_START = parse_et_timestamp("2026-08-17T10:16:00-04:00")
CLOSE_TS = parse_et_timestamp("2026-08-17T16:00:00-04:00")


def cash_book(
    replica_id: str = "baseline:cash",
    *,
    cash: str = "1000.00",
) -> Portfolio:
    return Portfolio(
        schema_version="1",
        replica_id=replica_id,
        product_id="baseline",
        cash=Decimal(cash),
        positions=(),
        reported_equity=None,
    )


def priced_bar(symbol: str, *, eligible: bool = True, vwap: str = "100") -> Bar:
    price = Decimal(vwap)
    return Bar(
        symbol=symbol,
        bar_start=BAR_START,
        eligible=eligible,
        open=price if eligible else None,
        high=price if eligible else None,
        low=price if eligible else None,
        close=price if eligible else None,
        volume=Decimal("1000") if eligible else None,
        vwap=price if eligible else None,
    )


def snapshot_for(round_id: str, *bars: Bar) -> Snapshot:
    start = parse_et_timestamp("2026-08-17T10:00:00-04:00")
    return Snapshot(
        schema_version="1",
        clock=Clock(
            schema_version="1",
            exchange_timestamp=start,
            timezone=EXCHANGE_TIMEZONE_NAME,
            session_status="open",
            round_id=round_id,
            round_start=start,
            deadline=parse_et_timestamp("2026-08-17T10:15:00-04:00"),
        ),
        bars=bars,
        portfolio=cash_book(),
    )