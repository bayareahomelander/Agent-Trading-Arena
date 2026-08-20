"""JSON contracts for replica state, decisions, snapshots, and ledger events.

D3: clock.json, portfolio.json, and fills.json. D4–D6 add the rest.
"""

from arena_kernel.schema.clock import SESSION_STATUSES, Clock, dump_clock, parse_clock
from arena_kernel.schema.decision import ACTIONS, Decision, Order, parse_decision
from arena_kernel.schema.errors import SchemaError
from arena_kernel.schema.events import (
    EVENT_TYPES,
    REFERENCE_SOURCES,
    DecisionAcceptedPayload,
    DecisionMissingPayload,
    FinalNlvPayload,
    LedgerEvent,
    MarkedToClosePayload,
    OrderFilledPayload,
    OrderRejectedPayload,
    dump_ledger_event,
    ledger_event_to_dict,
    make_decision_accepted,
    make_decision_missing,
    make_final_nlv,
    make_marked_to_close,
    make_order_filled,
    make_order_rejected,
    parse_ledger_event,
)
from arena_kernel.schema.fills import FillsFile, PriorFill, dump_fills, parse_fills
from arena_kernel.schema.market import Bar, Snapshot, dump_snapshot, parse_bar, parse_snapshot
from arena_kernel.schema.portfolio import Portfolio, Position, dump_portfolio, parse_portfolio
from arena_kernel.schema.round_id import parse_round_id
from arena_kernel.schema._parse import SCHEMA_VERSION

__all__ = [
    "ACTIONS",
    "SCHEMA_VERSION",
    "SESSION_STATUSES",
    "EVENT_TYPES",
    "REFERENCE_SOURCES",
    "Bar",
    "Clock",
    "Decision",
    "DecisionAcceptedPayload",
    "DecisionMissingPayload",
    "FillsFile",
    "FinalNlvPayload",
    "LedgerEvent",
    "MarkedToClosePayload",
    "Order",
    "OrderFilledPayload",
    "OrderRejectedPayload",
    "Portfolio",
    "Position",
    "PriorFill",
    "SchemaError",
    "Snapshot",
    "dump_clock",
    "dump_fills",
    "dump_ledger_event",
    "dump_portfolio",
    "dump_snapshot",
    "ledger_event_to_dict",
    "make_decision_accepted",
    "make_decision_missing",
    "make_final_nlv",
    "make_marked_to_close",
    "make_order_filled",
    "make_order_rejected",
    "parse_bar",
    "parse_clock",
    "parse_decision",
    "parse_fills",
    "parse_ledger_event",
    "parse_portfolio",
    "parse_round_id",
    "parse_snapshot",
]
