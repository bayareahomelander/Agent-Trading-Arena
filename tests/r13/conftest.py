"""Shared R13 registration, workspace, request, and fake CLI fixtures."""

from __future__ import annotations

import json
import os
import sys
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from arena_runtime.adapters.grok_build import (
    GROK_BUILD_DOCUMENTATION_URLS,
    GrokBuildAdapter,
)
from arena_runtime.audit import AuditArchive
from arena_runtime.isolation import prepare_replica_launch
from arena_runtime.registration import RuntimeCapabilities, RuntimeRegistration
from arena_runtime.runner import RUNNER_CONTRACT_VERSION, RunnerRequest

FAKE_GROK = Path(__file__).parent / "fixtures" / "fake_grok.py"
EXPECTED_VERSION = "1.0.5"
EXPECTED_MODEL = "registered-grok-model"
EXPECTED_REASONING = "high"

HELP_ITEMS = [
    "--single",
    "--output-format",
    "json",
    "streaming-json",
    "--model",
    "--resume",
    "--cwd",
    "--reasoning-effort",
    "agent",
]
AGENT_HELP_ITEMS = [
    "stdio",
]


def valid_scenario(log_path: Path) -> dict[str, Any]:
    return deepcopy(
        {
            "log_path": str(log_path),
            "version": {
                "currentVersion": f"{EXPECTED_VERSION} (5115b46bc9)",
                "channel": "stable",
            },
            "models_output": (
                "You are logged in with grok.com.\n"
                "\n"
                f"Default model: {EXPECTED_MODEL}\n"
                "\n"
                "Available models:\n"
                f"  * {EXPECTED_MODEL} (default)\n"
            ),
            "help_items": HELP_ITEMS,
            "agent_help_items": AGENT_HELP_ITEMS,
            "inspect": {
                "grokVersion": EXPECTED_VERSION,
                "channel": "stable",
                "loginPolicy": {
                    "disableApiKeyAuth": None,
                    "forceLoginTeamUuid": None,
                    "apiKeyAuthDisabled": False,
                },
            },
        }
    )


def make_registration() -> RuntimeRegistration:
    return RuntimeRegistration(
        schema_version="1",
        product_id="grok-product",
        provider_id="xai",
        adapter_id="grok_build",
        subscription_tier="individual-usd-20",
        authentication_method="subscription",
        exact_model=EXPECTED_MODEL,
        reasoning_mode=EXPECTED_REASONING,
        automatic_routing=False,
        expected_cli_version=EXPECTED_VERSION,
        replica_ids=("grok-product-1",),
        capabilities=RuntimeCapabilities(
            web_research=True,
            shell_execution=True,
            persistent_workspace=True,
            resumable_sessions=True,
            native_subagents=True,
        ),
        provider_documentation_url=GROK_BUILD_DOCUMENTATION_URLS[0],
        provider_documentation_retrieved_on=date(2026, 8, 18),
    )


def make_case(
    root: Path,
    scenario: dict[str, Any] | None = None,
    *,
    executable_name: str | None = None,
) -> tuple[GrokBuildAdapter, RunnerRequest, AuditArchive, Path, Path]:
    season = root / "season"
    workspace = season / "replicas" / "grok-product-1"
    (workspace / "state" / "market").mkdir(parents=True)
    (workspace / "agent" / "notes").mkdir(parents=True)
    (workspace / "agent" / "research").mkdir()
    (workspace / "agent" / "tools").mkdir()
    (workspace / "outbox").mkdir()
    (workspace / "RULES.md").write_text("rules\n", encoding="utf-8")
    (workspace / "PROMPT.md").write_text("prompt\n", encoding="utf-8")
    (workspace / "state" / "portfolio.json").write_text("{}\n", encoding="utf-8")
    credential_store = root / "grok-credentials"
    credential_store.mkdir()

    host_environment = {"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    for key in ("PATH", "PATHEXT", "SystemRoot", "TEMP", "TMP", "WINDIR"):
        value = os.environ.get(key)
        if value is not None:
            host_environment[key] = value
    launch = prepare_replica_launch(
        season.resolve(),
        "grok-product-1",
        credential_store=credential_store.resolve(),
        host_environment=host_environment,
    )
    archive = AuditArchive(root / "archive")
    scenario_path = root / "scenario.json"
    log_path = workspace / "agent" / "notes" / "fake-grok-commands.jsonl"
    resolved_scenario = valid_scenario(log_path) if scenario is None else scenario
    resolved_scenario["log_path"] = str(log_path)
    scenario_path.write_text(
        json.dumps(resolved_scenario, indent=2) + "\n",
        encoding="utf-8",
    )
    adapter = GrokBuildAdapter(
        make_registration(),
        launch,
        archive=archive,
        executable_name=sys.executable if executable_name is None else executable_name,
        executable_prefix=(str(FAKE_GROK), str(scenario_path)),
    )
    request = RunnerRequest(
        contract_version=RUNNER_CONTRACT_VERSION,
        product_id="grok-product",
        replica_id="grok-product-1",
        round_id="2026-08-17-morning",
        workspace=workspace.resolve(),
        model_reference=EXPECTED_MODEL,
        configuration_reference="registration:grok_build",
        launch_instruction=b"Frozen launch instruction",
        deadline=datetime.now(timezone.utc) + timedelta(seconds=15),
        session_reference=None,
    )
    return adapter, request, archive, scenario_path, log_path
