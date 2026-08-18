"""Frozen runtime product registration schema.

R3 parses and dumps the provider-neutral execution fields frozen before a
season. It does not inspect an installed CLI, authentication state, or any
provider service.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Final, Mapping
from urllib.parse import urlsplit

from arena_kernel.schema._dump import dump_json
from arena_kernel.schema._parse import (
    SCHEMA_VERSION,
    as_mapping,
    join_path,
    require_list,
    require_object,
    require_schema_version,
    require_str,
)
from arena_kernel.schema.errors import SchemaError

SUBSCRIPTION_AUTHENTICATION: Final[str] = "subscription"

CAPABILITY_NAMES: Final[tuple[str, ...]] = (
    "web_research",
    "shell_execution",
    "persistent_workspace",
    "resumable_sessions",
    "native_subagents",
)

_REGISTRATION_FIELDS: Final[tuple[str, ...]] = (
    "schema_version",
    "product_id",
    "provider_id",
    "adapter_id",
    "subscription_tier",
    "authentication_method",
    "exact_model",
    "reasoning_mode",
    "automatic_routing",
    "expected_cli_version",
    "replica_ids",
    "capabilities",
    "provider_documentation_url",
    "provider_documentation_retrieved_on",
)


@dataclass(frozen=True)
class RuntimeCapabilities:
    """Protocol-required native capability flags for one product."""

    web_research: bool
    shell_execution: bool
    persistent_workspace: bool
    resumable_sessions: bool
    native_subagents: bool


@dataclass(frozen=True)
class RuntimeRegistration:
    """Frozen provider-neutral execution registration."""

    schema_version: str
    product_id: str
    provider_id: str
    adapter_id: str
    subscription_tier: str
    authentication_method: str
    exact_model: str
    reasoning_mode: str
    automatic_routing: bool
    expected_cli_version: str
    replica_ids: tuple[str, ...]
    capabilities: RuntimeCapabilities
    provider_documentation_url: str
    provider_documentation_retrieved_on: date


def parse_runtime_registration(
    data: Mapping[str, Any] | str | bytes,
) -> RuntimeRegistration:
    """Parse and validate one frozen runtime registration."""

    payload = as_mapping(data)
    require_object(payload, required=_REGISTRATION_FIELDS)

    authentication_method = require_str(payload, "authentication_method")
    if authentication_method != SUBSCRIPTION_AUTHENTICATION:
        raise SchemaError(
            "authentication_method",
            "must be subscription authentication; API-key mode is prohibited",
        )

    automatic_routing = _require_bool(payload, "automatic_routing")
    if automatic_routing:
        raise SchemaError(
            "automatic_routing",
            "must be false for a frozen exact model",
        )

    replica_ids = _parse_replica_ids(payload)
    capabilities = _parse_capabilities(payload["capabilities"])
    documentation_url = require_str(payload, "provider_documentation_url")
    _require_https_url(documentation_url, path="provider_documentation_url")

    return RuntimeRegistration(
        schema_version=require_schema_version(payload),
        product_id=require_str(payload, "product_id"),
        provider_id=require_str(payload, "provider_id"),
        adapter_id=require_str(payload, "adapter_id"),
        subscription_tier=require_str(payload, "subscription_tier"),
        authentication_method=authentication_method,
        exact_model=require_str(payload, "exact_model"),
        reasoning_mode=require_str(payload, "reasoning_mode"),
        automatic_routing=automatic_routing,
        expected_cli_version=require_str(payload, "expected_cli_version"),
        replica_ids=replica_ids,
        capabilities=capabilities,
        provider_documentation_url=documentation_url,
        provider_documentation_retrieved_on=_require_date(
            payload,
            "provider_documentation_retrieved_on",
        ),
    )


def runtime_registration_to_dict(
    registration: RuntimeRegistration,
) -> dict[str, Any]:
    """Return the stable JSON-ready registration object."""

    return {
        "schema_version": registration.schema_version,
        "product_id": registration.product_id,
        "provider_id": registration.provider_id,
        "adapter_id": registration.adapter_id,
        "subscription_tier": registration.subscription_tier,
        "authentication_method": registration.authentication_method,
        "exact_model": registration.exact_model,
        "reasoning_mode": registration.reasoning_mode,
        "automatic_routing": registration.automatic_routing,
        "expected_cli_version": registration.expected_cli_version,
        "replica_ids": list(registration.replica_ids),
        "capabilities": {
            name: getattr(registration.capabilities, name)
            for name in CAPABILITY_NAMES
        },
        "provider_documentation_url": registration.provider_documentation_url,
        "provider_documentation_retrieved_on": (
            registration.provider_documentation_retrieved_on.isoformat()
        ),
    }


def dump_runtime_registration(registration: RuntimeRegistration) -> str:
    """Dump a byte-stable registration JSON string with a trailing newline."""

    payload = runtime_registration_to_dict(registration)
    canonical = parse_runtime_registration(payload)
    return dump_json(runtime_registration_to_dict(canonical))


def _parse_replica_ids(payload: Mapping[str, Any]) -> tuple[str, ...]:
    raw_ids = require_list(payload, "replica_ids")
    if not raw_ids:
        raise SchemaError("replica_ids", "must contain at least one replica")
    replica_ids: list[str] = []
    seen: set[str] = set()
    for index, value in enumerate(raw_ids):
        path = join_path("replica_ids", str(index))
        if not isinstance(value, str):
            raise SchemaError(path, "expected a string")
        if not value or value.strip() != value:
            raise SchemaError(path, "must be a non-empty string without padding")
        if value in seen:
            raise SchemaError(path, "duplicate replica_id")
        seen.add(value)
        replica_ids.append(value)
    return tuple(replica_ids)


def _parse_capabilities(value: Any) -> RuntimeCapabilities:
    path = "capabilities"
    if not isinstance(value, dict):
        raise SchemaError(path, "expected an object")
    require_object(value, required=CAPABILITY_NAMES, path=path)
    flags: dict[str, bool] = {}
    for name in CAPABILITY_NAMES:
        flag = _require_bool(value, name, path=path)
        if not flag:
            raise SchemaError(
                join_path(path, name),
                "must be enabled for an eligible product",
            )
        flags[name] = flag
    return RuntimeCapabilities(**flags)


def _require_bool(
    data: Mapping[str, Any],
    key: str,
    *,
    path: str = "$",
) -> bool:
    value = data[key]
    field = join_path(path, key)
    if not isinstance(value, bool):
        raise SchemaError(field, "expected a boolean")
    return value


def _require_https_url(value: str, *, path: str) -> None:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname:
        raise SchemaError(path, "must be an absolute HTTPS URL")
    if parsed.username is not None or parsed.password is not None:
        raise SchemaError(path, "must not contain credentials")


def _require_date(data: Mapping[str, Any], key: str) -> date:
    value = require_str(data, key)
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise SchemaError(key, "must be a valid YYYY-MM-DD date") from exc
    if parsed.isoformat() != value:
        raise SchemaError(key, "must be a valid YYYY-MM-DD date")
    return parsed
