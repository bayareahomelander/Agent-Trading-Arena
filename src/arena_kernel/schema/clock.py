"""clock.json — authoritative exchange time and deadline."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from arena_kernel.schema._parse import (
    as_mapping,
    join_path,
    require_object,
    require_schema_version,
    require_str,
    require_timestamp,
)
from arena_kernel.schema.errors import SchemaError
from arena_kernel.schema.round_id import parse_round_id
from arena_kernel.schema._dump import dump_json
from arena_kernel.types import EXCHANGE_TIMEZONE_NAME, format_et_timestamp

SESSION_STATUSES = frozenset({"pre_open", "open", "closed"})

_REQUIRED = (
    "schema_version",
    "exchange_timestamp",
    "timezone",
    "session_status",
    "round_id",
    "round_start",
    "deadline",
)


@dataclass(frozen=True)
class Clock:
    schema_version: str
    exchange_timestamp: datetime
    timezone: str
    session_status: str
    round_id: str
    round_start: datetime
    deadline: datetime


def parse_clock(data: Mapping[str, Any] | str | bytes, *, path: str = "$") -> Clock:
    payload = as_mapping(data)
    require_object(payload, required=_REQUIRED, path=path)
    timezone = require_str(payload, "timezone", path=path)
    if timezone != EXCHANGE_TIMEZONE_NAME:
        raise SchemaError(join_path(path, "timezone"), f"must be {EXCHANGE_TIMEZONE_NAME}")
    session_status = require_str(payload, "session_status", path=path)
    if session_status not in SESSION_STATUSES:
        raise SchemaError(
            join_path(path, "session_status"),
            "must be pre_open, open, or closed",
        )
    round_start = require_timestamp(payload, "round_start", path=path)
    deadline = require_timestamp(payload, "deadline", path=path)
    if deadline <= round_start:
        raise SchemaError(join_path(path, "deadline"), "must be after round_start")
    return Clock(
        schema_version=require_schema_version(payload, path=path),
        exchange_timestamp=require_timestamp(payload, "exchange_timestamp", path=path),
        timezone=timezone,
        session_status=session_status,
        round_id=parse_round_id(
            require_str(payload, "round_id", path=path),
            path=join_path(path, "round_id"),
        ),
        round_start=round_start,
        deadline=deadline,
    )


def clock_to_dict(clock: Clock) -> dict[str, Any]:
    return {
        "schema_version": clock.schema_version,
        "exchange_timestamp": format_et_timestamp(clock.exchange_timestamp),
        "timezone": clock.timezone,
        "session_status": clock.session_status,
        "round_id": clock.round_id,
        "round_start": format_et_timestamp(clock.round_start),
        "deadline": format_et_timestamp(clock.deadline),
    }


def dump_clock(clock: Clock) -> str:
    return dump_json(clock_to_dict(clock))
