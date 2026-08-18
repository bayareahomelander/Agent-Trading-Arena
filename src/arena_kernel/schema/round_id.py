"""Round id convention used by clock, decisions, and fills."""

from __future__ import annotations

import re
from datetime import date

from arena_kernel.schema.errors import SchemaError
from arena_kernel.vocabulary import ROUND_KINDS

_ROUND_ID = re.compile(r"^(\d{4}-\d{2}-\d{2})-(morning|late)$")


def parse_round_id(value: str, *, path: str = "round_id") -> str:
    """Accept `YYYY-MM-DD-morning` or `YYYY-MM-DD-late` with a real calendar date."""
    if not isinstance(value, str):
        raise SchemaError(path, "expected a string")
    match = _ROUND_ID.fullmatch(value)
    if match is None:
        raise SchemaError(path, "must match YYYY-MM-DD-morning or YYYY-MM-DD-late")
    day_text, kind = match.group(1), match.group(2)
    try:
        date.fromisoformat(day_text)
    except ValueError as exc:
        raise SchemaError(path, f"invalid calendar date {day_text!r}") from exc
    if kind not in ROUND_KINDS:
        raise SchemaError(path, "round kind must be morning or late")
    return value
