"""D6: ledger events construct, parse, and serialize stably."""

from decimal import Decimal

import pytest

from arena_kernel.schema import (
    EVENT_TYPES,
    SchemaError,
    dump_ledger_event,
    ledger_event_to_dict,
    make_decision_accepted,
    make_final_nlv,
    make_order_filled,
    parse_ledger_event,
)
from arena_kernel.schema.events import FILL_PAYLOAD_KEYS, REJECT_PAYLOAD_KEYS

from .conftest import TS, read_fixture, sample_fill, sample_reject


def test_fill_event_matches_golden() -> None:
    assert dump_ledger_event(sample_fill()) == read_fixture("golden", "order_filled.json")


def test_reject_event_matches_golden() -> None:
    assert dump_ledger_event(sample_reject()) == read_fixture("golden", "order_rejected.json")


def test_fill_and_reject_round_trip() -> None:
    filled = parse_ledger_event(read_fixture("golden", "order_filled.json"))
    rejected = parse_ledger_event(read_fixture("golden", "order_rejected.json"))
    assert dump_ledger_event(filled) == read_fixture("golden", "order_filled.json")
    assert dump_ledger_event(rejected) == read_fixture("golden", "order_rejected.json")
    assert filled.payload.cash_after == Decimal("899.95")
    assert rejected.payload.reason == "insufficient_cash"


def test_dump_is_byte_stable_across_calls() -> None:
    event = sample_fill()
    assert dump_ledger_event(event) == dump_ledger_event(event)


def test_fill_payload_key_order_is_locked() -> None:
    payload = ledger_event_to_dict(sample_fill())["payload"]
    assert list(payload) == list(FILL_PAYLOAD_KEYS)


def test_reject_payload_key_order_is_locked() -> None:
    payload = ledger_event_to_dict(sample_reject())["payload"]
    assert list(payload) == list(REJECT_PAYLOAD_KEYS)


def test_bar_id_defaults_to_symbol_at_bar_start() -> None:
    assert sample_fill().payload.bar_id == "SPY@2026-08-17T10:15:00-04:00"


def test_unknown_reference_source_is_schema_error() -> None:
    with pytest.raises(SchemaError) as exc:
        make_order_filled(
            replica_id="product-a-1",
            round_id="2026-08-17-morning",
            timestamp=TS,
            fill_id="x",
            symbol="SPY",
            side="buy",
            quantity=Decimal("1.000"),
            notional_usd=Decimal("100.00"),
            reference_source="last",
            bar_start=TS,
            raw_fill=Decimal("100.0000"),
            fill_price=Decimal("100.0000"),
            cash_before=Decimal("1000.00"),
            cash_after=Decimal("900.00"),
        )
    assert exc.value.path == "payload.reference_source"


def test_reject_requires_reason() -> None:
    with pytest.raises(SchemaError) as exc:
        parse_ledger_event(
            {
                "schema_version": "1",
                "type": "order_rejected",
                "replica_id": "product-a-1",
                "round_id": "2026-08-17-morning",
                "timestamp": "2026-08-17T10:16:00-04:00",
                "payload": {
                    "symbol": "SPY",
                    "side": "buy",
                    "priority": 1,
                },
            }
        )
    assert exc.value.path == "payload.reason"


def test_event_types_match_the_plan() -> None:
    assert EVENT_TYPES == (
        "round_opened",
        "decision_accepted",
        "decision_missing",
        "order_rejected",
        "order_filled",
        "marked_to_close",
        "final_nlv",
    )


def test_final_nlv_may_omit_round_id() -> None:
    event = make_final_nlv(
        replica_id="product-a-1",
        timestamp=TS,
        nlv=Decimal("1000.00"),
    )
    assert event.round_id is None
    again = parse_ledger_event(dump_ledger_event(event))
    assert again.payload.nlv == Decimal("1000.00")


def test_decision_accepted_round_trips() -> None:
    event = make_decision_accepted(
        replica_id="product-a-1",
        round_id="2026-08-17-morning",
        timestamp=TS,
        action="hold",
        order_count=0,
    )
    assert parse_ledger_event(dump_ledger_event(event)).payload.action == "hold"
