"""Shared R11 multi-replica Codex session fixtures."""

from __future__ import annotations

import base64
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from arena_runtime.adapters.codex import (
    CODEX_DOCUMENTATION_URLS,
    CodexAdapter,
    CodexSessionStore,
)
from arena_runtime.audit import AuditArchive
from arena_runtime.isolation import prepare_replica_launch
from arena_runtime.registration import RuntimeCapabilities, RuntimeRegistration
from arena_runtime.runner import RUNNER_CONTRACT_VERSION, RunnerRequest

FAKE_CODEX = Path(__file__).resolve().parents[1] / "fixtures" / "fake_codex.py"
EXPECTED_VERSION = "0.144.5"
EXPECTED_MODEL = "registered-codex-model"
EXPECTED_REASONING = "high"
MORNING_PROMPT = b"morning frozen instruction"
LATE_PROMPT = b"late frozen instruction"
MORNING_DECISION = b'{"round_id":"2026-08-17-morning","action":"hold"}\n'
LATE_DECISION = b'{"round_id":"2026-08-17-late","action":"hold"}\n'

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
    return {"status": status, "details": {} if details is None else details}


def make_registration(replica_ids: tuple[str, ...]) -> RuntimeRegistration:
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
        replica_ids=replica_ids,
        capabilities=RuntimeCapabilities(True, True, True, True, True),
        provider_documentation_url=CODEX_DOCUMENTATION_URLS[0],
        provider_documentation_retrieved_on=date(2026, 8, 17),
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
    (workspace / "state" / "portfolio.json").write_text('{}\n', encoding="utf-8")
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
    thread_id: str,
    **changes: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "command_log_path": str(workspace / "agent" / "notes" / "commands.jsonl"),
        "capture_log_path": str(workspace / "agent" / "notes" / "runs.jsonl"),
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
        "thread_id": thread_id,
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
    session_store: CodexSessionStore,
    archive: AuditArchive,
    thread_id: str,
    scenario_changes: dict[str, Any] | None = None,
) -> tuple[CodexAdapter, Path, Path]:
    season = root / "season"
    workspace = create_workspace(season, replica_id)
    launch = prepare_replica_launch(
        season.resolve(),
        replica_id,
        host_environment=host_environment(),
    )
    scenario_payload = scenario(
        workspace,
        thread_id,
        **({} if scenario_changes is None else scenario_changes),
    )
    scenario_path = root / f"scenario-{replica_id}.json"
    scenario_path.write_text(
        json.dumps(scenario_payload, indent=2) + "\n",
        encoding="utf-8",
    )
    adapter = CodexAdapter(
        registration,
        launch,
        archive=archive,
        session_store=session_store,
        executable_name=sys.executable,
        executable_prefix=(str(FAKE_CODEX), str(scenario_path)),
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
        product_id="codex-product",
        replica_id=replica_id,
        round_id=round_id,
        workspace=workspace,
        model_reference=EXPECTED_MODEL,
        configuration_reference="registration:codex",
        launch_instruction=prompt,
        deadline=datetime.now(timezone.utc) + timedelta(seconds=20),
        session_reference=session_reference,
    )
