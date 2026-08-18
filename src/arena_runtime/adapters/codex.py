"""OpenAI Codex subscription-backed adapter preflight.

R9 implements readiness checks only. It invokes documented diagnostic/help
commands through R7/R8, archives sanitized evidence through R5, and never reads
credential caches directly or starts an agent task.
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final, Mapping, Sequence

from arena_runtime.audit import (
    AUDIT_SCHEMA_VERSION,
    AuditArchive,
    ProviderArtifactReference,
    parse_audit_event,
)
from arena_runtime.isolation import ReplicaLaunch, run_isolated_process
from arena_runtime.process import ProcessFacts, ProcessSupervisorError
from arena_runtime.registration import RuntimeRegistration
from arena_runtime.runner import (
    RUNNER_CONTRACT_VERSION,
    PreflightResult,
    RunnerRequest,
)

CODEX_PROVIDER_ID: Final[str] = "openai"
CODEX_ADAPTER_ID: Final[str] = "codex"

CODEX_DOCUMENTATION_URLS: Final[tuple[str, ...]] = (
    "https://learn.chatgpt.com/docs/auth",
    "https://learn.chatgpt.com/docs/developer-commands?surface=cli",
    "https://learn.chatgpt.com/docs/non-interactive-mode",
    "https://learn.chatgpt.com/docs/config-file/config-reference",
)

CODEX_PREFLIGHT_FAILURES: Final[tuple[str, ...]] = (
    "codex_registration_mismatch",
    "codex_executable_missing",
    "codex_probe_failed",
    "codex_version_mismatch",
    "codex_unauthenticated",
    "codex_api_key_authentication",
    "codex_structured_interface_missing",
    "codex_doctor_invalid",
    "codex_model_mismatch",
    "codex_reasoning_mismatch",
    "codex_routing_enabled",
    "codex_provider_unavailable",
)

_VERSION_PATTERN = re.compile(r"^codex-cli(?:-exec)?\s+(\S+)\s*$")
_REQUIRED_EXEC_CAPABILITIES: Final[tuple[str, ...]] = (
    "--config",
    "--ignore-rules",
    "--ignore-user-config",
    "--json",
    "--model",
    "--output-schema",
    "--skip-git-repo-check",
    "--strict-config",
    "resume",
)


class CodexPreflightError(ValueError):
    """Invalid Codex adapter setup with a stable field path."""

    def __init__(self, path: str, message: str) -> None:
        self.path = path
        self.message = message
        super().__init__(f"{path}: {message}")


@dataclass(frozen=True)
class CodexPreflightCapabilities:
    """Non-secret Codex capability facts proven by preflight."""

    executable_name: str
    cli_version: str
    authentication_mode: str
    model: str
    model_provider: str
    reasoning_mode: str
    automatic_routing: bool
    headless_exec: bool
    jsonl_output: bool
    structured_output: bool
    session_resume: bool
    ignores_user_config: bool
    ignores_rules: bool


class CodexAdapter:
    """R9 Codex adapter surface: preflight only; run arrives in R10."""

    def __init__(
        self,
        registration: RuntimeRegistration,
        launch: ReplicaLaunch,
        *,
        archive: AuditArchive,
        executable_name: str = "codex",
        executable_prefix: Sequence[str] = (),
    ) -> None:
        if not isinstance(registration, RuntimeRegistration):
            raise CodexPreflightError("registration", "expected RuntimeRegistration")
        if not isinstance(launch, ReplicaLaunch):
            raise CodexPreflightError("launch", "expected ReplicaLaunch")
        if not isinstance(archive, AuditArchive):
            raise CodexPreflightError("archive", "expected AuditArchive")
        if registration.provider_id != CODEX_PROVIDER_ID:
            raise CodexPreflightError(
                "provider_id",
                f"must be {CODEX_PROVIDER_ID!r}",
            )
        if registration.adapter_id != CODEX_ADAPTER_ID:
            raise CodexPreflightError(
                "adapter_id",
                f"must be {CODEX_ADAPTER_ID!r}",
            )
        if registration.provider_documentation_url not in CODEX_DOCUMENTATION_URLS:
            raise CodexPreflightError(
                "provider_documentation_url",
                "must be a current official Codex product documentation URL",
            )
        if launch.replica_id not in registration.replica_ids:
            raise CodexPreflightError(
                "replica_id",
                "launch replica is not in the frozen registration",
            )
        _safe_segment(registration.product_id, path="product_id")
        _safe_segment(launch.replica_id, path="replica_id")
        if not isinstance(executable_name, str) or not executable_name:
            raise CodexPreflightError("executable_name", "must be a non-empty string")
        prefix = tuple(executable_prefix)
        for index, item in enumerate(prefix):
            if not isinstance(item, str) or not item or "\x00" in item:
                raise CodexPreflightError(
                    f"executable_prefix.{index}",
                    "must be a non-empty string without NUL",
                )
        self._registration = registration
        self._launch = launch
        self._archive = archive
        self._executable_name = executable_name
        self._executable_prefix = prefix
        self._last_capabilities: CodexPreflightCapabilities | None = None

    @property
    def last_capabilities(self) -> CodexPreflightCapabilities | None:
        """Most recent ready preflight's safe capability facts."""

        return self._last_capabilities

    def preflight(self, request: RunnerRequest) -> PreflightResult:
        """Run documented Codex readiness probes without starting a task."""

        if not isinstance(request, RunnerRequest):
            raise CodexPreflightError("request", "expected RunnerRequest")
        _safe_segment(request.product_id, path="product_id")
        _safe_segment(request.replica_id, path="replica_id")
        started_at = datetime.now(timezone.utc)
        self._append_preflight_event(
            request,
            event_type="preflight_started",
            timestamp=started_at,
            payload={},
            artifacts=(),
        )
        artifacts: list[ProviderArtifactReference] = []
        self._last_capabilities = None

        request_failure = self._request_failure(request)
        if request_failure is not None:
            return self._finish(
                request,
                started_at=started_at,
                ready=False,
                failure_reason=request_failure,
                capabilities=None,
                artifacts=artifacts,
            )

        executable = self._discover_executable()
        if executable is None:
            return self._finish(
                request,
                started_at=started_at,
                ready=False,
                failure_reason="codex_executable_missing",
                capabilities=None,
                artifacts=artifacts,
            )

        version_probe = self._probe(
            request,
            executable,
            name="version",
            arguments=("--version",),
            artifacts=artifacts,
        )
        if version_probe is None:
            return self._probe_failure(request, started_at, artifacts)
        version = _parse_version(version_probe.stdout)
        if version is None or version != self._registration.expected_cli_version:
            return self._finish(
                request,
                started_at=started_at,
                ready=False,
                failure_reason="codex_version_mismatch",
                capabilities=None,
                artifacts=artifacts,
            )

        login_probe = self._probe(
            request,
            executable,
            name="login-status",
            arguments=("login", "status"),
            artifacts=artifacts,
            accept_nonzero=True,
        )
        if login_probe is None:
            return self._probe_failure(request, started_at, artifacts)
        authentication_mode = _authentication_mode(
            login_probe.stdout + b"\n" + login_probe.stderr
        )
        if login_probe.exit_status != 0 or authentication_mode is None:
            return self._finish(
                request,
                started_at=started_at,
                ready=False,
                failure_reason="codex_unauthenticated",
                capabilities=None,
                artifacts=artifacts,
            )
        if authentication_mode != "chatgpt":
            return self._finish(
                request,
                started_at=started_at,
                ready=False,
                failure_reason="codex_api_key_authentication",
                capabilities=None,
                artifacts=artifacts,
            )

        help_probe = self._probe(
            request,
            executable,
            name="exec-help",
            arguments=("exec", "--help"),
            artifacts=artifacts,
        )
        if help_probe is None:
            return self._probe_failure(request, started_at, artifacts)
        help_text = help_probe.stdout.decode("utf-8", errors="replace")
        if any(item not in help_text for item in _REQUIRED_EXEC_CAPABILITIES):
            return self._finish(
                request,
                started_at=started_at,
                ready=False,
                failure_reason="codex_structured_interface_missing",
                capabilities=None,
                artifacts=artifacts,
            )

        doctor_probe = self._probe(
            request,
            executable,
            name="doctor",
            arguments=("doctor", "--json"),
            artifacts=artifacts,
        )
        if doctor_probe is None:
            return self._probe_failure(request, started_at, artifacts)
        doctor = _parse_doctor(doctor_probe.stdout)
        if doctor is None:
            return self._finish(
                request,
                started_at=started_at,
                ready=False,
                failure_reason="codex_doctor_invalid",
                capabilities=None,
                artifacts=artifacts,
            )
        failure = self._doctor_failure(
            doctor,
            version=version,
            authentication_mode=authentication_mode,
        )
        if failure is not None:
            return self._finish(
                request,
                started_at=started_at,
                ready=False,
                failure_reason=failure,
                capabilities=None,
                artifacts=artifacts,
            )

        config_details = _check_details(doctor, "config.load")
        capabilities = CodexPreflightCapabilities(
            executable_name=executable.name,
            cli_version=version,
            authentication_mode=authentication_mode,
            model=str(config_details["model"]),
            model_provider=str(config_details["model provider"]),
            reasoning_mode=self._registration.reasoning_mode,
            automatic_routing=False,
            headless_exec=True,
            jsonl_output=True,
            structured_output=True,
            session_resume=True,
            ignores_user_config=True,
            ignores_rules=True,
        )
        self._last_capabilities = capabilities
        return self._finish(
            request,
            started_at=started_at,
            ready=True,
            failure_reason=None,
            capabilities=capabilities,
            artifacts=artifacts,
        )

    def _request_failure(self, request: RunnerRequest) -> str | None:
        if request.product_id != self._registration.product_id:
            return "codex_registration_mismatch"
        if request.replica_id != self._launch.replica_id:
            return "codex_registration_mismatch"
        if request.replica_id not in self._registration.replica_ids:
            return "codex_registration_mismatch"
        if request.workspace != self._launch.workspace:
            return "codex_registration_mismatch"
        if request.model_reference != self._registration.exact_model:
            return "codex_registration_mismatch"
        return None

    def _discover_executable(self) -> Path | None:
        candidate = Path(self._executable_name)
        if candidate.is_absolute():
            resolved = candidate.resolve(strict=False)
            return resolved if resolved.is_file() else None
        found = shutil.which(
            self._executable_name,
            path=self._launch.environment().get("PATH"),
        )
        return Path(found).resolve() if found is not None else None

    def _probe(
        self,
        request: RunnerRequest,
        executable: Path,
        *,
        name: str,
        arguments: tuple[str, ...],
        artifacts: list[ProviderArtifactReference],
        accept_nonzero: bool = False,
    ) -> ProcessFacts | None:
        try:
            facts = run_isolated_process(
                self._launch,
                (
                    str(executable),
                    *self._executable_prefix,
                    *arguments,
                ),
                deadline=request.deadline,
            )
        except ProcessSupervisorError:
            return None
        artifacts.extend(
            (
                self._archive.write_provider_artifact(
                    self._artifact_path(request, f"{name}-stdout.log"),
                    facts.stdout,
                ),
                self._archive.write_provider_artifact(
                    self._artifact_path(request, f"{name}-stderr.log"),
                    facts.stderr,
                ),
            )
        )
        if facts.timed_out or (facts.exit_status != 0 and not accept_nonzero):
            return None
        return facts

    def _probe_failure(
        self,
        request: RunnerRequest,
        started_at: datetime,
        artifacts: list[ProviderArtifactReference],
    ) -> PreflightResult:
        return self._finish(
            request,
            started_at=started_at,
            ready=False,
            failure_reason="codex_probe_failed",
            capabilities=None,
            artifacts=artifacts,
        )

    def _doctor_failure(
        self,
        doctor: Mapping[str, Any],
        *,
        version: str,
        authentication_mode: str,
    ) -> str | None:
        if str(doctor.get("codexVersion", "")) != version:
            return "codex_version_mismatch"
        if _check_status(doctor, "installation") != "ok":
            return "codex_probe_failed"
        auth_status = _check_status(doctor, "auth.credentials")
        auth_details = _check_details(doctor, "auth.credentials")
        if auth_status != "ok":
            return "codex_unauthenticated"
        doctor_auth = str(auth_details.get("stored auth mode", "")).casefold()
        stored_api_key = _boolean_value(auth_details.get("stored API key"))
        stored_chatgpt = _boolean_value(auth_details.get("stored ChatGPT tokens"))
        if doctor_auth != "chatgpt" or authentication_mode != "chatgpt":
            return "codex_api_key_authentication"
        if stored_api_key is not False or stored_chatgpt is not True:
            return "codex_api_key_authentication"

        config_status = _check_status(doctor, "config.load")
        config_details = _check_details(doctor, "config.load")
        if config_status != "ok":
            return "codex_doctor_invalid"
        if str(config_details.get("model", "")) != self._registration.exact_model:
            return "codex_model_mismatch"
        if str(config_details.get("model provider", "")) != CODEX_PROVIDER_ID:
            return "codex_model_mismatch"
        observed_reasoning = config_details.get("model reasoning effort")
        if observed_reasoning is not None and (
            str(observed_reasoning) != self._registration.reasoning_mode
        ):
            return "codex_reasoning_mismatch"
        routing = _boolean_value(config_details.get("automatic routing", False))
        if routing is not False:
            return "codex_routing_enabled"
        if _check_status(doctor, "network.provider_reachability") != "ok":
            return "codex_provider_unavailable"
        return None

    def _finish(
        self,
        request: RunnerRequest,
        *,
        started_at: datetime,
        ready: bool,
        failure_reason: str | None,
        capabilities: CodexPreflightCapabilities | None,
        artifacts: list[ProviderArtifactReference],
    ) -> PreflightResult:
        summary = {
            "adapter_id": CODEX_ADAPTER_ID,
            "provider_id": CODEX_PROVIDER_ID,
            "ready": ready,
            "failure_reason": failure_reason,
            "capabilities": None if capabilities is None else asdict(capabilities),
            "documentation_urls": list(CODEX_DOCUMENTATION_URLS),
            "documentation_retrieved_on": (
                self._registration.provider_documentation_retrieved_on.isoformat()
            ),
        }
        summary_artifact = self._archive.write_provider_artifact(
            self._artifact_path(request, "summary.json"),
            (json.dumps(summary, indent=2) + "\n").encode("utf-8"),
        )
        all_artifacts = (*artifacts, summary_artifact)
        finished_at = datetime.now(timezone.utc)
        result = PreflightResult(
            contract_version=RUNNER_CONTRACT_VERSION,
            product_id=request.product_id,
            replica_id=request.replica_id,
            round_id=request.round_id,
            ready=ready,
            started_at=started_at,
            finished_at=finished_at,
            failure_reason=failure_reason,
            artifact_references=tuple(item.path for item in all_artifacts),
        )
        self._append_preflight_event(
            request,
            event_type="preflight_completed",
            timestamp=finished_at,
            payload={
                "ready": ready,
                "failure_reason": failure_reason,
            },
            artifacts=all_artifacts,
        )
        return result

    def _append_preflight_event(
        self,
        request: RunnerRequest,
        *,
        event_type: str,
        timestamp: datetime,
        payload: dict[str, object],
        artifacts: Sequence[ProviderArtifactReference],
    ) -> None:
        event = parse_audit_event(
            {
                "schema_version": AUDIT_SCHEMA_VERSION,
                "type": event_type,
                "product_id": request.product_id,
                "replica_id": request.replica_id,
                "round_id": request.round_id,
                "timestamp": timestamp.isoformat(),
                "payload": payload,
                "provider_artifacts": [
                    {"path": item.path, "checksum": item.checksum}
                    for item in artifacts
                ],
            }
        )
        self._archive.append_event(event)

    def _artifact_path(self, request: RunnerRequest, name: str) -> str:
        return (
            f"provider/{request.round_id}/{request.product_id}/"
            f"{request.replica_id}/codex-preflight-{name}"
        )


def _parse_version(value: bytes) -> str | None:
    match = _VERSION_PATTERN.fullmatch(value.decode("utf-8", errors="replace").strip())
    return None if match is None else match.group(1)


def _authentication_mode(value: bytes) -> str | None:
    text = value.decode("utf-8", errors="replace").casefold()
    if "chatgpt" in text:
        return "chatgpt"
    if "api key" in text or "api-key" in text:
        return "api_key"
    if "access token" in text:
        return "access_token"
    return None


def _parse_doctor(value: bytes) -> Mapping[str, Any] | None:
    try:
        parsed = json.loads(value.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(parsed, dict) or not isinstance(parsed.get("checks"), dict):
        return None
    return parsed


def _check(doctor: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    checks = doctor.get("checks")
    if not isinstance(checks, Mapping):
        return {}
    check = checks.get(name)
    return check if isinstance(check, Mapping) else {}


def _check_status(doctor: Mapping[str, Any], name: str) -> str:
    return str(_check(doctor, name).get("status", "")).casefold()


def _check_details(doctor: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    details = _check(doctor, name).get("details")
    return details if isinstance(details, Mapping) else {}


def _boolean_value(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.casefold()
        if normalized == "true":
            return True
        if normalized == "false":
            return False
    return None


def _safe_segment(value: str, *, path: str) -> None:
    if value in {".", ".."} or "/" in value or "\\" in value:
        raise CodexPreflightError(path, "must be one safe path segment")
