"""Deadline-bound process-tree supervision.

R7 launches literal argv without a shell, in an explicit working directory and
sanitized environment. It returns raw process facts only; provider meaning and
runner outcome classification belong to adapters.
"""

from __future__ import annotations

import os
import signal
import subprocess
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO, Final, Mapping, Sequence

from arena_runtime.audit import validate_audit_environment

DEFAULT_STREAM_LIMIT: Final[int] = 1024 * 1024
_TERMINATION_WAIT_SECONDS: Final[float] = 10.0


class ProcessSupervisorError(ValueError):
    """Invalid launch input or failed supervision with a stable field path."""

    def __init__(self, path: str, message: str) -> None:
        self.path = path
        self.message = message
        super().__init__(f"{path}: {message}")


@dataclass(frozen=True)
class ProcessFacts:
    """Raw launch, timing, exit, timeout, and bounded stream facts."""

    argv: tuple[str, ...]
    cwd: Path
    pid: int
    started_at: datetime
    finished_at: datetime
    exit_status: int
    timed_out: bool
    stdout: bytes
    stderr: bytes
    stdout_truncated: bool
    stderr_truncated: bool


def run_process(
    argv: Sequence[str],
    *,
    cwd: Path | str,
    environment: Mapping[str, str],
    deadline: datetime,
    stdout_limit: int = DEFAULT_STREAM_LIMIT,
    stderr_limit: int = DEFAULT_STREAM_LIMIT,
) -> ProcessFacts:
    """Launch and supervise one process tree until exit or absolute deadline."""

    command = _require_argv(argv)
    working_directory = _require_cwd(cwd)
    launch_environment = _require_environment(environment)
    absolute_deadline = _require_deadline(deadline)
    out_limit = _require_limit(stdout_limit, path="stdout_limit")
    err_limit = _require_limit(stderr_limit, path="stderr_limit")

    started_at = datetime.now(timezone.utc)
    if absolute_deadline.astimezone(timezone.utc) <= started_at:
        raise ProcessSupervisorError("deadline", "must be in the future")

    popen_options: dict[str, object] = {}
    if os.name == "nt":
        popen_options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        popen_options["start_new_session"] = True

    try:
        process = subprocess.Popen(
            list(command),
            cwd=working_directory,
            env=launch_environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            bufsize=0,
            **popen_options,
        )
    except OSError as exc:
        raise ProcessSupervisorError("argv.0", f"cannot launch executable: {exc}") from exc

    if process.stdout is None or process.stderr is None:
        _terminate_process_tree(process)
        raise ProcessSupervisorError("process", "stdout/stderr capture unavailable")

    stdout_collector = _BoundedCollector(process.stdout, out_limit)
    stderr_collector = _BoundedCollector(process.stderr, err_limit)
    stdout_collector.start()
    stderr_collector.start()

    timed_out = False
    try:
        remaining = max(
            0.0,
            (
                absolute_deadline.astimezone(timezone.utc)
                - datetime.now(timezone.utc)
            ).total_seconds(),
        )
        try:
            process.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            timed_out = True
            _terminate_process_tree(process)
        if process.poll() is None:
            process.wait(timeout=_TERMINATION_WAIT_SECONDS)
    except subprocess.TimeoutExpired as exc:
        _terminate_process_tree(process)
        raise ProcessSupervisorError(
            "process",
            "process tree did not terminate",
        ) from exc
    finally:
        if process.poll() is None:
            _terminate_process_tree(process)

    finished_at = datetime.now(timezone.utc)
    stdout, stdout_truncated = stdout_collector.finish()
    stderr, stderr_truncated = stderr_collector.finish()
    if process.returncode is None:
        raise ProcessSupervisorError("process", "missing exit status")

    return ProcessFacts(
        argv=command,
        cwd=working_directory,
        pid=process.pid,
        started_at=started_at,
        finished_at=finished_at,
        exit_status=process.returncode,
        timed_out=timed_out,
        stdout=stdout,
        stderr=stderr,
        stdout_truncated=stdout_truncated,
        stderr_truncated=stderr_truncated,
    )


class _BoundedCollector:
    def __init__(self, stream: BinaryIO, limit: int) -> None:
        self._stream = stream
        self._limit = limit
        self._buffer = bytearray()
        self._truncated = False
        self._error: OSError | None = None
        self._thread = threading.Thread(target=self._drain, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def finish(self) -> tuple[bytes, bool]:
        self._thread.join(timeout=_TERMINATION_WAIT_SECONDS)
        if self._thread.is_alive():
            raise ProcessSupervisorError("process", "stream collector did not finish")
        if self._error is not None:
            raise ProcessSupervisorError(
                "process",
                f"cannot capture process stream: {self._error}",
            ) from self._error
        return bytes(self._buffer), self._truncated

    def _drain(self) -> None:
        try:
            while True:
                chunk = self._stream.read(65536)
                if not chunk:
                    return
                remaining = self._limit - len(self._buffer)
                if remaining > 0:
                    self._buffer.extend(chunk[:remaining])
                if len(chunk) > remaining:
                    self._truncated = True
        except OSError as exc:
            self._error = exc
        finally:
            self._stream.close()


def _terminate_process_tree(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=False,
                check=False,
                timeout=_TERMINATION_WAIT_SECONDS,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.TimeoutExpired):
            process.kill()
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            return
        except OSError:
            process.kill()
    try:
        process.wait(timeout=_TERMINATION_WAIT_SECONDS)
    except subprocess.TimeoutExpired:
        process.kill()


def _require_argv(value: Sequence[str]) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ProcessSupervisorError("argv", "expected a sequence of strings")
    command = tuple(value)
    if not command:
        raise ProcessSupervisorError("argv", "must not be empty")
    for index, item in enumerate(command):
        path = f"argv.{index}"
        if not isinstance(item, str):
            raise ProcessSupervisorError(path, "expected a string")
        if not item or "\x00" in item:
            raise ProcessSupervisorError(path, "must be a non-empty string without NUL")
    return command


def _require_cwd(value: Path | str) -> Path:
    if not isinstance(value, (Path, str)):
        raise ProcessSupervisorError("cwd", "expected a path")
    path = Path(value)
    if not path.is_absolute():
        raise ProcessSupervisorError("cwd", "must be absolute")
    resolved = path.resolve(strict=False)
    if resolved != path or ".." in path.parts:
        raise ProcessSupervisorError("cwd", "must be resolved")
    if not resolved.is_dir():
        raise ProcessSupervisorError("cwd", "must be an existing directory")
    return resolved


def _require_environment(value: Mapping[str, str]) -> dict[str, str]:
    try:
        validate_audit_environment(value)
    except ValueError as exc:
        path = getattr(exc, "path", "environment")
        message = getattr(exc, "message", str(exc))
        raise ProcessSupervisorError(path, message) from exc
    return dict(value)


def _require_deadline(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise ProcessSupervisorError("deadline", "expected a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ProcessSupervisorError("deadline", "must be timezone-aware")
    return value


def _require_limit(value: int, *, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProcessSupervisorError(path, "expected a non-negative integer")
    if value < 0:
        raise ProcessSupervisorError(path, "must be non-negative")
    return value
