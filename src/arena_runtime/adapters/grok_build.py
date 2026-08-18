"""xAI Grok Build subscription-backed adapter preflight.

R13 implements readiness checks only. It invokes documented Grok Build
diagnostic/help commands through R7/R8, archives sanitized evidence through
R5, and never reads credential caches directly or starts an agent task.
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
from arena_runtime.runner import RUNNER_CONTRACT_VERSION, PreflightResult, RunnerRequest

GROK_BUILD_PROVIDER_ID: Final[str] = "xai"
GROK_BUILD_ADAPTER_ID: Final[str] = "grok_build"

GROK_BUILD_DOCUMENTATION_URLS: Final[tuple[str, ...]] = (
    "https://docs.x.ai/build/overview",
    "https://docs.x.ai/build/cli/reference",
    "https://docs.x.ai/build/cli/headless-scripting",
    "https://docs.x.ai/build/enterprise",
    "https://docs.x.ai/build/settings",
)

GROK_BUILD_PREFLIGHT_FAILURES: Final[tuple[str, ...]] = (
    "grok_build_registration_mismatch",
    "grok_build_executable_missing",
    "grok_build_probe_failed",
    "grok_build_version_mismatch",
    "grok_build_unauthenticated",
    "grok_build_api_key_authentication",
    "grok_build_structured_interface_missing",
    "grok_build_inspect_invalid",
    "grok_build_model_mismatch",
    "grok_build_reasoning_mismatch",
    "grok_build_routing_enabled",
    "grok_build_provider_unavailable",
)

_VERSION_TOKEN = re.compile(r"^(\d+\.\d+\.\d+)\b")
_DEFAULT_MODEL_LINE = re.compile(r"^Default model:\s+(\S+)\s*$", re.MULTILINE)
_AVAILABLE_MODEL_LINE = re.compile(r"^[\t *\-]+(\S+)", re.MULTILINE)
_REQUIRED_HEADLESS_CAPABILITIES: Final[tuple[str, ...]] = (
    "--single",
    "--output-format",
    "json",
    "streaming-json",
    "--model",
    "--resume",
    "--cwd",
    "--reasoning-effort",
    "agent",
)
_REQUIRED_ACP_CAPABILITIES: Final[tuple[str, ...]] = ("stdio",)
_UNAVAILABLE_MARKERS: Final[tuple[str, ...]] = (
    "unable to reach",
    "provider unavailable",
    "service unavailable",
    "connection refused",
    "connection failed",
)
_DOCUMENTED_REASONING_MODES: Final[frozenset[str]] = frozenset(
    {
        "none",
        "minimal",
        "low",
        "medium",
        "high",
        "xhigh",
        "max",
    }
)


class GrokBuildPreflightError(ValueError):
    """Invalid Grok Build adapter setup with a stable field path."""

    def __init__(self, path: str, message: str) -> None:
        self.path = path
        self.message = message
        super().__init__(f"{path}: {message}")


@dataclass(frozen=True)
class GrokBuildPreflightCapabilities:
    """Non-secret Grok Build capability facts proven by preflight."""

    executable_name: str
    cli_version: str
    authentication_mode: str
    model: str
    reasoning_mode: str
    automatic_routing: bool
    headless_prompt: bool
    json_output: bool
    streaming_json: bool
    acp_stdio: bool
    session_resume: bool


class GrokBuildAdapter:
    """R13 Grok Build adapter surface: preflight only; run arrives in R14."""

    def __init__(
        self,
        registration: RuntimeRegistration,
        launch: ReplicaLaunch,
        *,
        archive: AuditArchive,
        executable_name: str = "grok",
        executable_prefix: Sequence[str] = (),
    ) -> None:
        if not isinstance(registration, RuntimeRegistration):
            raise GrokBuildPreflightError(
                "registration",
                "expected RuntimeRegistration",
            )
        if not isinstance(launch, ReplicaLaunch):
            raise GrokBuildPreflightError("launch", "expected ReplicaLaunch")
        if not isinstance(archive, AuditArchive):
            raise GrokBuildPreflightError("archive", "expected AuditArchive")
        if registration.provider_id != GROK_BUILD_PROVIDER_ID:
            raise GrokBuildPreflightError(
                "provider_id",
                f"must be {GROK_BUILD_PROVIDER_ID!r}",
            )
        if registration.adapter_id != GROK_BUILD_ADAPTER_ID:
            raise GrokBuildPreflightError(
                "adapter_id",
                f"must be {GROK_BUILD_ADAPTER_ID!r}",
            )
        if registration.provider_documentation_url not in GROK_BUILD_DOCUMENTATION_URLS:
            raise GrokBuildPreflightError(
                "provider_documentation_url",
                "must be a current official Grok Build product documentation URL",
            )
        if launch.replica_id not in registration.replica_ids:
            raise GrokBuildPreflightError(
                "replica_id",
                "launch replica is not in the frozen registration",
            )
        _safe_segment(registration.product_id, path="product_id")
        _safe_segment(launch.replica_id, path="replica_id")
        if not isinstance(executable_name, str) or not executable_name:
            raise GrokBuildPreflightError(
                "executable_name",
                "must be a non-empty string",
            )
        prefix = tuple(executable_prefix)
        for index, item in enumerate(prefix):
            if not isinstance(item, str) or not item or "\x00" in item:
                raise GrokBuildPreflightError(
                    f"executable_prefix.{index}",
                    "must be a non-empty string without NUL",
                )
        self._registration = registration
        self._launch = launch
        self._archive = archive
        self._executable_name = executable_name
        self._executable_prefix = prefix
        self._last_capabilities: GrokBuildPreflightCapabilities | None = None

    @property
    def last_capabilities(self) -> GrokBuildPreflightCapabilities | None:
        """Most recent ready preflight's safe capability facts."""

        return self._last_capabilities

    def preflight(self, request: RunnerRequest) -> PreflightResult:
        """Run documented Grok Build readiness probes without starting a task."""

        if not isinstance(request, RunnerRequest):
            raise GrokBuildPreflightError("request", "expected RunnerRequest")
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
                failure_reason="grok_build_executable_missing",
                capabilities=None,
                artifacts=artifacts,
            )

        version_probe = self._probe(
            request,
            executable,
            name="version",
            arguments=("version", "--json"),
            artifacts=artifacts,
        )
        if version_probe is None:
            return self._probe_failure(request, started_at, artifacts)
        version = _parse_version_json(version_probe.stdout)
        if version is None or version != self._registration.expected_cli_version:
            return self._finish(
                request,
                started_at=started_at,
                ready=False,
                failure_reason="grok_build_version_mismatch",
                capabilities=None,
                artifacts=artifacts,
            )

        models_probe = self._probe(
            request,
            executable,
            name="models",
            arguments=("models",),
            artifacts=artifacts,
            accept_nonzero=True,
        )
        if models_probe is None:
            return self._probe_failure(request, started_at, artifacts)
        models_text = models_probe.stdout + b"\n" + models_probe.stderr
        if _provider_unavailable(models_text):
            return self._finish(
                request,
                started_at=started_at,
                ready=False,
                failure_reason="grok_build_provider_unavailable",
                capabilities=None,
                artifacts=artifacts,
            )
        authentication_mode = _authentication_mode(models_text)
        if authentication_mode is None or authentication_mode == "unauthenticated":
            return self._finish(
                request,
                started_at=started_at,
                ready=False,
                failure_reason="grok_build_unauthenticated",
                capabilities=None,
                artifacts=artifacts,
            )
        if authentication_mode != "grok.com":
            return self._finish(
                request,
                started_at=started_at,
                ready=False,
                failure_reason="grok_build_api_key_authentication",
                capabilities=None,
                artifacts=artifacts,
            )
        if models_probe.exit_status != 0:
            return self._probe_failure(request, started_at, artifacts)
        model = _parse_default_model(models_text)
        if model is None or model != self._registration.exact_model:
            return self._finish(
                request,
                started_at=started_at,
                ready=False,
                failure_reason="grok_build_model_mismatch",
                capabilities=None,
                artifacts=artifacts,
            )
        available = _parse_available_models(models_text)
        if available and self._registration.exact_model not in available:
            return self._finish(
                request,
                started_at=started_at,
                ready=False,
                failure_reason="grok_build_model_mismatch",
                capabilities=None,
                artifacts=artifacts,
            )

        help_probe = self._probe(
            request,
            executable,
            name="help",
            arguments=("--help",),
            artifacts=artifacts,
        )
        if help_probe is None:
            return self._probe_failure(request, started_at, artifacts)
        help_text = help_probe.stdout.decode("utf-8", errors="replace")
        if any(item not in help_text for item in _REQUIRED_HEADLESS_CAPABILITIES):
            return self._finish(
                request,
                started_at=started_at,
                ready=False,
                failure_reason="grok_build_structured_interface_missing",
                capabilities=None,
                artifacts=artifacts,
            )

        agent_help_probe = self._probe(
            request,
            executable,
            name="agent-help",
            arguments=("agent", "--help"),
            artifacts=artifacts,
        )
        if agent_help_probe is None:
            return self._probe_failure(request, started_at, artifacts)
        agent_help_text = agent_help_probe.stdout.decode("utf-8", errors="replace")
        if any(item not in agent_help_text for item in _REQUIRED_ACP_CAPABILITIES):
            return self._finish(
                request,
                started_at=started_at,
                ready=False,
                failure_reason="grok_build_structured_interface_missing",
                capabilities=None,
                artifacts=artifacts,
            )
        if self._registration.reasoning_mode not in _DOCUMENTED_REASONING_MODES:
            return self._finish(
                request,
                started_at=started_at,
                ready=False,
                failure_reason="grok_build_reasoning_mismatch",
                capabilities=None,
                artifacts=artifacts,
            )

        inspect_probe = self._probe(
            request,
            executable,
            name="inspect",
            arguments=("inspect", "--json"),
            artifacts=artifacts,
        )
        if inspect_probe is None:
            return self._probe_failure(request, started_at, artifacts)
        inspect = _parse_inspect(inspect_probe.stdout)
        if inspect is None:
            return self._finish(
                request,
                started_at=started_at,
                ready=False,
                failure_reason="grok_build_inspect_invalid",
                capabilities=None,
                artifacts=artifacts,
            )
        inspect_failure = self._inspect_failure(
            inspect,
            version=version,
            model=model,
        )
        if inspect_failure is not None:
            return self._finish(
                request,
                started_at=started_at,
                ready=False,
                failure_reason=inspect_failure,
                capabilities=None,
                artifacts=artifacts,
            )

        capabilities = GrokBuildPreflightCapabilities(
            executable_name=executable.name,
            cli_version=version,
            authentication_mode=authentication_mode,
            model=model,
            reasoning_mode=self._registration.reasoning_mode,
            automatic_routing=False,
            headless_prompt=True,
            json_output=True,
            streaming_json=True,
            acp_stdio=True,
            session_resume=True,
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
            return "grok_build_registration_mismatch"
        if request.replica_id != self._launch.replica_id:
            return "grok_build_registration_mismatch"
        if request.replica_id not in self._registration.replica_ids:
            return "grok_build_registration_mismatch"
        if request.workspace != self._launch.workspace:
            return "grok_build_registration_mismatch"
        if request.model_reference != self._registration.exact_model:
            return "grok_build_registration_mismatch"
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
            failure_reason="grok_build_probe_failed",
            capabilities=None,
            artifacts=artifacts,
        )

    def _inspect_failure(
        self,
        inspect: Mapping[str, Any],
        *,
        version: str,
        model: str,
    ) -> str | None:
        grok_version = inspect.get("grokVersion")
        if not isinstance(grok_version, str) or not grok_version:
            return "grok_build_inspect_invalid"
        if grok_version != version:
            return "grok_build_version_mismatch"
        inspect_model = _inspect_model(inspect)
        if inspect_model is not None and inspect_model != model:
            return "grok_build_model_mismatch"
        inspect_reasoning = _inspect_reasoning(inspect)
        if inspect_reasoning is not None and (
            inspect_reasoning != self._registration.reasoning_mode
        ):
            return "grok_build_reasoning_mismatch"
        routing = _inspect_routing(inspect)
        if routing is True:
            return "grok_build_routing_enabled"
        if routing is not False and routing is not None:
            return "grok_build_inspect_invalid"
        reachability = _inspect_reachability(inspect)
        if reachability is not None and reachability != "ok":
            return "grok_build_provider_unavailable"
        return None

    def _finish(
        self,
        request: RunnerRequest,
        *,
        started_at: datetime,
        ready: bool,
        failure_reason: str | None,
        capabilities: GrokBuildPreflightCapabilities | None,
        artifacts: list[ProviderArtifactReference],
    ) -> PreflightResult:
        summary = {
            "adapter_id": GROK_BUILD_ADAPTER_ID,
            "provider_id": GROK_BUILD_PROVIDER_ID,
            "ready": ready,
            "failure_reason": failure_reason,
            "capabilities": None if capabilities is None else asdict(capabilities),
            "documentation_urls": list(GROK_BUILD_DOCUMENTATION_URLS),
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
        if not ready:
            self._last_capabilities = None
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
            f"{request.replica_id}/grok-preflight-{name}"
        )


def _parse_version_json(value: bytes) -> str | None:
    try:
        parsed = json.loads(value.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(parsed, dict):
        return None
    current = parsed.get("currentVersion")
    if not isinstance(current, str):
        return None
    match = _VERSION_TOKEN.match(current.strip())
    return None if match is None else match.group(1)


def _authentication_mode(value: bytes) -> str | None:
    text = value.decode("utf-8", errors="replace").casefold()
    logged_in = "you are logged in with grok.com" in text
    using_key = "you are using" in text and "api_key" in text
    unsigned = "you are not authenticated" in text
    matched = sum((logged_in, using_key, unsigned))
    if matched != 1:
        return None
    if logged_in:
        return "grok.com"
    if using_key:
        return "api_key"
    return "unauthenticated"


def _parse_default_model(value: bytes) -> str | None:
    text = value.decode("utf-8", errors="replace")
    match = _DEFAULT_MODEL_LINE.search(text)
    if match is None:
        return None
    model = match.group(1)
    return model if model else None


def _parse_available_models(value: bytes) -> tuple[str, ...]:
    text = value.decode("utf-8", errors="replace")
    marker = "Available models:"
    start = text.find(marker)
    if start < 0:
        return ()
    names: list[str] = []
    for match in _AVAILABLE_MODEL_LINE.finditer(text[start + len(marker) :]):
        name = match.group(1)
        if name and name not in names:
            names.append(name)
    return tuple(names)


def _provider_unavailable(value: bytes) -> bool:
    text = value.decode("utf-8", errors="replace").casefold()
    return any(marker in text for marker in _UNAVAILABLE_MARKERS)


def _parse_inspect(value: bytes) -> Mapping[str, Any] | None:
    try:
        parsed = json.loads(value.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def _inspect_model(inspect: Mapping[str, Any]) -> str | None:
    for key in ("defaultModel", "default_model"):
        value = inspect.get(key)
        if isinstance(value, str) and value:
            return value
    models = inspect.get("models")
    if isinstance(models, Mapping):
        value = models.get("default")
        if isinstance(value, str) and value:
            return value
    return None


def _inspect_reasoning(inspect: Mapping[str, Any]) -> str | None:
    for key in ("defaultReasoningEffort", "default_reasoning_effort", "reasoningEffort"):
        value = inspect.get(key)
        if isinstance(value, str) and value:
            return value
    models = inspect.get("models")
    if isinstance(models, Mapping):
        value = models.get("default_reasoning_effort")
        if isinstance(value, str) and value:
            return value
    return None


def _inspect_routing(inspect: Mapping[str, Any]) -> bool | None:
    for key in ("automaticRouting", "automatic_routing"):
        value = _boolean_value(inspect.get(key))
        if value is not None:
            return value
    models = inspect.get("models")
    if isinstance(models, Mapping):
        return _boolean_value(models.get("automatic_routing"))
    return None


def _inspect_reachability(inspect: Mapping[str, Any]) -> str | None:
    for key in ("providerReachability", "provider_reachability"):
        value = inspect.get(key)
        if isinstance(value, str) and value:
            return value.casefold()
    return None


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
        raise GrokBuildPreflightError(path, "must be one safe path segment")
