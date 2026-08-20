"""Shared R14 fresh Grok Build execution fixtures."""

from __future__ import annotations

import base64
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from arena_runtime.adapters.grok_build import (
    GROK_BUILD_DOCUMENTATION_URLS,
    GrokBuildAdapter,
)
from arena_runtime.audit import AuditArchive
from arena_runtime.isolation import prepare_replica_launch
from arena_runtime.registration import RuntimeCapabilities, RuntimeRegistration
from arena_runtime.runner import RUNNER_CONTRACT_VERSION, RunnerRequest

FAKE_GROK = Path(__file__).resolve().parents[1] / "fixtures" / "fake_grok.py"
EXPECTED_VERSION = "1.0.5"
EXPECTED_MODEL = "registered-grok-model"
EXPECTED_REASONING = "high"
FROZEN_PROMPT = (
    "Frozen launch instruction.\n"
    "Write only outbox/decision.json; metacharacters stay literal: & | ; $(x) `x`.\n"
    "Unicode stays exact: café."
).encode("utf-8")
EXACT_DECISION = b' {"round_id":"2026-08-17-morning", "broken": }\r\n'

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


def make_case(
    root: Path,
    *,
    decision_bytes: bytes | None = EXACT_DECISION,
    prompt_bytes: bytes = FROZEN_PROMPT,
    run_exit: int = 0,
    run_sleep_seconds: float = 0,
    deadline_seconds: float = 20,
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
    host_environment: dict[str, str] = {}
    for key in ("PATH", "PATHEXT", "SystemRoot", "TEMP", "TMP", "WINDIR"):
        value = os.environ.get(key)
        if value is not None:
            host_environment[key] = value
    launch = prepare_replica_launch(
        season.resolve(),
        "grok-product-1",
        host_environment=host_environment,
    )
    registration = RuntimeRegistration(
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
        capabilities=RuntimeCapabilities(True, True, True, True, True),
        provider_documentation_url=GROK_BUILD_DOCUMENTATION_URLS[0],
        provider_documentation_retrieved_on=date(2026, 8, 18),
    )
    command_log = workspace / "agent" / "notes" / "commands.jsonl"
    run_capture = workspace / "agent" / "notes" / "run-capture.json"
    scenario = {
        "command_log_path": str(command_log),
        "run_capture_path": str(run_capture),
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
        "decision_base64": (
            None
            if decision_bytes is None
            else base64.b64encode(decision_bytes).decode("ascii")
        ),
        "stdout_events": [
            {"type": "text", "data": "wrote outbox/decision.json"},
            {
                "type": "end",
                "stopReason": "end_turn",
                "sessionId": "fresh-grok-session",
            },
        ],
        "stderr_text": "synthetic progress",
        "run_exit": run_exit,
        "run_sleep_seconds": run_sleep_seconds,
    }
    scenario_path = root / "scenario.json"
    scenario_path.write_text(
        json.dumps(scenario, indent=2) + "\n",
        encoding="utf-8",
    )
    archive = AuditArchive(root / "archive")
    adapter = GrokBuildAdapter(
        registration,
        launch,
        archive=archive,
        executable_name=sys.executable,
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
        launch_instruction=prompt_bytes,
        deadline=datetime.now(timezone.utc) + timedelta(seconds=deadline_seconds),
        session_reference=None,
    )
    return adapter, request, archive, run_capture, command_log
