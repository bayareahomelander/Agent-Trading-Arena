"""Shared R9 registration, workspace, request, and fake CLI fixtures."""

from __future__ import annotations

import json
import os
import sys
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from arena_runtime.adapters.codex import CODEX_DOCUMENTATION_URLS, CodexAdapter
from arena_runtime.audit import AuditArchive
from arena_runtime.isolation import prepare_replica_launch
from arena_runtime.registration import (
    RuntimeCapabilities,
    RuntimeRegistration,
)
from arena_runtime.runner import RUNNER_CONTRACT_VERSION, RunnerRequest

FAKE_CODEX = Path(__file__).parent / "fixtures" / "fake_codex.py"
EXPECTED_VERSION = "0.144.5"
EXPECTED_MODEL = "registered-codex-model"
EXPECTED_REASONING = "high"

EXEC_HELP_ITEMS = [
    "--config",
    "--ignore-rules",
    "--ignore-user-config",
    "--json",
    "--model",
    "--output-schema",
    "--skip-git-repo-check",
    "--strict-config",
    "resume",
]


def _check(status: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "id": "synthetic",
        "category": "synthetic",
        "status": status,
        "summary": "synthetic",
        "details": {} if details is None else details,
        "remediation": None,
        "durationMs": 0,
    }


def valid_scenario(log_path: Path) -> dict[str, Any]:
    return deepcopy(
        {
            "log_path": str(log_path),
            "version": EXPECTED_VERSION,
            "login_output": "Logged in using ChatGPT",
            "login_exit": 0,
            "exec_help_items": EXEC_HELP_ITEMS,
            "doctor": {
                "schemaVersion": 1,
                "generatedAt": "2026-08-17T10:00:00Z",
                "overallStatus": "ok",
                "codexVersion": EXPECTED_VERSION,
                "checks": {
                    "installation": _check("ok"),
                    "auth.credentials": _check(
                        "ok",
                        {
                            "stored auth mode": "chatgpt",
                            "stored API key": "false",
                            "stored ChatGPT tokens": "true",
                        },
                    ),
                    "config.load": _check(
                        "ok",
                        {
                            "model": EXPECTED_MODEL,
                            "model provider": "openai",
                            "model reasoning effort": EXPECTED_REASONING,
                            "automatic routing": "false",
                        },
                    ),
                    "network.provider_reachability": _check("ok"),
                },
            },
        }
    )


def make_registration() -> RuntimeRegistration:
    return RuntimeRegistration(
        schema_version="1",
        product_id="codex-product",
        provider_id="openai",
        adapter_id="codex",
        subscription_tier="individual-usd-20",
        authentication_method="subscription",
        exact_model=EXPECTED_MODEL,
        reasoning_mode=EXPECTED_REASONING,
        automatic_routing=False,
        expected_cli_version=EXPECTED_VERSION,
        replica_ids=("codex-product-1",),
        capabilities=RuntimeCapabilities(
            web_research=True,
            shell_execution=True,
            persistent_workspace=True,
            resumable_sessions=True,
            native_subagents=True,
        ),
        provider_documentation_url=CODEX_DOCUMENTATION_URLS[0],
        provider_documentation_retrieved_on=date(2026, 8, 17),
    )


def make_case(
    root: Path,
    scenario: dict[str, Any] | None = None,
    *,
    executable_name: str | None = None,
) -> tuple[CodexAdapter, RunnerRequest, AuditArchive, Path, Path]:
    season = root / "season"
    workspace = season / "replicas" / "codex-product-1"
    (workspace / "state" / "market").mkdir(parents=True)
    (workspace / "agent" / "notes").mkdir(parents=True)
    (workspace / "agent" / "research").mkdir()
    (workspace / "agent" / "tools").mkdir()
    (workspace / "outbox").mkdir()
    (workspace / "RULES.md").write_text("rules\n", encoding="utf-8")
    (workspace / "PROMPT.md").write_text("prompt\n", encoding="utf-8")
    (workspace / "state" / "portfolio.json").write_text('{}\n', encoding="utf-8")
    credential_store = root / "codex-credentials"
    credential_store.mkdir()

    host_environment = {"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    for key in ("PATH", "PATHEXT", "SystemRoot", "TEMP", "TMP", "WINDIR"):
        value = os.environ.get(key)
        if value is not None:
            host_environment[key] = value
    launch = prepare_replica_launch(
        season.resolve(),
        "codex-product-1",
        credential_store=credential_store.resolve(),
        host_environment=host_environment,
    )
    archive = AuditArchive(root / "archive")
    scenario_path = root / "scenario.json"
    log_path = workspace / "agent" / "notes" / "fake-codex-commands.jsonl"
    resolved_scenario = valid_scenario(log_path) if scenario is None else scenario
    resolved_scenario["log_path"] = str(log_path)
    scenario_path.write_text(
        json.dumps(resolved_scenario, indent=2) + "\n",
        encoding="utf-8",
    )
    adapter = CodexAdapter(
        make_registration(),
        launch,
        archive=archive,
        executable_name=sys.executable if executable_name is None else executable_name,
        executable_prefix=(str(FAKE_CODEX), str(scenario_path)),
    )
    request = RunnerRequest(
        contract_version=RUNNER_CONTRACT_VERSION,
        product_id="codex-product",
        replica_id="codex-product-1",
        round_id="2026-08-17-morning",
        workspace=workspace.resolve(),
        model_reference=EXPECTED_MODEL,
        configuration_reference="registration:codex",
        launch_instruction=b"Frozen launch instruction",
        deadline=datetime.now(timezone.utc) + timedelta(seconds=15),
        session_reference=None,
    )
    return adapter, request, archive, scenario_path, log_path
