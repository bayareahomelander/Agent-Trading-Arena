"""R5: normalized audit JSONL is append-only and deterministic."""

from dataclasses import replace
from pathlib import Path

from arena_runtime.audit import AuditArchive, parse_audit_event

from .conftest import PROVIDER_OUTPUT, audit_event


def test_two_events_append_in_order_as_single_line_json(tmp_path: Path) -> None:
    archive = AuditArchive(tmp_path / "archive")
    first = audit_event("commit_started")
    second = audit_event("commit_completed")

    archive.append_event(first)
    archive.append_event(second)

    lines = archive.events_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert [parse_audit_event(line).event_type for line in lines] == [
        "commit_started",
        "commit_completed",
    ]
    assert all("\n" not in line for line in lines)


def test_second_archive_run_produces_identical_bytes(tmp_path: Path) -> None:
    trees: list[dict[str, bytes]] = []
    for name in ("first", "second"):
        archive = AuditArchive(tmp_path / name)
        artifact = archive.write_provider_artifact(
            "provider/round/replica/stdout.log",
            PROVIDER_OUTPUT,
        )
        event = replace(
            audit_event("replica_completed"),
            provider_artifacts=(artifact,),
        )
        archive.append_event(event)
        trees.append(
            {
                path.relative_to(archive.root).as_posix(): path.read_bytes()
                for path in archive.root.rglob("*")
                if path.is_file()
            }
        )

    assert trees[0] == trees[1]


def test_archive_root_and_returned_paths_are_resolved(tmp_path: Path) -> None:
    archive = AuditArchive(tmp_path / "nested" / "archive")

    assert archive.root.is_absolute()
    assert archive.root == archive.root.resolve()
    assert archive.append_event(audit_event()).is_relative_to(archive.root)
