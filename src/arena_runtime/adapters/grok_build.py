"""xAI Grok Build subscription-backed adapter.

R13 proves readiness. R14 runs one fresh headless replica session. Resume and
provider-failure classification remain later slices.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import threading
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
_SESSION_SCHEMA_VERSION: Final[str] = "1"
_SESSION_LOCKS: dict[Path, threading.Lock] = {}
_SESSION_LOCKS_GUARD = threading.Lock()
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


class GrokBuildExecutionError(ValueError):
    """Raw fresh-run failure whose provider meaning remains deferred to R16."""

    def __init__(
        self,
        path: str,
        message: str,
        *,
        facts: ProcessFacts | None = None,
        decision_checksum: str | None = None,
        artifact_references: tuple[str, ...] = (),
    ) -> None:
        self.path = path
        self.message = message
        self.facts = facts
        self.decision_checksum = decision_checksum
        self.artifact_references = artifact_references
        super().__init__(f"{path}: {message}")


class GrokBuildSessionError(ValueError):
    """Missing, corrupt, ambiguous, or cross-replica Grok Build session state."""

    def __init__(self, path: str, message: str) -> None:
        self.path = path
        self.message = message
        super().__init__(f"{path}: {message}")


class GrokBuildSessionStore:
    """Immutable one-to-one Grok Build session references outside agent workspaces."""

    def __init__(self, root: Path | str) -> None:
        if not isinstance(root, (Path, str)):
            raise GrokBuildSessionError("session_store", "expected a path")
        resolved = Path(root).resolve(strict=False)
        try:
            resolved.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise GrokBuildSessionError(
                "session_store",
                f"cannot create session store: {exc}",
            ) from exc
        if not resolved.is_dir():
            raise GrokBuildSessionError("session_store", "must be a directory")
        self._root = resolved
        with _SESSION_LOCKS_GUARD:
            self._lock = _SESSION_LOCKS.setdefault(resolved, threading.Lock())

    @property
    def root(self) -> Path:
        return self._root

    def record_path(self, product_id: str, replica_id: str) -> Path:
        _store_segment(product_id, path="product_id")
        _store_segment(replica_id, path="replica_id")
        return (self._root / product_id / f"{replica_id}.json").resolve(strict=False)

    def save(
        self,
        product_id: str,
        replica_id: str,
        session_reference: str,
    ) -> Path:
        reference = _session_reference(session_reference)
        target = self.record_path(product_id, replica_id)
        payload = {
            "schema_version": _SESSION_SCHEMA_VERSION,
            "product_id": product_id,
            "replica_id": replica_id,
            "session_reference": reference,
        }
        data = (json.dumps(payload, indent=2) + "\n").encode("utf-8")
        with self._lock:
            for record in self._root.rglob("*.json"):
                stored = self._load_path(record)
                if stored["session_reference"] == reference and record != target:
                    raise GrokBuildSessionError(
                        "session_reference",
                        "is already mapped to another product or replica",
                    )
            if target.exists():
                stored = self._load_path(target)
                if stored != payload:
                    raise GrokBuildSessionError(
                        "session_reference",
                        "replica already has a different stored session",
                    )
                return target
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("xb") as stream:
                    stream.write(data)
            except FileExistsError:
                stored = self._load_path(target)
                if stored != payload:
                    raise GrokBuildSessionError(
                        "session_reference",
                        "replica session was concurrently replaced",
                    )
            except OSError as exc:
                raise GrokBuildSessionError(
                    "session_store",
                    f"cannot persist session reference: {exc}",
                ) from exc
        return target

    def load(self, product_id: str, replica_id: str) -> str:
        target = self.record_path(product_id, replica_id)
        with self._lock:
            if not target.is_file():
                raise GrokBuildSessionError(
                    "session_reference",
                    "stored session is missing for this replica",
                )
            return str(self._load_path(target)["session_reference"])

    def _load_path(self, path: Path) -> dict[str, str]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GrokBuildSessionError(
                "session_reference",
                "stored session record is corrupt",
            ) from exc
        required = {
            "schema_version",
            "product_id",
            "replica_id",
            "session_reference",
        }
        if not isinstance(payload, dict) or set(payload) != required:
            raise GrokBuildSessionError(
                "session_reference",
                "stored session record has an invalid shape",
            )
        for key in required:
            if not isinstance(payload[key], str):
                raise GrokBuildSessionError(
                    "session_reference",
                    f"stored session field {key!r} is invalid",
                )
        if payload["schema_version"] != _SESSION_SCHEMA_VERSION:
            raise GrokBuildSessionError(
                "session_reference",
                "stored session schema version is unsupported",
            )
        _store_segment(payload["product_id"], path="product_id")
        _store_segment(payload["replica_id"], path="replica_id")
        _session_reference(payload["session_reference"])
        expected = self.record_path(payload["product_id"], payload["replica_id"])
        if expected != path.resolve(strict=False):
            raise GrokBuildSessionError(
                "session_reference",
                "stored session identity does not match its path",
            )
        return {key: str(payload[key]) for key in required}


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
    """Grok Build adapter: R13 preflight, R14 fresh run, R15 session resume."""

    def __init__(
        self,
        registration: RuntimeRegistration,
        launch: ReplicaLaunch,
        *,
        archive: AuditArchive,
        session_store: GrokBuildSessionStore | None = None,
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
        resolved_session_store = (
            GrokBuildSessionStore(
                archive.root.parent / "runtime-state" / "grok-sessions"
            )
            if session_store is None
            else session_store
        )
        if not isinstance(resolved_session_store, GrokBuildSessionStore):
            raise GrokBuildPreflightError(
                "session_store",
                "expected GrokBuildSessionStore",
            )
        if resolved_session_store.root == launch.workspace or (
            resolved_session_store.root.is_relative_to(launch.workspace)
        ):
            raise GrokBuildPreflightError(
                "session_store",
                "must be outside the replica workspace",
            )
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
        self._session_store = resolved_session_store
        self._executable_name = executable_name
        self._executable_prefix = prefix
        self._last_capabilities: GrokBuildPreflightCapabilities | None = None
        self._ready_executable: Path | None = None
        self._ready_identity: tuple[str, str, str] | None = None

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
        """Execute a fresh or exact stored-session Grok Build round."""

        if not isinstance(request, RunnerRequest):
            raise GrokBuildExecutionError("request", "expected RunnerRequest")
        identity = (request.product_id, request.replica_id, request.round_id)
        if self._ready_executable is None or self._ready_identity != identity:
            raise GrokBuildExecutionError(
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
                raise GrokBuildSessionError(
                    "session_reference",
                    "stored session exists; an explicit matching reference is required",
                )
        else:
            stored_session = self._session_store.load(
                request.product_id,
                request.replica_id,
            )
            if request.session_reference != stored_session:
                raise GrokBuildSessionError(
                    "session_reference",
                    "does not match the session stored for this replica",
                )
        try:
            prompt = request.launch_instruction.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise GrokBuildExecutionError(
                "launch_instruction",
                "must be valid UTF-8 for Grok Build CLI transport",
            ) from exc

        decision_path = resolve_replica_path(
            self._launch,
            "outbox/decision.json",
            writable=True,
        )
        if decision_path.exists():
            raise GrokBuildExecutionError(
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
                    self._fresh_argv(self._ready_executable, request, prompt)
                    if stored_session is None
                    else self._resume_argv(
                        self._ready_executable,
                        request,
                        stored_session,
                        prompt,
                    )
                ),
                deadline=request.deadline,
            )
        except ProcessSupervisorError as exc:
            raise GrokBuildExecutionError(
                getattr(exc, "path", "process"),
                getattr(exc, "message", str(exc)),
            ) from exc

        artifacts = (
            self._archive.write_provider_artifact(
                self._run_artifact_path(request, "stdout.jsonl"),
                facts.stdout,
            ),
            self._archive.write_provider_artifact(
                self._run_artifact_path(request, "stderr.log"),
                facts.stderr,
            ),
        )
        artifact_paths = tuple(item.path for item in artifacts)
        collected_path = resolve_replica_path(
            self._launch,
            "outbox/decision.json",
            writable=True,
        )
        decision_bytes = (
            collected_path.read_bytes() if collected_path.is_file() else None
        )
        decision_checksum = (
            hashlib.sha256(decision_bytes).hexdigest()
            if decision_bytes is not None
            else None
        )
        if facts.timed_out:
            raise GrokBuildExecutionError(
                "deadline",
                "Grok Build process tree was terminated at the shared deadline",
                facts=facts,
                decision_checksum=decision_checksum,
                artifact_references=artifact_paths,
            )
        if facts.exit_status != 0:
            raise GrokBuildExecutionError(
                "exit_status",
                "Grok Build fresh run exited unsuccessfully",
                facts=facts,
                decision_checksum=decision_checksum,
                artifact_references=artifact_paths,
            )
        if decision_bytes is None:
            raise GrokBuildExecutionError(
                "decision",
                "Grok Build fresh run did not write outbox/decision.json",
                facts=facts,
                decision_checksum=None,
                artifact_references=artifact_paths,
            )

        observed_session = _require_one_session_id(facts.stdout)
        if stored_session is None:
            self._session_store.save(
                request.product_id,
                request.replica_id,
                observed_session,
            )
        elif observed_session != stored_session:
            raise GrokBuildSessionError(
                "session_reference",
                "resumed Grok Build output reported a different session",
            )
        result_session = stored_session or observed_session

        self._append_preflight_event(
            request,
            event_type="decision_collected",
            timestamp=facts.finished_at,
            payload={
                "decision_present": True,
                "decision_checksum": decision_checksum,
            },
            artifacts=(),
        )
        result = RunnerResult(
            contract_version=RUNNER_CONTRACT_VERSION,
            product_id=request.product_id,
            replica_id=request.replica_id,
            round_id=request.round_id,
            outcome="completed",
            started_at=facts.started_at,
            finished_at=facts.finished_at,
            exit_status=facts.exit_status,
            decision_present=True,
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

    def _command_prefix(
        self,
        executable: Path,
        request: RunnerRequest,
    ) -> tuple[str, ...]:
        return (
            str(executable),
            *self._executable_prefix,
            "--cwd",
            str(request.workspace),
            "--model",
            self._registration.exact_model,
            "--reasoning-effort",
            self._registration.reasoning_mode,
            "--output-format",
            "streaming-json",
            "--sandbox",
            "workspace",
            "--always-approve",
            "--no-auto-update",
            "--verbatim",
        )

    def _fresh_argv(
        self,
        executable: Path,
        request: RunnerRequest,
        prompt: str,
    ) -> tuple[str, ...]:
        return (*self._command_prefix(executable, request), "--single", prompt)

    def _resume_argv(
        self,
        executable: Path,
        request: RunnerRequest,
        session_reference: str,
        prompt: str,
    ) -> tuple[str, ...]:
        return (
            *self._command_prefix(executable, request),
            "--resume",
            session_reference,
            "--single",
            prompt,
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

    def _run_artifact_path(self, request: RunnerRequest, name: str) -> str:
        return (
            f"provider/{request.round_id}/{request.product_id}/"
            f"{request.replica_id}/grok-run-{name}"
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


def _session_reference(value: object) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise GrokBuildSessionError(
            "session_reference",
            "must be a non-empty opaque string without padding",
        )
    if "\x00" in value:
        raise GrokBuildSessionError("session_reference", "must not contain NUL")
    return value


def _store_segment(value: str, *, path: str) -> None:
    try:
        _safe_segment(value, path=path)
    except GrokBuildPreflightError as exc:
        raise GrokBuildSessionError(exc.path, exc.message) from exc


def _require_one_session_id(value: bytes) -> str:
    collected = _collect_session_ids(value)
    if collected is None:
        raise GrokBuildSessionError(
            "session_reference",
            "Grok Build output was not valid JSON or JSONL",
        )
    if len(collected) != 1:
        raise GrokBuildSessionError(
            "session_reference",
            "completed Grok Build output must contain exactly one sessionId",
        )
    return collected[0]


def _collect_session_ids(value: bytes) -> tuple[str, ...] | None:
    events: list[Mapping[str, Any]] = []
    for raw_line in value.splitlines():
        if not raw_line.strip():
            continue
        try:
            event = json.loads(raw_line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        if not isinstance(event, dict):
            return None
        events.append(event)
    end_ids: list[str] = []
    for event in events:
        if event.get("type") == "end":
            session_id = event.get("sessionId")
            if isinstance(session_id, str) and session_id and session_id.strip() == session_id:
                end_ids.append(session_id)
    if end_ids:
        return tuple(end_ids)
    if len(events) == 1:
        session_id = events[0].get("sessionId")
        if isinstance(session_id, str) and session_id and session_id.strip() == session_id:
            return (session_id,)
    return ()
