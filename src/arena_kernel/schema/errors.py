"""Schema failures carry a field path so D3+ tests can name the bad field."""

from __future__ import annotations


class SchemaError(ValueError):
    """Invalid JSON contract. `path` is a dotted field path (`cash`, `positions.0.quantity`)."""

    def __init__(self, path: str, message: str) -> None:
        self.path = path
        self.message = message
        super().__init__(f"{path}: {message}")
