"""R3: ineligible or ambiguous runtime registrations fail by field path."""

from typing import Any, Callable

import pytest

from arena_kernel.schema.errors import SchemaError
from arena_runtime.registration import parse_runtime_registration

from conftest import valid_registration


Mutation = Callable[[dict[str, Any]], None]


def _set_auth_api_key(payload: dict[str, Any]) -> None:
    payload["authentication_method"] = "api_key"


def _enable_routing(payload: dict[str, Any]) -> None:
    payload["automatic_routing"] = True


def _duplicate_replica(payload: dict[str, Any]) -> None:
    payload["replica_ids"] = ["product-a-1", "product-a-1"]


def _remove_exact_model(payload: dict[str, Any]) -> None:
    del payload["exact_model"]


def _blank_exact_model(payload: dict[str, Any]) -> None:
    payload["exact_model"] = ""


def _remove_cli_version(payload: dict[str, Any]) -> None:
    del payload["expected_cli_version"]


def _blank_cli_version(payload: dict[str, Any]) -> None:
    payload["expected_cli_version"] = " "


@pytest.mark.parametrize(
    ("mutate", "path"),
    [
        (_set_auth_api_key, "authentication_method"),
        (_enable_routing, "automatic_routing"),
        (_duplicate_replica, "replica_ids.1"),
        (_remove_exact_model, "exact_model"),
        (_blank_exact_model, "exact_model"),
        (_remove_cli_version, "expected_cli_version"),
        (_blank_cli_version, "expected_cli_version"),
    ],
)
def test_required_r3_rejections_name_the_field(
    mutate: Mutation,
    path: str,
) -> None:
    payload = valid_registration()
    mutate(payload)

    with pytest.raises(SchemaError) as exc:
        parse_runtime_registration(payload)

    assert exc.value.path == path


@pytest.mark.parametrize(
    ("field", "value", "path"),
    [
        ("product_id", "", "product_id"),
        ("provider_id", " provider", "provider_id"),
        ("adapter_id", 3, "adapter_id"),
        ("subscription_tier", "", "subscription_tier"),
        ("reasoning_mode", "", "reasoning_mode"),
        ("automatic_routing", 0, "automatic_routing"),
        ("replica_ids", [], "replica_ids"),
        ("provider_documentation_url", "http://docs.example.test", "provider_documentation_url"),
        ("provider_documentation_retrieved_on", "2026-02-30", "provider_documentation_retrieved_on"),
    ],
)
def test_other_invalid_registration_fields_fail_by_path(
    field: str,
    value: object,
    path: str,
) -> None:
    payload = valid_registration()
    payload[field] = value

    with pytest.raises(SchemaError) as exc:
        parse_runtime_registration(payload)

    assert exc.value.path == path


def test_missing_capability_fails_at_nested_path() -> None:
    payload = valid_registration()
    del payload["capabilities"]["native_subagents"]

    with pytest.raises(SchemaError) as exc:
        parse_runtime_registration(payload)

    assert exc.value.path == "capabilities.native_subagents"


def test_disabled_required_capability_is_ineligible() -> None:
    payload = valid_registration()
    payload["capabilities"]["resumable_sessions"] = False

    with pytest.raises(SchemaError) as exc:
        parse_runtime_registration(payload)

    assert exc.value.path == "capabilities.resumable_sessions"


def test_unknown_field_is_rejected() -> None:
    payload = valid_registration()
    payload["monthly_price"] = "20.00"

    with pytest.raises(SchemaError) as exc:
        parse_runtime_registration(payload)

    assert exc.value.path == "monthly_price"
