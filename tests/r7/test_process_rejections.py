"""R7: invalid launch boundaries fail before process start."""

from datetime import datetime
from pathlib import Path

import pytest

from arena_runtime.process import ProcessSupervisorError, run_process

from .conftest import argv, deadline, sanitized_environment


def test_naive_deadline_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ProcessSupervisorError) as exc:
        run_process(
            argv("success"),
            cwd=tmp_path,
            environment=sanitized_environment(),
            deadline=datetime(2026, 8, 17, 10, 15),
        )

    assert exc.value.path == "deadline"


def test_past_deadline_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ProcessSupervisorError) as exc:
        run_process(
            argv("success"),
            cwd=tmp_path,
            environment=sanitized_environment(),
            deadline=deadline(-1),
        )

    assert exc.value.path == "deadline"


def test_relative_cwd_is_rejected() -> None:
    with pytest.raises(ProcessSupervisorError) as exc:
        run_process(
            argv("success"),
            cwd=Path("relative"),
            environment=sanitized_environment(),
            deadline=deadline(),
        )

    assert exc.value.path == "cwd"


def test_missing_cwd_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ProcessSupervisorError) as exc:
        run_process(
            argv("success"),
            cwd=tmp_path / "missing",
            environment=sanitized_environment(),
            deadline=deadline(),
        )

    assert exc.value.path == "cwd"


def test_secret_environment_is_rejected(tmp_path: Path) -> None:
    environment = sanitized_environment()
    environment["PROVIDER_API_KEY"] = "synthetic-secret"

    with pytest.raises(ProcessSupervisorError) as exc:
        run_process(
            argv("success"),
            cwd=tmp_path,
            environment=environment,
            deadline=deadline(),
        )

    assert exc.value.path == "environment.PROVIDER_API_KEY"


@pytest.mark.parametrize(
    ("command", "path"),
    [
        ((), "argv"),
        (("",), "argv.0"),
        (("python", 3), "argv.1"),
    ],
)
def test_invalid_argv_is_rejected(
    tmp_path: Path,
    command: tuple[object, ...],
    path: str,
) -> None:
    with pytest.raises(ProcessSupervisorError) as exc:
        run_process(
            command,  # type: ignore[arg-type]
            cwd=tmp_path,
            environment=sanitized_environment(),
            deadline=deadline(),
        )

    assert exc.value.path == path
