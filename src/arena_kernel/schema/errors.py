"""Schema failures carry a field path so tests can name the bad field."""

from __future__ import annotations


class FieldError(ValueError):
    """Invalid input with a stable dotted field path."""

    def __init__(self, path: str, message: str) -> None:
        self.path = path
        self.message = message
        super().__init__(f"{path}: {message}")


class SchemaError(FieldError):
    """Invalid JSON contract. `path` is a dotted field path (`cash`, `positions.0.quantity`)."""
