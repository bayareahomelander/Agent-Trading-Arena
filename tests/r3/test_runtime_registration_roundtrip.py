"""R3: valid frozen registrations dump and parse byte-stably."""

from dataclasses import FrozenInstanceError
from datetime import date

import pytest

from arena_runtime.registration import (
    CAPABILITY_NAMES,
    SUBSCRIPTION_AUTHENTICATION,
    RuntimeRegistration,
    dump_runtime_registration,
    parse_runtime_registration,
    runtime_registration_to_dict,
)

from .conftest import valid_registration


def test_registration_parses_every_frozen_runtime_field() -> None:
    registration = parse_runtime_registration(valid_registration())

    assert registration.schema_version == "1"
    assert registration.product_id == "product-a"
    assert registration.provider_id == "provider-a"
    assert registration.adapter_id == "adapter-a"
    assert registration.subscription_tier == "individual-usd-20"
    assert registration.authentication_method == SUBSCRIPTION_AUTHENTICATION
    assert registration.exact_model == "registered-model-a"
    assert registration.reasoning_mode == "registered-stable-mode"
    assert registration.automatic_routing is False
    assert registration.expected_cli_version == "1.2.3"
    assert registration.replica_ids == ("product-a-1", "product-a-2")
    assert registration.provider_documentation_retrieved_on == date(2026, 8, 17)


def test_registration_and_capabilities_are_frozen() -> None:
    registration = parse_runtime_registration(valid_registration())

    with pytest.raises(FrozenInstanceError):
        registration.exact_model = "other"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        registration.capabilities.web_research = False  # type: ignore[misc]


def test_capability_names_are_the_protocol_categories() -> None:
    assert CAPABILITY_NAMES == (
        "web_research",
        "shell_execution",
        "persistent_workspace",
        "resumable_sessions",
        "native_subagents",
    )


def test_dump_parse_round_trip_is_stable() -> None:
    first = parse_runtime_registration(valid_registration())
    first_dump = dump_runtime_registration(first)
    second = parse_runtime_registration(first_dump.encode("utf-8"))
    second_dump = dump_runtime_registration(second)

    assert second == first
    assert second_dump == first_dump
    assert first_dump.endswith("\n")


def test_dump_field_order_is_frozen() -> None:
    registration = parse_runtime_registration(valid_registration())

    assert tuple(runtime_registration_to_dict(registration)) == (
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


def test_to_dict_uses_json_values_not_dataclass_objects() -> None:
    registration = parse_runtime_registration(valid_registration())
    payload = runtime_registration_to_dict(registration)

    assert payload["replica_ids"] == ["product-a-1", "product-a-2"]
    assert payload["capabilities"] == valid_registration()["capabilities"]
    assert payload["provider_documentation_retrieved_on"] == "2026-08-17"
    assert isinstance(registration, RuntimeRegistration)
