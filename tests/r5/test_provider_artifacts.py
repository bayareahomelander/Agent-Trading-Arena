"""R5: provider streams are redacted, checksummed, and immutable."""

import hashlib
from dataclasses import replace
from pathlib import Path

import pytest

from arena_runtime.audit import (
    REDACTION_MARKER,
    AuditArchive,
    AuditArchiveError,
    redact_provider_bytes,
)

from .conftest import (
    PROVIDER_OUTPUT,
    SYNTHETIC_API_KEY,
    SYNTHETIC_BEARER_TOKEN,
    SYNTHETIC_OAUTH_TOKEN,
    audit_event,
)


def test_synthetic_oauth_and_api_tokens_never_reach_archive_bytes(
    tmp_path: Path,
) -> None:
    archive = AuditArchive(tmp_path / "archive")
    artifact = archive.write_provider_artifact(
        "provider/round/replica/stdout.log",
        PROVIDER_OUTPUT,
    )
    event = replace(
        audit_event("replica_completed"),
        provider_artifacts=(artifact,),
    )
    archive.append_event(event)

    all_bytes = b"".join(
        path.read_bytes() for path in archive.root.rglob("*") if path.is_file()
    )
    assert SYNTHETIC_API_KEY not in all_bytes
    assert SYNTHETIC_OAUTH_TOKEN not in all_bytes
    assert SYNTHETIC_BEARER_TOKEN not in all_bytes
    assert REDACTION_MARKER in all_bytes
    assert b"ordinary output remains" in all_bytes


def test_artifact_reference_and_sidecar_store_sanitized_sha256(
    tmp_path: Path,
) -> None:
    archive = AuditArchive(tmp_path / "archive")
    relative = "provider/round/replica/stderr.log"
    artifact = archive.write_provider_artifact(relative, PROVIDER_OUTPUT)
    sanitized = redact_provider_bytes(PROVIDER_OUTPUT)
    expected = hashlib.sha256(sanitized).hexdigest()

    assert artifact.path == relative
    assert artifact.checksum == expected
    assert (archive.root / relative).read_bytes() == sanitized
    assert (archive.root / f"{relative}.sha256").read_text(
        encoding="ascii"
    ) == expected + "\n"


def test_same_artifact_bytes_are_idempotent(tmp_path: Path) -> None:
    archive = AuditArchive(tmp_path / "archive")
    relative = "provider/round/replica/transcript.log"

    first = archive.write_provider_artifact(relative, PROVIDER_OUTPUT)
    second = archive.write_provider_artifact(relative, PROVIDER_OUTPUT)

    assert second == first


def test_existing_artifact_cannot_be_overwritten(tmp_path: Path) -> None:
    archive = AuditArchive(tmp_path / "archive")
    relative = "provider/round/replica/stdout.log"
    archive.write_provider_artifact(relative, b"first safe bytes\n")

    with pytest.raises(AuditArchiveError) as exc:
        archive.write_provider_artifact(relative, b"different safe bytes\n")

    assert exc.value.path == "relative_path"


def test_append_rejects_missing_referenced_artifact(tmp_path: Path) -> None:
    archive = AuditArchive(tmp_path / "archive")
    missing = archive.write_provider_artifact(
        "provider/round/replica/stdout.log",
        b"safe\n",
    )
    (archive.root / missing.path).unlink()
    event = replace(
        audit_event("replica_completed"),
        provider_artifacts=(missing,),
    )

    with pytest.raises(AuditArchiveError) as exc:
        archive.append_event(event)

    assert exc.value.path == "provider_artifacts.path"
    assert not archive.events_path.exists()


def test_append_rejects_artifact_checksum_mismatch(tmp_path: Path) -> None:
    archive = AuditArchive(tmp_path / "archive")
    artifact = archive.write_provider_artifact(
        "provider/round/replica/stdout.log",
        b"safe\n",
    )
    wrong = replace(artifact, checksum="0" * 64)
    event = replace(
        audit_event("replica_completed"),
        provider_artifacts=(wrong,),
    )

    with pytest.raises(AuditArchiveError) as exc:
        archive.append_event(event)

    assert exc.value.path == "provider_artifacts.checksum"


def test_provider_artifact_requires_bytes(tmp_path: Path) -> None:
    archive = AuditArchive(tmp_path / "archive")

    with pytest.raises(AuditArchiveError) as exc:
        archive.write_provider_artifact(
            "provider/round/replica/stdout.log",
            "not bytes",  # type: ignore[arg-type]
        )

    assert exc.value.path == "provider_bytes"
