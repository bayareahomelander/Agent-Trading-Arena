"""Stable JSON dumps: indent 2, insertion order, trailing newline."""

from __future__ import annotations

import json
from typing import Any


def dump_json(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=2) + "\n"
