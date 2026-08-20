"""One-to-one replica session references stored outside agent workspaces."""

from __future__ import annotations

import json
import threading
from pathlib import Path

from arena_kernel.schema.errors import FieldError

_SESSION_SCHEMA_VERSION = "1"
_SESSION_LOCKS: dict[Path, threading.Lock] = {}
_SESSION_LOCKS_GUARD = threading.Lock()


def require_session_reference(
    value: object, *, error_cls: type[FieldError]
) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise error_cls(
            "session_reference",
            "must be a non-empty opaque string without padding",
        )
    if "\x00" in value:
        raise error_cls("session_reference", "must not contain NUL")
    return value


class SessionStore:
    """Immutable one-to-one session references outside replica workspaces."""

    def __init__(self, root: Path | str, *, error_cls: type[FieldError]) -> None:
        if not isinstance(root, (Path, str)):
            raise error_cls("session_store", "expected a path")
        resolved = Path(root).resolve(strict=False)
        try:
            resolved.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise error_cls(
                "session_store",
                f"cannot create session store: {exc}",
            ) from exc
        if not resolved.is_dir():
            raise error_cls("session_store", "must be a directory")
        self._root = resolved
        self._error_cls = error_cls
        with _SESSION_LOCKS_GUARD:
            self._lock = _SESSION_LOCKS.setdefault(resolved, threading.Lock())

    @property
    def root(self) -> Path:
        return self._root

    def record_path(self, product_id: str, replica_id: str) -> Path:
        self._store_segment(product_id, path="product_id")
        self._store_segment(replica_id, path="replica_id")
        return (self._root / product_id / f"{replica_id}.json").resolve(strict=False)

    def save(
        self,
        product_id: str,
        replica_id: str,
        session_reference: str,
    ) -> Path:
        error = self._error_cls
        reference = require_session_reference(
            session_reference, error_cls=error
        )
        target = self.record_path(product_id, replica_id)
        payload = {
            "schema_version": _SESSION_SCHEMA_VERSION,
            "product_id": product_id,
            "replica_id": replica_id,
            "session_reference": reference,
        }
        data = (json.dumps(payload, indent=2) + "\n").encode("utf-8")
        with self._lock:
            for record in self._root.rglob("*.json"):
                stored = self._load_path(record)
                if stored["session_reference"] == reference and record != target:
                    raise error(
                        "session_reference",
                        "is already mapped to another product or replica",
                    )
            if target.exists():
                stored = self._load_path(target)
                if stored != payload:
                    raise error(
                        "session_reference",
                        "replica already has a different stored session",
                    )
                return target
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("xb") as stream:
                    stream.write(data)
            except FileExistsError:
                stored = self._load_path(target)
                if stored != payload:
                    raise error(
                        "session_reference",
                        "replica session was concurrently replaced",
                    )
            except OSError as exc:
                raise error(
                    "session_store",
                    f"cannot persist session reference: {exc}",
                ) from exc
        return target

    def load(self, product_id: str, replica_id: str) -> str:
        target = self.record_path(product_id, replica_id)
        with self._lock:
            if not target.is_file():
                raise self._error_cls(
                    "session_reference",
                    "stored session is missing for this replica",
                )
            return str(self._load_path(target)["session_reference"])

    def _load_path(self, path: Path) -> dict[str, str]:
        error = self._error_cls
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise error(
                "session_reference",
                "stored session record is corrupt",
            ) from exc
        required = {
            "schema_version",
            "product_id",
            "replica_id",
            "session_reference",
        }
        if not isinstance(payload, dict) or set(payload) != required:
            raise error(
                "session_reference",
                "stored session record has an invalid shape",
            )
        for key in required:
            if not isinstance(payload[key], str):
                raise error(
                    "session_reference",
                    f"stored session field {key!r} is invalid",
                )
        if payload["schema_version"] != _SESSION_SCHEMA_VERSION:
            raise error(
                "session_reference",
                "stored session schema version is unsupported",
            )
        self._store_segment(payload["product_id"], path="product_id")
        self._store_segment(payload["replica_id"], path="replica_id")
        require_session_reference(
            payload["session_reference"], error_cls=error
        )
        expected = self.record_path(payload["product_id"], payload["replica_id"])
        if expected != path.resolve(strict=False):
            raise error(
                "session_reference",
                "stored session identity does not match its path",
            )
        return {key: str(payload[key]) for key in required}

    def _store_segment(self, value: str, *, path: str) -> None:
        if value in {".", ".."} or "/" in value or "\\" in value:
            raise self._error_cls(path, "must be one safe path segment")
