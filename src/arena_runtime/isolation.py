"""Replica workspace and launch isolation.

R8 validates one direct replica root, brokers runtime paths, builds a minimal
environment, and applies a launch-time filesystem mode guard. Provider command
construction, login, and outcome interpretation remain out of scope.
"""

from __future__ import annotations

import ctypes
import getpass
import os
import stat
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Final, Iterator, Mapping, Sequence

from arena_runtime.audit import validate_audit_environment
from arena_runtime.process import (
    DEFAULT_STREAM_LIMIT,
    ProcessFacts,
    ProcessSupervisorError,
    run_process,
)

REPLICAS_DIRECTORY: Final[str] = "replicas"
READ_ONLY_AREAS: Final[tuple[str, ...]] = ("RULES.md", "PROMPT.md", "state")
WRITABLE_AREAS: Final[tuple[str, ...]] = ("agent", "outbox")

_TOP_LEVEL_AREAS: Final[frozenset[str]] = frozenset(
    (*READ_ONLY_AREAS, *WRITABLE_AREAS)
)
_MINIMAL_ENVIRONMENT_KEYS: Final[frozenset[str]] = frozenset(
    {
        "LANG",
        "LC_ALL",
        "PATH",
        "PATHEXT",
        "SystemRoot",
        "TEMP",
        "TMP",
        "TMPDIR",
        "WINDIR",
    }
)
_DACL_SECURITY_INFORMATION: Final[int] = 0x00000004
_WINDOWS_ACL_TIMEOUT_SECONDS: Final[float] = 10.0


class IsolationError(ValueError):
    """Unsafe replica launch boundary with a stable field path."""

    def __init__(self, path: str, message: str) -> None:
        self.path = path
        self.message = message
        super().__init__(f"{path}: {message}")


@dataclass(frozen=True)
class ReplicaLaunch:
    """Validated launch inputs for exactly one replica workspace."""

    season_root: Path
    replicas_root: Path
    replica_id: str
    workspace: Path
    credential_store: Path | None
    environment_items: tuple[tuple[str, str], ...]
    read_only_paths: tuple[Path, ...]
    writable_paths: tuple[Path, ...]

    def environment(self) -> dict[str, str]:
        """Return a fresh mutable copy for subprocess launch."""

        return dict(self.environment_items)


@dataclass(frozen=True)
class _WindowsDaclSnapshot:
    path: Path
    descriptor: bytes


def prepare_replica_launch(
    season_root: Path | str,
    replica_id: str,
    *,
    credential_store: Path | str | None = None,
    host_environment: Mapping[str, str] | None = None,
) -> ReplicaLaunch:
    """Validate and freeze one direct replica launch boundary."""

    season = _require_resolved_directory(season_root, path="season_root")
    replica = _require_replica_id(replica_id)
    replicas_root = _require_child_directory(
        season / REPLICAS_DIRECTORY,
        parent=season,
        path="replicas_root",
    )
    workspace = _require_child_directory(
        replicas_root / replica,
        parent=replicas_root,
        path="workspace",
    )
    _reject_links(workspace)
    _require_workspace_layout(workspace)

    resolved_credential_store: Path | None = None
    if credential_store is not None:
        resolved_credential_store = _require_resolved_directory(
            credential_store,
            path="credential_store",
        )
        if resolved_credential_store == season or resolved_credential_store.is_relative_to(
            season
        ):
            raise IsolationError(
                "credential_store",
                "must be outside the season and replica workspaces",
            )

    environment = _minimal_environment(
        host_environment or {},
        replica_id=replica,
        workspace=workspace,
    )
    return ReplicaLaunch(
        season_root=season,
        replicas_root=replicas_root,
        replica_id=replica,
        workspace=workspace,
        credential_store=resolved_credential_store,
        environment_items=tuple(sorted(environment.items())),
        read_only_paths=tuple(workspace / name for name in READ_ONLY_AREAS),
        writable_paths=tuple(workspace / name for name in WRITABLE_AREAS),
    )


def resolve_replica_path(
    launch: ReplicaLaunch,
    candidate: Path | str,
    *,
    writable: bool = False,
) -> Path:
    """Resolve a runtime path inside one replica and optionally require write scope."""

    _require_launch(launch)
    if not isinstance(candidate, (Path, str)):
        raise IsolationError("path", "expected a path")
    path = Path(candidate)
    if ".." in path.parts:
        raise IsolationError("path", "must not contain parent traversal")
    combined = path if path.is_absolute() else launch.workspace / path
    resolved = combined.resolve(strict=False)
    if not resolved.is_relative_to(launch.workspace):
        raise IsolationError("path", "must stay within the replica workspace")
    _reject_link_chain(launch.workspace, combined)
    if writable and not any(
        resolved == root or resolved.is_relative_to(root)
        for root in launch.writable_paths
    ):
        raise IsolationError(
            "path",
            "writable paths are limited to agent/ and outbox/",
        )
    return resolved


@contextmanager
def enforce_workspace_permissions(launch: ReplicaLaunch) -> Iterator[None]:
    """Temporarily apply the R8 read/write filesystem mode policy."""

    _require_launch(launch)
    _reject_links(launch.workspace)
    snapshot = _mode_snapshot(launch.workspace)
    windows_dacls: tuple[_WindowsDaclSnapshot, ...] = ()
    try:
        _apply_workspace_modes(launch)
        if os.name == "nt":
            state_root = launch.workspace / "state"
            windows_dacls = _capture_windows_dacls(
                (
                    launch.workspace,
                    state_root,
                    *tuple(state_root.rglob("*")),
                )
            )
            _apply_windows_write_denials(launch)
        yield
    finally:
        try:
            if windows_dacls:
                _restore_windows_dacls(windows_dacls)
        finally:
            _restore_modes(snapshot)


def run_isolated_process(
    launch: ReplicaLaunch,
    argv: Sequence[str],
    *,
    deadline: datetime,
    stdout_limit: int = DEFAULT_STREAM_LIMIT,
    stderr_limit: int = DEFAULT_STREAM_LIMIT,
) -> ProcessFacts:
    """Run R7 with the validated replica as cwd under the R8 mode guard."""

    _require_launch(launch)
    with enforce_workspace_permissions(launch):
        try:
            return run_process(
                argv,
                cwd=launch.workspace,
                environment=launch.environment(),
                deadline=deadline,
                stdout_limit=stdout_limit,
                stderr_limit=stderr_limit,
            )
        except ProcessSupervisorError:
            raise


def _minimal_environment(
    host_environment: Mapping[str, str],
    *,
    replica_id: str,
    workspace: Path,
) -> dict[str, str]:
    if not isinstance(host_environment, Mapping):
        raise IsolationError("host_environment", "expected a mapping")
    environment: dict[str, str] = {}
    for key in _MINIMAL_ENVIRONMENT_KEYS:
        if key not in host_environment:
            continue
        value = host_environment[key]
        if not isinstance(value, str):
            raise IsolationError(f"host_environment.{key}", "expected a string")
        environment[key] = value
    environment["ARENA_REPLICA_ID"] = replica_id
    environment["ARENA_WORKSPACE"] = str(workspace)
    try:
        validate_audit_environment(environment)
    except ValueError as exc:
        path = getattr(exc, "path", "host_environment")
        message = getattr(exc, "message", str(exc))
        raise IsolationError(path, message) from exc
    return environment


def _require_workspace_layout(workspace: Path) -> None:
    required_files = ("RULES.md", "PROMPT.md")
    required_directories = ("state", "agent", "outbox")
    for name in required_files:
        if not (workspace / name).is_file():
            raise IsolationError(f"workspace.{name}", "required file is missing")
    for name in required_directories:
        if not (workspace / name).is_dir():
            raise IsolationError(f"workspace.{name}", "required directory is missing")
    for child in workspace.iterdir():
        if child.name not in _TOP_LEVEL_AREAS:
            raise IsolationError(
                f"workspace.{child.name}",
                "unexpected top-level workspace path",
            )


def _require_replica_id(value: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise IsolationError(
            "replica_id",
            "must be a non-empty string without padding",
        )
    if value in {".", ".."} or "/" in value or "\\" in value:
        raise IsolationError("replica_id", "must be one direct directory name")
    return value


def _require_resolved_directory(value: Path | str, *, path: str) -> Path:
    if not isinstance(value, (Path, str)):
        raise IsolationError(path, "expected a path")
    candidate = Path(value)
    if not candidate.is_absolute():
        raise IsolationError(path, "must be absolute")
    resolved = candidate.resolve(strict=False)
    if resolved != candidate or ".." in candidate.parts:
        raise IsolationError(path, "must be resolved")
    if not resolved.is_dir():
        raise IsolationError(path, "must be an existing directory")
    if _is_link_or_junction(candidate):
        raise IsolationError(path, "symlink or junction is prohibited")
    return resolved


def _require_child_directory(value: Path, *, parent: Path, path: str) -> Path:
    if _is_link_or_junction(value):
        raise IsolationError(path, "symlink or junction is prohibited")
    resolved = value.resolve(strict=False)
    if resolved.parent != parent or not resolved.is_dir():
        raise IsolationError(path, "must be one existing direct child directory")
    return resolved


def _reject_links(root: Path) -> None:
    if _is_link_or_junction(root):
        raise IsolationError("workspace", "symlink or junction is prohibited")
    for path in root.rglob("*"):
        if _is_link_or_junction(path):
            relative = path.relative_to(root).as_posix()
            raise IsolationError(
                f"workspace.{relative}",
                "symlink or junction is prohibited",
            )


def _reject_link_chain(workspace: Path, candidate: Path) -> None:
    current = workspace
    try:
        relative = candidate.relative_to(workspace)
    except ValueError:
        return
    for part in relative.parts:
        current = current / part
        if current.exists() and _is_link_or_junction(current):
            raise IsolationError("path", "symlink or junction is prohibited")


def _is_link_or_junction(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    return bool(is_junction()) if callable(is_junction) else False


def _mode_snapshot(root: Path) -> tuple[tuple[Path, int], ...]:
    paths = (root, *tuple(root.rglob("*")))
    return tuple(
        (path, stat.S_IMODE(path.stat(follow_symlinks=False).st_mode))
        for path in paths
    )


def _apply_workspace_modes(launch: ReplicaLaunch) -> None:
    _chmod(launch.workspace, 0o555)
    for root in launch.read_only_paths:
        _chmod_tree(root, directory_mode=0o555, file_mode=0o444)
    for root in launch.writable_paths:
        _chmod_tree(root, directory_mode=0o700, file_mode=0o600)


def _chmod_tree(root: Path, *, directory_mode: int, file_mode: int) -> None:
    paths = (root, *tuple(root.rglob("*")))
    for path in paths:
        _chmod(path, directory_mode if path.is_dir() else file_mode)


def _chmod(path: Path, mode: int) -> None:
    try:
        os.chmod(path, mode)
    except OSError as exc:
        raise IsolationError(
            "workspace",
            f"cannot enforce permissions on {path.name!r}: {exc}",
        ) from exc


def _restore_modes(snapshot: tuple[tuple[Path, int], ...]) -> None:
    failure: OSError | None = None
    for path, mode in reversed(snapshot):
        try:
            if path.exists():
                os.chmod(path, mode)
        except OSError as exc:
            failure = failure or exc
    if failure is not None:
        raise IsolationError("workspace", f"cannot restore permissions: {failure}")


def _capture_windows_dacls(
    paths: Sequence[Path],
) -> tuple[_WindowsDaclSnapshot, ...]:
    return tuple(
        _WindowsDaclSnapshot(path=path, descriptor=_get_windows_dacl(path))
        for path in paths
    )


def _apply_windows_write_denials(launch: ReplicaLaunch) -> None:
    principal = getpass.getuser()
    if not principal:
        raise IsolationError("workspace", "cannot identify Windows launch user")
    _run_icacls(
        launch.workspace,
        f"{principal}:(W,D,DC)",
        cwd=launch.workspace,
    )
    _run_icacls(
        launch.workspace / "state",
        f"{principal}:(OI)(CI)(W,D,DC)",
        cwd=launch.workspace,
    )


def _run_icacls(target: Path, denial: str, *, cwd: Path) -> None:
    system_root = os.environ.get("SystemRoot") or os.environ.get("WINDIR")
    if not system_root:
        raise IsolationError("workspace", "Windows system root is unavailable")
    executable = (Path(system_root) / "System32" / "icacls.exe").resolve()
    environment = {
        "SystemRoot": system_root,
        "WINDIR": system_root,
    }
    path_value = os.environ.get("PATH")
    if path_value is not None:
        environment["PATH"] = path_value
    facts = run_process(
        (str(executable), str(target), "/deny", denial, "/q"),
        cwd=cwd,
        environment=environment,
        deadline=datetime.now(timezone.utc)
        + timedelta(seconds=_WINDOWS_ACL_TIMEOUT_SECONDS),
        stdout_limit=65536,
        stderr_limit=65536,
    )
    if facts.timed_out or facts.exit_status != 0:
        detail = (facts.stderr or facts.stdout).decode(errors="replace").strip()
        raise IsolationError(
            "workspace",
            f"cannot apply Windows write isolation: {detail or facts.exit_status}",
        )


def _get_windows_dacl(path: Path) -> bytes:
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    get_file_security = advapi32.GetFileSecurityW
    get_file_security.argtypes = (
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_uint32),
    )
    get_file_security.restype = ctypes.c_int
    required = ctypes.c_uint32()
    get_file_security(
        str(path),
        _DACL_SECURITY_INFORMATION,
        None,
        0,
        ctypes.byref(required),
    )
    if required.value == 0:
        error = ctypes.get_last_error()
        raise IsolationError(
            "workspace",
            f"cannot read Windows ACL for {path.name!r}: error {error}",
        )
    buffer = ctypes.create_string_buffer(required.value)
    if not get_file_security(
        str(path),
        _DACL_SECURITY_INFORMATION,
        buffer,
        required.value,
        ctypes.byref(required),
    ):
        error = ctypes.get_last_error()
        raise IsolationError(
            "workspace",
            f"cannot read Windows ACL for {path.name!r}: error {error}",
        )
    return bytes(buffer.raw[: required.value])


def _restore_windows_dacls(
    snapshots: Sequence[_WindowsDaclSnapshot],
) -> None:
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    set_file_security = advapi32.SetFileSecurityW
    set_file_security.argtypes = (
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_void_p,
    )
    set_file_security.restype = ctypes.c_int
    failure: tuple[Path, int] | None = None
    for snapshot in snapshots:
        descriptor = ctypes.create_string_buffer(snapshot.descriptor)
        if not set_file_security(
            str(snapshot.path),
            _DACL_SECURITY_INFORMATION,
            descriptor,
        ):
            failure = failure or (snapshot.path, ctypes.get_last_error())
    if failure is not None:
        path, error = failure
        raise IsolationError(
            "workspace",
            f"cannot restore Windows ACL for {path.name!r}: error {error}",
        )


def _require_launch(value: ReplicaLaunch) -> None:
    if not isinstance(value, ReplicaLaunch):
        raise IsolationError("launch", "expected ReplicaLaunch")
