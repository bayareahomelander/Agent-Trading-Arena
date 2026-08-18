"""Shared R15 multi-replica Grok Build session fixtures."""

from __future__ import annotations

import base64
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from arena_runtime.adapters.grok_build import (
    GROK_BUILD_DOCUMENTATION_URLS,
    GrokBuildAdapter,
    GrokBuildSessionStore,
)
from arena_runtime.audit import AuditArchive
from arena_runtime.isolation import prepare_replica_launch
from arena_runtime.registration import RuntimeCapabilities, RuntimeRegistration
from arena_runtime.runner import RUNNER_CONTRACT_VERSION, RunnerRequest

FAKE_GROK = Path(__file__).parent / "fixtures" / "fake_grok.py"
EXPECTED_VERSION = "1.0.5"
EXPECTED_MODEL = "registered-grok-model"
EXPECTED_REASONING = "high"
MORNING_PROMPT = b"morning frozen instruction"
LATE_PROMPT = b"late frozen instruction"
MORNING_DECISION = b'{"round_id":"2026-08-17-morning","action":"hold"}\n'
LATE_DECISION = b'{"round_id":"2026-08-17-late","action":"hold"}\n'

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
AGENT_HELP_ITEMS = ["stdio"]


def make_registration(replica_ids: tuple[str, ...]) -> RuntimeRegistration:
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
        replica_ids=replica_ids,
        capabilities=RuntimeCapabilities(True, True, True, True, True),
        provider_documentation_url=GROK_BUILD_DOCUMENTATION_URLS[0],
        provider_documentation_retrieved_on=date(2026, 8, 18),
    )


def create_workspace(season: Path, replica_id: str) -> Path:
    workspace = season / "replicas" / replica_id
    (workspace / "state" / "market").mkdir(parents=True)
    (workspace / "agent" / "notes").mkdir(parents=True)
    (workspace / "agent" / "research").mkdir()
    (workspace / "agent" / "tools").mkdir()
    (workspace / "outbox").mkdir()
    (workspace / "RULES.md").write_text("rules\n", encoding="utf-8")
    (workspace / "PROMPT.md").write_text("prompt\n", encoding="utf-8")
    (workspace / "state" / "portfolio.json").write_text("{}\n", encoding="utf-8")
    return workspace.resolve()


def host_environment() -> dict[str, str]:
    environment: dict[str, str] = {}
    for key in ("PATH", "PATHEXT", "SystemRoot", "TEMP", "TMP", "WINDIR"):
        value = os.environ.get(key)
        if value is not None:
            environment[key] = value
    return environment


def scenario(
    workspace: Path,
    session_id: str,
    **changes: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "command_log_path": str(workspace / "agent" / "notes" / "commands.jsonl"),
        "capture_log_path": str(workspace / "agent" / "notes" / "runs.jsonl"),
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
        "session_id": session_id,
        "decisions": {
            MORNING_PROMPT.decode(): base64.b64encode(MORNING_DECISION).decode(),
            LATE_PROMPT.decode(): base64.b64encode(LATE_DECISION).decode(),
        },
    }
    payload.update(changes)
    return payload


def build_adapter(
    root: Path,
    *,
    replica_id: str,
    registration: RuntimeRegistration,
    session_store: GrokBuildSessionStore,
    archive: AuditArchive,
    session_id: str,
    scenario_changes: dict[str, Any] | None = None,
) -> tuple[GrokBuildAdapter, Path, Path]:
    season = root / "season"
    workspace = create_workspace(season, replica_id)
    credentials = root / f"credentials-{replica_id}"
    credentials.mkdir()
    launch = prepare_replica_launch(
        season.resolve(),
        replica_id,
        credential_store=credentials.resolve(),
        host_environment=host_environment(),
    )
    scenario_payload = scenario(
        workspace,
        session_id,
        **({} if scenario_changes is None else scenario_changes),
    )
    scenario_path = root / f"scenario-{replica_id}.json"
    scenario_path.write_text(
        json.dumps(scenario_payload, indent=2) + "\n",
        encoding="utf-8",
    )
    adapter = GrokBuildAdapter(
        registration,
        launch,
        archive=archive,
        session_store=session_store,
        executable_name=sys.executable,
        executable_prefix=(str(FAKE_GROK), str(scenario_path)),
    )
    return adapter, workspace, scenario_path


def request(
    workspace: Path,
    replica_id: str,
    *,
    round_id: str,
    prompt: bytes,
    session_reference: str | None = None,
) -> RunnerRequest:
    return RunnerRequest(
        contract_version=RUNNER_CONTRACT_VERSION,
        product_id="grok-product",
        replica_id=replica_id,
        round_id=round_id,
        workspace=workspace,
        model_reference=EXPECTED_MODEL,
        configuration_reference="registration:grok_build",
        launch_instruction=prompt,
        deadline=datetime.now(timezone.utc) + timedelta(seconds=20),
        session_reference=session_reference,
    )
