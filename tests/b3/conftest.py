from decimal import Decimal

from arena_kernel.schema import Portfolio, Position
from arena_kernel.types import parse_et_timestamp

CLOSE_TS = parse_et_timestamp("2026-08-17T16:00:00-04:00")
CLOSES = {"AAA": Decimal("10"), "SPY": Decimal("112")}


def starter(
    *,
    replica_id: str = "product-a-1",
    product_id: str = "product-a",
    cash: str = "1000.00",
    positions: tuple[Position, ...] = (),
) -> Portfolio:
    return Portfolio(
        schema_version="1",
        replica_id=replica_id,
        product_id=product_id,
        cash=Decimal(cash),
        positions=positions,
        reported_equity=None,
    )
