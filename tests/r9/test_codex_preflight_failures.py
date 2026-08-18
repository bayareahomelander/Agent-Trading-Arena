"""R9: every required Codex readiness failure maps to one named reason."""

from pathlib import Path
from typing import Any, Callable

import pytest

from .conftest import EXEC_HELP_ITEMS, valid_scenario, make_case


Mutation = Callable[[dict[str, Any]], None]


def _version_mismatch(scenario: dict[str, Any]) -> None:
    scenario["version"] = "9.9.9"


def _unauthenticated(scenario: dict[str, Any]) -> None:
    scenario["login_output"] = "Not logged in"
    scenario["login_exit"] = 1


def _api_key_auth(scenario: dict[str, Any]) -> None:
    scenario["login_output"] = "Logged in using API key"
    auth = scenario["doctor"]["checks"]["auth.credentials"]
    auth["details"] = {
        "stored auth mode": "apikey",
        "stored API key": "true",
        "stored ChatGPT tokens": "false",
    }


def _model_mismatch(scenario: dict[str, Any]) -> None:
    scenario["doctor"]["checks"]["config.load"]["details"]["model"] = "other"


def _reasoning_mismatch(scenario: dict[str, Any]) -> None:
    scenario["doctor"]["checks"]["config.load"]["details"][
        "model reasoning effort"
    ] = "low"


def _routing_enabled(scenario: dict[str, Any]) -> None:
    scenario["doctor"]["checks"]["config.load"]["details"][
        "automatic routing"
    ] = "true"


def _provider_unavailable(scenario: dict[str, Any]) -> None:
    scenario["doctor"]["checks"]["network.provider_reachability"][
        "status"
    ] = "error"


def _missing_structured_interface(scenario: dict[str, Any]) -> None:
    scenario["exec_help_items"] = [
        item for item in EXEC_HELP_ITEMS if item != "--json"
    ]


def _invalid_doctor(scenario: dict[str, Any]) -> None:
    scenario["doctor_invalid"] = True


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (_version_mismatch, "codex_version_mismatch"),
        (_unauthenticated, "codex_unauthenticated"),
        (_api_key_auth, "codex_api_key_authentication"),
        (_model_mismatch, "codex_model_mismatch"),
        (_reasoning_mismatch, "codex_reasoning_mismatch"),
        (_routing_enabled, "codex_routing_enabled"),
        (_provider_unavailable, "codex_provider_unavailable"),
        (_missing_structured_interface, "codex_structured_interface_missing"),
        (_invalid_doctor, "codex_doctor_invalid"),
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


def test_missing_codex_executable_fails_without_running_a_probe(tmp_path: Path) -> None:
    missing = str((tmp_path / "missing" / "codex.exe").resolve())
    adapter, request, _, _, command_log = make_case(
        tmp_path,
        executable_name=missing,
    )

    result = adapter.preflight(request)

    assert result.ready is False
    assert result.failure_reason == "codex_executable_missing"
    assert not command_log.exists()
