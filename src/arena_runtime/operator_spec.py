"""One-round operator JSON contract. Construction and waiting are E8/E9."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Final, Mapping

from arena_kernel.schema._dump import dump_json
from arena_kernel.schema._parse import SCHEMA_VERSION, join_path
from arena_kernel.schema.errors import SchemaError
from arena_kernel.schema.round_id import parse_round_id
from arena_kernel.types import format_et_timestamp, parse_et_timestamp
from arena_runtime.orchestrator import OrchestratorError, ReplicaDuty
from arena_runtime.registration import (
    RuntimeRegistration,
    parse_runtime_registration,
    runtime_registration_to_dict,
)

VENDOR_KINDS: Final[tuple[str, ...]] = ("fixture", "aggregates")
ADAPTER_IDS: Final[tuple[str, ...]] = ("fake", "codex", "grok_build")

_CANONICAL_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "archive",
        "books_root",
        "staging_root",
        "season_root",
        "workspaces",
        "calendar",
        "universe",
        "registrations",
        "duties",
        "round_id",
        "timestamps",
        "vendor",
        "adapters",
    }
)
_TIMESTAMP_NAMES: Final[frozenset[str]] = frozenset(
    {
        "deadline",
        "decided_at",
        "finished_at",
        "marked_at",
        "preflight_finished_at",
        "preflight_started_at",
        "published_at",
        "reference_minute",
        "round_start",
        "run_finished_at",
        "run_started_at",
        "started_at",
        "timestamp",
    }
)
_PATH_NAMES: Final[frozenset[str]] = frozenset(
    {
        "archive",
        "archive_root",
        "books_root",
        "calendar",
        "calendar_path",
        "season_root",
        "snapshot",
        "staging_root",
        "workspace",
    }
)


@dataclass(frozen=True)
class OperatorVendor:
    """Registered vendor kind plus construction-neutral JSON options."""

    kind: str
    options: tuple[tuple[str, Any], ...] = ()


@dataclass(frozen=True)
class OperatorSpec:
    """Parsed fields needed by the one-round operator surface."""

    schema_version: str | None
    archive: Path | None
    books_root: Path | None
    staging_root: Path | None
    season_root: Path | None
    workspaces: tuple[tuple[str, Path], ...]
    calendar: Path | None
    universe: tuple[str, ...] | Path | None
    vendor: OperatorVendor
    registrations: tuple[RuntimeRegistration, ...]
    duties: tuple[ReplicaDuty, ...]
    adapters: tuple[tuple[str, str], ...]
    round_id: str | None
    timestamps: tuple[tuple[str, datetime], ...]
    extras: tuple[tuple[str, Any], ...] = ()


def parse_operator_spec(data: Mapping[str, Any] | str | bytes) -> OperatorSpec:
    """Parse the E7 contract or validate one legacy R25 command object."""

    payload = _as_object(data)
    schema_version = _schema_version(payload)
    archive = _optional_path(payload, "archive")
    books_root = _optional_path(payload, "books_root")
    staging_root = _optional_path(payload, "staging_root")
    season_root = _optional_path(payload, "season_root")
    workspaces = _parse_workspaces(payload.get("workspaces"))
    calendar = _optional_path(payload, "calendar")
    universe = _parse_universe(payload.get("universe"))
    vendor = _parse_vendor(payload.get("vendor"))
    registrations = _parse_registrations(payload.get("registrations"))
    duties = _parse_duties(payload.get("duties"))
    adapters = _parse_adapters(payload.get("adapters"), payload, registrations, duties)
    round_id = _parse_round(payload.get("round_id"))
    timestamps = _parse_timestamps(payload.get("timestamps"))
    _validate_legacy_fields(payload)

    extras = tuple(
        (key, value)
        for key, value in sorted(payload.items())
        if key not in _CANONICAL_FIELDS
    )
    return OperatorSpec(
        schema_version=schema_version,
        archive=archive,
        books_root=books_root,
        staging_root=staging_root,
        season_root=season_root,
        workspaces=workspaces,
        calendar=calendar,
        universe=universe,
        vendor=vendor,
        registrations=registrations,
        duties=duties,
        adapters=adapters,
        round_id=round_id,
        timestamps=timestamps,
        extras=extras,
    )


def operator_spec_to_dict(spec: OperatorSpec) -> dict[str, Any]:
    """Return the stable JSON-ready operator object."""

    if not isinstance(spec, OperatorSpec):
        raise TypeError("expected OperatorSpec")
    payload: dict[str, Any] = {}
    if spec.schema_version is not None:
        payload["schema_version"] = spec.schema_version
    for name in ("archive", "books_root", "staging_root", "season_root"):
        value = getattr(spec, name)
        if value is not None:
            payload[name] = str(value)
    if spec.workspaces:
        payload["workspaces"] = {
            replica_id: str(path) for replica_id, path in spec.workspaces
        }
    if spec.calendar is not None:
        payload["calendar"] = str(spec.calendar)
    if isinstance(spec.universe, Path):
        payload["universe"] = str(spec.universe)
    elif spec.universe is not None:
        payload["universe"] = list(spec.universe)
    payload["vendor"] = {
        "kind": spec.vendor.kind,
        **{key: _json_ready(value) for key, value in spec.vendor.options},
    }
    if spec.registrations:
        payload["registrations"] = [
            runtime_registration_to_dict(item) for item in spec.registrations
        ]
    if spec.duties:
        payload["duties"] = [
            {
                "product_id": item.product_id,
                "replica_id": item.replica_id,
                "status": item.status,
            }
            for item in spec.duties
        ]
    if spec.adapters:
        payload["adapters"] = dict(spec.adapters)
    if spec.round_id is not None:
        payload["round_id"] = spec.round_id
    if spec.timestamps:
        payload["timestamps"] = {
            name: format_et_timestamp(value) for name, value in spec.timestamps
        }
    for key, value in spec.extras:
        payload[key] = _json_ready(value)
    return payload


def dump_operator_spec(spec: OperatorSpec) -> str:
    """Dump a canonical operator spec with a trailing newline."""

    canonical = parse_operator_spec(operator_spec_to_dict(spec))
    return dump_json(operator_spec_to_dict(canonical))


def _as_object(data: Mapping[str, Any] | str | bytes) -> dict[str, Any]:
    if isinstance(data, bytes):
        try:
            data = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SchemaError("$", "invalid UTF-8") from exc
    if isinstance(data, str):
        try:
            value = json.loads(data)
        except json.JSONDecodeError as exc:
            raise SchemaError("$", f"invalid JSON: {exc.msg}") from exc
        if not isinstance(value, dict):
            raise SchemaError("$", "expected a JSON object")
        return value
    if isinstance(data, dict):
        return data
    raise SchemaError("$", "expected a JSON object")


def _schema_version(payload: Mapping[str, Any]) -> str | None:
    if "schema_version" not in payload:
        return None
    value = _text(payload["schema_version"], path="schema_version")
    if value != SCHEMA_VERSION:
        raise SchemaError("schema_version", f"unsupported schema_version {value!r}")
    return value


def _optional_path(payload: Mapping[str, Any], key: str) -> Path | None:
    if key not in payload:
        return None
    return _absolute_path(payload[key], path=key)


def _absolute_path(value: object, *, path: str) -> Path:
    if not isinstance(value, (str, Path)):
        raise SchemaError(path, "expected a path string")
    candidate = Path(value)
    if not candidate.is_absolute():
        raise SchemaError(path, "must be absolute")
    if ".." in candidate.parts:
        raise SchemaError(path, "must be resolved")
    return candidate


def _parse_workspaces(value: object) -> tuple[tuple[str, Path], ...]:
    if value is None:
        return ()
    if not isinstance(value, dict):
        raise SchemaError("workspaces", "expected an object")
    if not value:
        raise SchemaError("workspaces", "must contain at least one replica")
    return tuple(
        (
            _text(replica_id, path=f"workspaces.{replica_id}"),
            _absolute_path(path, path=f"workspaces.{replica_id}"),
        )
        for replica_id, path in sorted(value.items())
    )


def _parse_universe(value: object) -> tuple[str, ...] | Path | None:
    if value is None:
        return None
    if isinstance(value, (str, Path)):
        return _absolute_path(value, path="universe")
    if not isinstance(value, list):
        raise SchemaError("universe", "expected a symbol list or absolute path")
    if not value:
        raise SchemaError("universe", "must contain at least one symbol")
    symbols: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        path = f"universe.{index}"
        symbol = _text(item, path=path)
        if symbol in seen:
            raise SchemaError(path, "duplicate symbol")
        seen.add(symbol)
        symbols.append(symbol)
    return tuple(symbols)


def _parse_vendor(value: object) -> OperatorVendor:
    if value is None:
        return OperatorVendor(kind="fixture")
    if isinstance(value, (str, Path)):
        return OperatorVendor(
            kind="fixture",
            options=(("root", _absolute_path(value, path="vendor")),),
        )
    if not isinstance(value, dict):
        raise SchemaError("vendor", "expected a path string or object")
    kind = _text(value.get("kind"), path="vendor.kind")
    if kind not in VENDOR_KINDS:
        raise SchemaError("vendor.kind", f"must be one of {', '.join(VENDOR_KINDS)}")
    options: dict[str, Any] = {}
    for key, item in value.items():
        if key == "kind":
            continue
        option = _text(key, path="vendor")
        if option in {"path", "root"}:
            canonical = "root"
            if canonical in options:
                raise SchemaError("vendor.root", "duplicate path option")
            options[canonical] = _absolute_path(item, path=f"vendor.{option}")
        elif option == "api_key_path":
            options[option] = _absolute_path(item, path="vendor.api_key_path")
        else:
            options[option] = item
    return OperatorVendor(kind=kind, options=tuple(sorted(options.items())))


def _parse_registrations(value: object) -> tuple[RuntimeRegistration, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise SchemaError("registrations", "expected a list")
    if not value:
        raise SchemaError("registrations", "must contain at least one product")
    registrations: list[RuntimeRegistration] = []
    for index, item in enumerate(value):
        path = f"registrations.{index}"
        source: object = item
        if isinstance(item, (str, Path)):
            registration_path = _absolute_path(item, path=path)
            if not registration_path.is_file():
                raise SchemaError(path, "file not found")
            try:
                source = registration_path.read_text(encoding="utf-8")
            except OSError as exc:
                raise SchemaError(path, "cannot read file") from exc
        try:
            registration = parse_runtime_registration(source)  # type: ignore[arg-type]
        except SchemaError as exc:
            raise _prefixed(path, exc) from exc
        if registration.adapter_id not in ADAPTER_IDS:
            raise SchemaError(
                f"{path}.adapter_id",
                f"must be one of {', '.join(ADAPTER_IDS)}",
            )
        registrations.append(registration)
    return tuple(registrations)


def _parse_duties(value: object) -> tuple[ReplicaDuty, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise SchemaError("duties", "expected a list")
    if not value:
        raise SchemaError("duties", "must contain at least one replica")
    duties: list[ReplicaDuty] = []
    for index, item in enumerate(value):
        path = f"duties.{index}"
        if not isinstance(item, dict):
            raise SchemaError(path, "expected an object")
        for key in ("product_id", "replica_id", "status"):
            if key not in item:
                raise SchemaError(f"{path}.{key}", "missing")
        extra = next(
            (key for key in item if key not in {"product_id", "replica_id", "status"}),
            None,
        )
        if extra is not None:
            raise SchemaError(f"{path}.{extra}", "unknown field")
        try:
            duty = ReplicaDuty(item["product_id"], item["replica_id"], item["status"])
        except OrchestratorError as exc:
            raise _prefixed(path, exc) from exc
        duties.append(duty)
    return tuple(duties)


def _parse_adapters(
    value: object,
    payload: Mapping[str, Any],
    registrations: tuple[RuntimeRegistration, ...],
    duties: tuple[ReplicaDuty, ...],
) -> tuple[tuple[str, str], ...]:
    if value is not None and not isinstance(value, dict):
        raise SchemaError("adapters", "expected a product-to-adapter object")
    adapters: dict[str, str] = {}
    if isinstance(value, dict):
        for product_id, raw_adapter in value.items():
            product = _text(product_id, path=f"adapters.{product_id}")
            adapter = _text(raw_adapter, path=f"adapters.{product}")
            if adapter not in ADAPTER_IDS:
                raise SchemaError(
                    f"adapters.{product}",
                    f"must be one of {', '.join(ADAPTER_IDS)}",
                )
            adapters[product] = adapter
    products = {item.product_id for item in registrations}
    products.update(item.product_id for item in duties)
    raw_products = payload.get("product_ids")
    if isinstance(raw_products, list):
        products.update(
            _text(item, path=f"product_ids.{index}")
            for index, item in enumerate(raw_products)
        )
    for product in products:
        adapters.setdefault(product, "fake")
    return tuple(sorted(adapters.items()))


def _parse_round(value: object) -> str | None:
    if value is None:
        return None
    try:
        return parse_round_id(value, path="round_id")  # type: ignore[arg-type]
    except SchemaError:
        raise
    except (TypeError, ValueError) as exc:
        raise SchemaError("round_id", str(exc)) from exc


def _parse_timestamps(value: object) -> tuple[tuple[str, datetime], ...]:
    if value is None:
        return ()
    if not isinstance(value, dict):
        raise SchemaError("timestamps", "expected an object")
    if not value:
        raise SchemaError("timestamps", "must contain at least one timestamp")
    return tuple(
        (
            _text(name, path="timestamps"),
            _timestamp(raw, path=f"timestamps.{name}"),
        )
        for name, raw in sorted(value.items())
    )


def _validate_legacy_fields(value: object, *, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            child = join_path(path, str(key))
            if path == "$" and key == "books" and isinstance(item, dict):
                for replica_id, book_path in item.items():
                    _absolute_path(book_path, path=f"books.{replica_id}")
            elif key in _PATH_NAMES and item is not None:
                _absolute_path(item, path=child)
            elif key in _TIMESTAMP_NAMES or key.endswith("_at"):
                _timestamp(item, path=child)
            _validate_legacy_fields(item, path=child)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _validate_legacy_fields(item, path=join_path(path, str(index)))


def _timestamp(value: object, *, path: str) -> datetime:
    if not isinstance(value, str):
        raise SchemaError(path, "expected an ISO-8601 string")
    try:
        return parse_et_timestamp(value)
    except ValueError as exc:
        raise SchemaError(path, str(exc)) from exc


def _text(value: object, *, path: str) -> str:
    if not isinstance(value, str):
        raise SchemaError(path, "expected a string")
    if not value or value.strip() != value:
        raise SchemaError(path, "must be a non-empty string without padding")
    return value


def _prefixed(parent: str, error: OrchestratorError | SchemaError) -> SchemaError:
    path = parent if error.path == "$" else join_path(parent, error.path)
    return SchemaError(path, error.message)


def _json_ready(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return format_et_timestamp(value)
    if isinstance(value, dict):
        return {key: _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    return value
