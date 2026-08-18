"""Shared R10 fresh Codex execution fixtures."""

from __future__ import annotations

import base64
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from arena_runtime.adapters.codex import CODEX_DOCUMENTATION_URLS, CodexAdapter
from arena_runtime.audit import AuditArchive
from arena_runtime.isolation import prepare_replica_launch
from arena_runtime.registration import RuntimeCapabilities, RuntimeRegistration
from arena_runtime.runner import RUNNER_CONTRACT_VERSION, RunnerRequest

FAKE_CODEX = Path(__file__).parent / "fixtures" / "fake_codex.py"
EXPECTED_VERSION = "0.144.5"
EXPECTED_MODEL = "registered-codex-model"
EXPECTED_REASONING = "high"
FROZEN_PROMPT = (
    "Frozen launch instruction.\n"
    "Write only outbox/decision.json; metacharacters stay literal: & | ; $(x) `x`.\n"
    "Unicode stays exact: café."
).encode("utf-8")
EXACT_DECISION = b' {"round_id":"2026-08-17-morning", "broken": }\r\n'

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


def _check(status: str, details: dict[str, object] | None = None) -> dict[str, object]:
    return {
        "status": status,
        "details": {} if details is None else details,
    }


def make_case(
    root: Path,
    *,
    decision_bytes: bytes | None = EXACT_DECISION,
    prompt_bytes: bytes = FROZEN_PROMPT,
    run_exit: int = 0,
    run_sleep_seconds: float = 0,
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
    host_environment: dict[str, str] = {}
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
    registration = RuntimeRegistration(
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
        capabilities=RuntimeCapabilities(True, True, True, True, True),
        provider_documentation_url=CODEX_DOCUMENTATION_URLS[0],
        provider_documentation_retrieved_on=date(2026, 8, 17),
    )
    command_log = workspace / "agent" / "notes" / "commands.jsonl"
    run_capture = workspace / "agent" / "notes" / "run-capture.json"
    scenario = {
        "command_log_path": str(command_log),
        "run_capture_path": str(run_capture),
        "version": EXPECTED_VERSION,
        "exec_help_items": EXEC_HELP_ITEMS,
        "doctor": {
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
        "decision_base64": (
            None
            if decision_bytes is None
            else base64.b64encode(decision_bytes).decode("ascii")
        ),
        "stdout_events": [
            {"type": "thread.started", "thread_id": "fresh-thread-id"},
            {"type": "turn.started"},
            {"type": "turn.completed", "usage": {"input_tokens": 1}},
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
    adapter = CodexAdapter(
        registration,
        launch,
        archive=archive,
        executable_name=sys.executable,
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
        launch_instruction=prompt_bytes,
        deadline=datetime.now(timezone.utc) + timedelta(seconds=20),
        session_reference=None,
    )
    return adapter, request, archive, run_capture, command_log
