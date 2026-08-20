"""OpenAI Codex subscription-backed adapter preflight.

R9 implements readiness checks only. It invokes documented diagnostic/help
commands through R7/R8, archives sanitized evidence through R5, and never reads
credential caches directly or starts an agent task.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final, Mapping, Sequence

from arena_kernel.schema.errors import FieldError
from arena_runtime.audit import (
    AuditArchive,
    ProviderArtifactReference,
    append_runner_event,
)
from arena_runtime.session import SessionStore, require_session_reference
from arena_runtime.isolation import (
    ReplicaLaunch,
    resolve_replica_path,
    run_isolated_process,
)
from arena_runtime.process import ProcessFacts, ProcessSupervisorError
from arena_runtime.registration import RuntimeRegistration
from arena_runtime.runner import (
    RUNNER_CONTRACT_VERSION,
    PreflightResult,
    RunnerRequest,
    RunnerResult,
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
CODEX_QUOTA_ERROR_CODES: Final[frozenset[str]] = frozenset(
    {
        "quota_exceeded",
        "rate_limit_reached",
        "session_budget_exceeded",
        "usage_limit_exceeded",
        "workspace_member_credits_depleted",
        "workspace_member_usage_limit_reached",
        "workspace_owner_credits_depleted",
        "workspace_owner_usage_limit_reached",
    }
)
CODEX_PROVIDER_UNAVAILABLE_CODES: Final[frozenset[str]] = frozenset(
    {
        "http_connection_failed",
        "internal_server_error",
        "provider_unavailable",
        "response_stream_connection_failed",
        "response_stream_disconnected",
        "response_too_many_failed_attempts",
        "server_overloaded",
        "service_unavailable",
    }
)
CODEX_REFUSAL_CODES: Final[frozenset[str]] = frozenset(
    {
        "cyber_policy",
        "policy_refusal",
        "refusal",
        "task_refused",
    }
)
_ERROR_CODE_KEYS: Final[frozenset[str]] = frozenset(
    {
        "code",
        "codex_error_kind",
        "codexerrorkind",
        "error_code",
        "error_type",
        "errorcode",
        "errortype",
        "rate_limit_reached_type",
        "ratelimitreachedtype",
    }
)


class CodexPreflightError(FieldError):
    """Invalid Codex adapter setup with a stable field path."""


class CodexExecutionError(FieldError):
    """Raw fresh-run failure whose provider meaning remains deferred to R12."""

    def __init__(
        self,
        path: str,
        message: str,
        *,
        facts: ProcessFacts | None = None,
        decision_checksum: str | None = None,
        artifact_references: tuple[str, ...] = (),
    ) -> None:
        super().__init__(path, message)
        self.facts = facts
        self.decision_checksum = decision_checksum
        self.artifact_references = artifact_references


class CodexSessionError(FieldError):
    """Missing, corrupt, ambiguous, or cross-replica Codex session state."""


class CodexSessionStore(SessionStore):
    """Immutable one-to-one Codex session references outside agent workspaces."""

    def __init__(self, root: Path | str) -> None:
        super().__init__(root, error_cls=CodexSessionError)


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


@dataclass(frozen=True)
class CodexOutcomeClassification:
    """Normalized lifecycle outcome plus non-secret source-evidence facts."""

    outcome: str
    event_types: tuple[str, ...]
    error_codes: tuple[str, ...]
    jsonl_valid: bool


class CodexAdapter:
    """R9 Codex adapter surface: preflight only; run arrives in R10."""

    def __init__(
        self,
        registration: RuntimeRegistration,
        launch: ReplicaLaunch,
        *,
        archive: AuditArchive,
        session_store: CodexSessionStore | None = None,
        executable_name: str = "codex",
        executable_prefix: Sequence[str] = (),
    ) -> None:
        if not isinstance(registration, RuntimeRegistration):
            raise CodexPreflightError("registration", "expected RuntimeRegistration")
        if not isinstance(launch, ReplicaLaunch):
            raise CodexPreflightError("launch", "expected ReplicaLaunch")
        if not isinstance(archive, AuditArchive):
            raise CodexPreflightError("archive", "expected AuditArchive")
        resolved_session_store = (
            CodexSessionStore(
                archive.root.parent / "runtime-state" / "codex-sessions"
            )
            if session_store is None
            else session_store
        )
        if not isinstance(resolved_session_store, CodexSessionStore):
            raise CodexPreflightError(
                "session_store",
                "expected CodexSessionStore",
            )
        if resolved_session_store.root == launch.workspace or (
            resolved_session_store.root.is_relative_to(launch.workspace)
        ):
            raise CodexPreflightError(
                "session_store",
                "must be outside the replica workspace",
            )
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
        self._session_store = resolved_session_store
        self._executable_name = executable_name
        self._executable_prefix = prefix
        self._last_capabilities: CodexPreflightCapabilities | None = None
        self._last_classification: CodexOutcomeClassification | None = None
        self._ready_executable: Path | None = None
        self._ready_identity: tuple[str, str, str] | None = None

    @property
    def last_capabilities(self) -> CodexPreflightCapabilities | None:
        """Most recent ready preflight's safe capability facts."""

        return self._last_capabilities

    @property
    def last_classification(self) -> CodexOutcomeClassification | None:
        """Most recent run's normalized outcome evidence."""

        return self._last_classification

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
        self._last_classification = None
        self._ready_executable = None
        self._ready_identity = None

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
        self._ready_executable = executable
        self._ready_identity = (
            request.product_id,
            request.replica_id,
            request.round_id,
        )
        return self._finish(
            request,
            started_at=started_at,
            ready=True,
            failure_reason=None,
            capabilities=capabilities,
            artifacts=artifacts,
        )

    def run(self, request: RunnerRequest) -> RunnerResult:
        """Execute a fresh or exact stored-session Codex round."""

        if not isinstance(request, RunnerRequest):
            raise CodexExecutionError("request", "expected RunnerRequest")
        identity = (request.product_id, request.replica_id, request.round_id)
        if self._ready_executable is None or self._ready_identity != identity:
            raise CodexExecutionError(
                "preflight",
                "matching ready preflight is required before execution",
            )
        stored_session: str | None = None
        if request.session_reference is None:
            stored_path = self._session_store.record_path(
                request.product_id,
                request.replica_id,
            )
            if stored_path.exists():
                self._session_store.load(request.product_id, request.replica_id)
                raise CodexSessionError(
                    "session_reference",
                    "stored session exists; an explicit matching reference is required",
                )
        else:
            stored_session = self._session_store.load(
                request.product_id,
                request.replica_id,
            )
            if request.session_reference != stored_session:
                raise CodexSessionError(
                    "session_reference",
                    "does not match the session stored for this replica",
                )
        try:
            prompt = request.launch_instruction.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise CodexExecutionError(
                "launch_instruction",
                "must be valid UTF-8 for Codex CLI transport",
            ) from exc

        decision_path = resolve_replica_path(
            self._launch,
            "outbox/decision.json",
            writable=True,
        )
        if decision_path.exists():
            raise CodexExecutionError(
                "workspace.outbox.decision",
                "must be absent before a fresh round",
            )

        launched_at = datetime.now(timezone.utc)
        self._append_preflight_event(
            request,
            event_type="replica_launched",
            timestamp=launched_at,
            payload={
                "deadline": request.deadline.isoformat(),
                "session_reference": stored_session,
            },
            artifacts=(),
        )
        try:
            facts = run_isolated_process(
                self._launch,
                (
                    self._fresh_exec_argv(
                        self._ready_executable,
                        request,
                        prompt,
                    )
                    if stored_session is None
                    else self._resume_exec_argv(
                        self._ready_executable,
                        request,
                        stored_session,
                        prompt,
                    )
                ),
                deadline=request.deadline,
            )
        except ProcessSupervisorError as exc:
            raise CodexExecutionError(
                getattr(exc, "path", "process"),
                getattr(exc, "message", str(exc)),
            ) from exc

        artifacts = (
            self._archive.write_provider_artifact(
                self._artifact_path(request, "run-stdout.jsonl"),
                facts.stdout,
            ),
            self._archive.write_provider_artifact(
                self._artifact_path(request, "run-stderr.log"),
                facts.stderr,
            ),
        )
        collected_path = resolve_replica_path(
            self._launch,
            "outbox/decision.json",
            writable=True,
        )
        decision_bytes = collected_path.read_bytes() if collected_path.is_file() else None
        decision_checksum = (
            hashlib.sha256(decision_bytes).hexdigest()
            if decision_bytes is not None
            else None
        )
        self._append_preflight_event(
            request,
            event_type="decision_collected",
            timestamp=facts.finished_at,
            payload={
                "decision_present": decision_bytes is not None,
                "decision_checksum": decision_checksum,
            },
            artifacts=(),
        )

        artifact_paths = tuple(item.path for item in artifacts)
        classification, events = _classify_codex_outcome(
            facts,
            decision_present=decision_bytes is not None,
        )
        self._last_classification = classification

        observed_session = _optional_thread_reference(events)
        if observed_session is None and classification.outcome in {
            "completed",
            "missing_decision",
        }:
            raise CodexSessionError(
                "session_reference",
                "completed Codex JSONL omitted thread.started.thread_id",
            )
        if stored_session is None and observed_session is not None:
            self._session_store.save(
                request.product_id,
                request.replica_id,
                observed_session,
            )
        elif (
            stored_session is not None
            and observed_session is not None
            and observed_session != stored_session
        ):
            raise CodexSessionError(
                "session_reference",
                "resumed Codex output reported a different thread",
            )
        result_session = stored_session or observed_session

        if classification.outcome == "timeout":
            self._append_preflight_event(
                request,
                event_type="replica_terminated",
                timestamp=facts.finished_at,
                payload={
                    "reason": "deadline",
                    "exit_status": facts.exit_status,
                },
                artifacts=(),
            )

        result = RunnerResult(
            contract_version=RUNNER_CONTRACT_VERSION,
            product_id=request.product_id,
            replica_id=request.replica_id,
            round_id=request.round_id,
            outcome=classification.outcome,
            started_at=facts.started_at,
            finished_at=facts.finished_at,
            exit_status=facts.exit_status,
            decision_present=decision_bytes is not None,
            decision_checksum=decision_checksum,
            session_reference=result_session,
            artifact_references=artifact_paths,
        )
        self._append_preflight_event(
            request,
            event_type="replica_completed",
            timestamp=facts.finished_at,
            payload={
                "outcome": result.outcome,
                "exit_status": result.exit_status,
                "session_reference": result_session,
            },
            artifacts=artifacts,
        )
        return result

    def _fresh_exec_argv(
        self,
        executable: Path,
        request: RunnerRequest,
        prompt: str,
    ) -> tuple[str, ...]:
        return (
            str(executable),
            *self._executable_prefix,
            "--model",
            self._registration.exact_model,
            "--config",
            f'model_reasoning_effort="{self._registration.reasoning_mode}"',
            "--config",
            'model_provider="openai"',
            "--sandbox",
            "workspace-write",
            "--ask-for-approval",
            "never",
            "--search",
            "--strict-config",
            "--cd",
            str(request.workspace),
            "exec",
            "--json",
            "--ignore-user-config",
            "--ignore-rules",
            "--skip-git-repo-check",
            prompt,
        )

    def _resume_exec_argv(
        self,
        executable: Path,
        request: RunnerRequest,
        session_reference: str,
        prompt: str,
    ) -> tuple[str, ...]:
        return (
            str(executable),
            *self._executable_prefix,
            "--model",
            self._registration.exact_model,
            "--config",
            f'model_reasoning_effort="{self._registration.reasoning_mode}"',
            "--config",
            'model_provider="openai"',
            "--sandbox",
            "workspace-write",
            "--ask-for-approval",
            "never",
            "--search",
            "--strict-config",
            "--cd",
            str(request.workspace),
            "exec",
            "resume",
            "--json",
            "--ignore-user-config",
            "--ignore-rules",
            "--skip-git-repo-check",
            session_reference,
            prompt,
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
        if not ready:
            self._ready_executable = None
            self._ready_identity = None
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
        append_runner_event(
            self._archive,
            event_type=event_type,
            product_id=request.product_id,
            replica_id=request.replica_id,
            round_id=request.round_id,
            timestamp=timestamp,
            payload=payload,
            artifacts=artifacts,
        )

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


def classify_codex_outcome(
    facts: ProcessFacts,
    *,
    decision_present: bool,
) -> CodexOutcomeClassification:
    """Map explicit Codex JSONL/raw facts to exactly one frozen R2 outcome."""

    classification, _ = _classify_codex_outcome(
        facts,
        decision_present=decision_present,
    )
    return classification


def _classify_codex_outcome(
    facts: ProcessFacts,
    *,
    decision_present: bool,
) -> tuple[CodexOutcomeClassification, tuple[Mapping[str, Any], ...]]:
    events = _parse_codex_jsonl(facts.stdout)
    if events is None:
        return (
            CodexOutcomeClassification("runner_error", (), (), False),
            (),
        )
    event_types = tuple(str(event["type"]) for event in events)
    error_codes: set[str] = set()
    for event in events:
        event_type = str(event["type"])
        if event_type in {"error", "turn.failed"}:
            _collect_error_codes(event, error_codes)
        if event_type == "item.completed":
            item = event.get("item")
            if isinstance(item, Mapping):
                status = _normalize_code(item.get("status"))
                if status in {"declined", "refused"}:
                    error_codes.add("refusal")

    classes: set[str] = set()
    if error_codes & CODEX_QUOTA_ERROR_CODES:
        classes.add("quota_exhausted")
    if error_codes & CODEX_PROVIDER_UNAVAILABLE_CODES:
        classes.add("provider_unavailable")
    if error_codes & CODEX_REFUSAL_CODES:
        classes.add("refusal")
    known_codes = (
        CODEX_QUOTA_ERROR_CODES
        | CODEX_PROVIDER_UNAVAILABLE_CODES
        | CODEX_REFUSAL_CODES
    )
    unknown_codes = error_codes - known_codes

    if len(classes) != 1 or unknown_codes:
        if classes or error_codes:
            outcome = "runner_error"
        elif facts.timed_out:
            outcome = "timeout"
        elif (
            facts.exit_status == 0
            and "turn.completed" in event_types
            and not any(kind in {"error", "turn.failed"} for kind in event_types)
        ):
            outcome = "completed" if decision_present else "missing_decision"
        else:
            outcome = "runner_error"
    else:
        outcome = next(iter(classes))

    return (
        CodexOutcomeClassification(
            outcome=outcome,
            event_types=event_types,
            error_codes=tuple(sorted(error_codes)),
            jsonl_valid=True,
        ),
        events,
    )


def _parse_codex_jsonl(value: bytes) -> tuple[Mapping[str, Any], ...] | None:
    events: list[Mapping[str, Any]] = []
    for index, raw_line in enumerate(value.splitlines()):
        if not raw_line.strip():
            continue
        try:
            event = json.loads(raw_line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        if not isinstance(event, dict):
            return None
        event_type = event.get("type")
        if not isinstance(event_type, str) or not event_type:
            return None
        events.append(event)
    return tuple(events)


def _optional_thread_reference(events: Sequence[Mapping[str, Any]]) -> str | None:
    references = [
        require_session_reference(event.get("thread_id"), error_cls=CodexSessionError)
        for event in events
        if event.get("type") == "thread.started"
    ]
    if not references:
        return None
    if len(references) != 1:
        raise CodexSessionError(
            "session_reference",
            "Codex JSONL contained multiple thread references",
        )
    return references[0]


def _collect_error_codes(value: object, codes: set[str]) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized_key = _normalize_code(key)
            if normalized_key in _ERROR_CODE_KEYS:
                normalized_value = _normalize_code(child)
                if normalized_value:
                    codes.add(normalized_value)
            _collect_error_codes(child, codes)
    elif isinstance(value, list):
        for child in value:
            _collect_error_codes(child, codes)


def _normalize_code(value: object) -> str:
    if not isinstance(value, str):
        return ""
    with_boundaries = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value.strip())
    return re.sub(r"[^a-zA-Z0-9]+", "_", with_boundaries).strip("_").casefold()


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
