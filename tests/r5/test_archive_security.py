"""R5: archive paths, auth caches, and environment metadata stay safe."""

from pathlib import Path

import pytest

from arena_runtime.audit import (
    AuditArchive,
    AuditArchiveError,
    validate_audit_environment,
)


@pytest.mark.parametrize(
    "relative_path",
    [
        "../escape.log",
        "provider/../../escape.log",
        "/absolute/escape.log",
        "C:\\outside\\escape.log",
        "normalized/events.jsonl",
    ],
)
def test_artifact_traversal_or_wrong_prefix_is_rejected(
    tmp_path: Path,
    relative_path: str,
) -> None:
    archive = AuditArchive(tmp_path / "archive")

    with pytest.raises(AuditArchiveError) as exc:
        archive.write_provider_artifact(relative_path, b"safe\n")

    assert exc.value.path == "relative_path"
    assert not (tmp_path / "escape.log").exists()


@pytest.mark.parametrize(
    "source_path",
    [
        "/home/test/.provider/auth.json",
        "/home/test/.provider/auth-cache/state.json",
        "/home/test/.provider/credentials.json",
        "C:\\Users\\test\\provider\\tokens\\state.json",
    ],
)
def test_auth_cache_source_paths_are_rejected_before_write(
    tmp_path: Path,
    source_path: str,
) -> None:
    archive = AuditArchive(tmp_path / "archive")

    with pytest.raises(AuditArchiveError) as exc:
        archive.write_provider_artifact(
            "provider/round/replica/stdout.log",
            b"safe\n",
            source_path=source_path,
        )

    assert exc.value.path == "source_path"
    assert not (archive.root / "provider").exists()


def test_auth_cache_target_path_is_rejected(tmp_path: Path) -> None:
    archive = AuditArchive(tmp_path / "archive")

    with pytest.raises(AuditArchiveError) as exc:
        archive.write_provider_artifact(
            "provider/auth-cache/state.json",
            b"safe\n",
        )

    assert exc.value.path == "relative_path"


@pytest.mark.parametrize(
    "environment",
    [
        {"PROVIDER_API_KEY": "synthetic"},
        {"ACCESS_TOKEN": "synthetic"},
        {"AWS_SHARED_CREDENTIALS_FILE": "synthetic"},
        {"STATUS": "Bearer bearer.secret.value"},
    ],
)
def test_secret_bearing_environment_is_rejected(
    environment: dict[str, str],
) -> None:
    with pytest.raises(AuditArchiveError) as exc:
        validate_audit_environment(environment)

    assert exc.value.path.startswith("environment.")


def test_safe_environment_is_validated_but_never_archived(tmp_path: Path) -> None:
    archive = AuditArchive(tmp_path / "archive")
    safe_environment = {
        "LANG": "en_US.UTF-8",
        "PATH": "C:/safe/bin",
        "TOKENIZERS_PARALLELISM": "false",
    }

    archive.write_provider_artifact(
        "provider/round/replica/stdout.log",
        b"safe output\n",
        environment=safe_environment,
    )

    all_bytes = b"".join(
        path.read_bytes() for path in archive.root.rglob("*") if path.is_file()
    )
    assert b"TOKENIZERS_PARALLELISM" not in all_bytes
    assert b"C:/safe/bin" not in all_bytes


def test_archive_root_that_is_a_file_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "archive"
    root.write_bytes(b"not a directory")

    with pytest.raises(AuditArchiveError) as exc:
        AuditArchive(root)

    assert exc.value.path == "root"
