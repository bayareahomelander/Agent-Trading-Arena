"""R13: every required Grok Build readiness failure maps to one named reason."""

from pathlib import Path
from typing import Any, Callable

import pytest

from .conftest import EXPECTED_MODEL, HELP_ITEMS, valid_scenario, make_case


Mutation = Callable[[dict[str, Any]], None]


def _version_mismatch(scenario: dict[str, Any]) -> None:
    scenario["version"] = {
        "currentVersion": "9.9.9 (deadbeef)",
        "channel": "stable",
    }


def _unauthenticated(scenario: dict[str, Any]) -> None:
    scenario["models_output"] = (
        "You are not authenticated.\n"
        "\n"
        f"Default model: {EXPECTED_MODEL}\n"
        "\n"
        "Available models:\n"
        f"  * {EXPECTED_MODEL} (default)\n"
    )


def _api_key_auth(scenario: dict[str, Any]) -> None:
    scenario["models_output"] = (
        "You are using XAI_API_KEY.\n"
        "\n"
        f"Default model: {EXPECTED_MODEL}\n"
        "\n"
        "Available models:\n"
        f"  * {EXPECTED_MODEL} (default)\n"
    )


def _model_mismatch(scenario: dict[str, Any]) -> None:
    scenario["models_output"] = (
        "You are logged in with grok.com.\n"
        "\n"
        "Default model: other-model\n"
        "\n"
        "Available models:\n"
        "  * other-model (default)\n"
    )


def _reasoning_mismatch(scenario: dict[str, Any]) -> None:
    scenario["inspect"]["defaultReasoningEffort"] = "low"


def _routing_enabled(scenario: dict[str, Any]) -> None:
    scenario["inspect"]["automaticRouting"] = True


def _provider_unavailable(scenario: dict[str, Any]) -> None:
    scenario["models_output"] = (
        "You are logged in with grok.com.\n"
        "\n"
        "Unable to reach the xAI service.\n"
    )
    scenario["models_exit"] = 1


def _missing_structured_interface(scenario: dict[str, Any]) -> None:
    scenario["help_items"] = [
        item for item in HELP_ITEMS if item != "streaming-json"
    ]


def _invalid_inspect(scenario: dict[str, Any]) -> None:
    scenario["inspect_invalid"] = True


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (_version_mismatch, "grok_build_version_mismatch"),
        (_unauthenticated, "grok_build_unauthenticated"),
        (_api_key_auth, "grok_build_api_key_authentication"),
        (_model_mismatch, "grok_build_model_mismatch"),
        (_reasoning_mismatch, "grok_build_reasoning_mismatch"),
        (_routing_enabled, "grok_build_routing_enabled"),
        (_provider_unavailable, "grok_build_provider_unavailable"),
        (_missing_structured_interface, "grok_build_structured_interface_missing"),
        (_invalid_inspect, "grok_build_inspect_invalid"),
    ],
)
def test_preflight_failure_is_normalized(
    tmp_path: Path,
    mutate: Mutation,
    reason: str,
) -> None:
    scenario = valid_scenario(tmp_path / "placeholder.log")
    mutate(scenario)
    adapter, request, _, _, _ = make_case(tmp_path, scenario)

    result = adapter.preflight(request)

    assert result.ready is False
    assert result.failure_reason == reason
    assert adapter.last_capabilities is None


def test_missing_grok_executable_fails_without_running_a_probe(tmp_path: Path) -> None:
    missing = str((tmp_path / "missing" / "grok.exe").resolve())
    adapter, request, _, _, command_log = make_case(
        tmp_path,
        executable_name=missing,
    )

    result = adapter.preflight(request)

    assert result.ready is False
    assert result.failure_reason == "grok_build_executable_missing"
    assert not command_log.exists()
