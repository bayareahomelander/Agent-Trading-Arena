"""Manual operator entry point.

R25 dispatches to existing runtime APIs. It does not interpret decisions,
choose disposition policy, or wait on a wall clock.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from arena_kernel.marketdata import FixtureVendor
from arena_kernel.schema.market import parse_snapshot
from arena_kernel.schema.portfolio import parse_portfolio
from arena_kernel.types import parse_et_timestamp
from arena_runtime.adapters.fake import FakeRunner, FakeRunnerScript
from arena_runtime.audit import AuditArchive
from arena_runtime.disposition import decide_round_disposition
from arena_runtime.orchestrator import (
    CLOSE_DEFERRED,
    CLOSE_MARKED,
    PreflightBarrierResult,
    ReplicaDuty,
    collect_sealed_decisions,
    evaluate_candidates,
    mark_official_close,
    preflight_round,
    publish_candidates,
    run_decision_barrier,
)
from arena_runtime.registration import parse_runtime_registration
from arena_runtime.runner import (
    RUNNER_CONTRACT_VERSION,
    PreflightResult,
    RunnerRequest,
)

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_PAUSED = 10
EXIT_DEFERRED = 11
EXIT_NOT_COMMITTED = 12


class CliError(ValueError):
    """Operator input is unusable before any runtime work starts."""


def main(argv: Sequence[str] | None = None) -> int:
    """Parse frozen operator arguments and dispatch one command."""

    parser = _parser()
    try:
        args = parser.parse_args(list(argv) if argv is not None else None)
    except SystemExit as exc:
        code = exc.code
        return code if isinstance(code, int) else EXIT_USAGE
    handlers = {
        "preflight": cmd_preflight,
        "run-round": cmd_run_round,
        "close": cmd_close,
    }
    handler = handlers.get(args.command)
    if handler is None:
        parser.print_help()
        return EXIT_USAGE
    try:
        return handler(args)
    except CliError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_USAGE
    except Exception as exc:  # noqa: BLE001 - operator surface returns a status
        print(str(exc), file=sys.stderr)
        return EXIT_ERROR


def cmd_preflight(args: argparse.Namespace) -> int:
    spec = _load_spec(args.spec)
    archive_root = _existing_dir(spec, "archive", create=True)
    registrations = [
        parse_runtime_registration(_read_json(path))
        for path in _existing_paths(spec, "registrations")
    ]
    duties = tuple(
        ReplicaDuty(
            item["product_id"],
            item["replica_id"],
            item["status"],
        )
        for item in _require_list(spec, "duties")
    )
    requests = tuple(_parse_request(item) for item in _require_list(spec, "requests"))
    for request in requests:
        _require_existing_dir(request.workspace, name="workspace")
    archive = AuditArchive(archive_root)
    runner = FakeRunner(_parse_scripts(spec), archive=archive)
    result = preflight_round(
        registrations=registrations,
        duties=duties,
        requests=requests,
        runners=_runners(spec, runner),
        common_data_status=str(spec["common_data_status"]),
        archive=archive,
        decided_at=_aware(spec["decided_at"]),
    )
    status = "ready" if result.ready else "paused"
    print(status)
    return EXIT_OK if result.ready else EXIT_PAUSED


def cmd_run_round(args: argparse.Namespace) -> int:
    spec = _load_spec(args.spec)
    archive_root = _existing_dir(spec, "archive", create=True)
    books_root = _existing_dir(spec, "books_root", create=True)
    staging_root = _existing_dir(spec, "staging_root", create=True)
    snapshot = parse_snapshot(_read_text(_existing_file(spec, "snapshot")))
    requests = tuple(_parse_request(item) for item in _require_list(spec, "requests"))
    workspaces = {
        request.replica_id: _require_existing_dir(request.workspace, name="workspace")
        for request in requests
    }
    books = {
        replica_id: parse_portfolio(_read_text(path))
        for replica_id, path in _existing_mapping(spec, "books").items()
    }
    archive = AuditArchive(archive_root)
    runner = FakeRunner(_parse_scripts(spec), archive=archive)
    barrier = run_decision_barrier(
        preflight=_parse_preflight(spec["preflight"]),
        requests=requests,
        runners=_runners(spec, runner),
        snapshot_checksum=str(spec["snapshot_checksum"]),
    )
    disposition = decide_round_disposition(
        barrier.results,
        str(spec["common_data_status"]),
    )
    collection = collect_sealed_decisions(
        barrier=barrier,
        disposition=disposition,
        workspaces=workspaces,
        staging_root=staging_root,
    )
    candidates = evaluate_candidates(
        collection=collection,
        snapshot=snapshot,
        books=books,
    )
    publication = publish_candidates(
        candidates=candidates,
        books_root=books_root,
        archive=archive,
        published_at=_aware(spec["published_at"]),
    )
    status = "committed" if publication.committed else "not_committed"
    print(status)
    return EXIT_OK if publication.committed else EXIT_NOT_COMMITTED


def cmd_close(args: argparse.Namespace) -> int:
    spec = _load_spec(args.spec)
    books_root = _existing_dir(spec, "books_root", create=False)
    vendor_root = _existing_dir(spec, "vendor", create=False)
    result = mark_official_close(
        books_root=books_root,
        vendor=FixtureVendor(vendor_root),
        session_date=date.fromisoformat(str(spec["session_date"])),
        replica_ids=tuple(_require_list(spec, "replica_ids")),
        marked_at=_aware(spec["marked_at"]),
    )
    print(result.status)
    if result.status == CLOSE_MARKED:
        return EXIT_OK
    if result.status == CLOSE_DEFERRED:
        return EXIT_DEFERRED
    return EXIT_ERROR


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="arena-runtime",
        description="Manual one-shot operator commands. Not a season daemon.",
    )
    sub = parser.add_subparsers(dest="command")
    for name in ("preflight", "run-round", "close"):
        command = sub.add_parser(name)
        command.add_argument("--spec", required=True, type=Path)
    return parser


def _load_spec(path: Path) -> dict[str, Any]:
    resolved = Path(path)
    if not resolved.is_file():
        raise CliError(f"spec not found: {resolved}")
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CliError(f"spec is not JSON: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise CliError("spec must be a JSON object")
    return payload


def _existing_file(spec: Mapping[str, Any], key: str) -> Path:
    path = Path(str(spec[key]))
    if not path.is_file():
        raise CliError(f"{key} not found: {path}")
    return path


def _existing_dir(spec: Mapping[str, Any], key: str, *, create: bool) -> Path:
    path = Path(str(spec[key]))
    if create:
        path.mkdir(parents=True, exist_ok=True)
    if not path.is_dir():
        raise CliError(f"{key} not found: {path}")
    return path.resolve()


def _existing_paths(spec: Mapping[str, Any], key: str) -> tuple[Path, ...]:
    paths = []
    for item in _require_list(spec, key):
        path = Path(str(item))
        if not path.is_file():
            raise CliError(f"{key} not found: {path}")
        paths.append(path)
    return tuple(paths)


def _existing_mapping(spec: Mapping[str, Any], key: str) -> dict[str, Path]:
    raw = spec.get(key)
    if not isinstance(raw, dict):
        raise CliError(f"{key} must be an object of existing files")
    resolved: dict[str, Path] = {}
    for replica_id, value in raw.items():
        path = Path(str(value))
        if not path.is_file():
            raise CliError(f"{key}.{replica_id} not found: {path}")
        resolved[str(replica_id)] = path
    return resolved


def _require_existing_dir(path: Path, *, name: str) -> Path:
    if not path.is_dir():
        raise CliError(f"{name} not found: {path}")
    return path.resolve()


def _require_list(spec: Mapping[str, Any], key: str) -> list[Any]:
    value = spec.get(key)
    if not isinstance(value, list):
        raise CliError(f"{key} must be a list")
    return value


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _aware(value: object) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise CliError("timestamp must be timezone-aware")
        return value
    return parse_et_timestamp(str(value))


def _parse_request(item: object) -> RunnerRequest:
    if not isinstance(item, dict):
        raise CliError("requests must contain objects")
    workspace = Path(str(item["workspace"]))
    instruction = item.get("launch_instruction", "Frozen launch instruction")
    if isinstance(instruction, str):
        instruction_bytes = instruction.encode("utf-8")
    else:
        raise CliError("launch_instruction must be a string")
    return RunnerRequest(
        contract_version=str(item.get("contract_version", RUNNER_CONTRACT_VERSION)),
        product_id=str(item["product_id"]),
        replica_id=str(item["replica_id"]),
        round_id=str(item["round_id"]),
        workspace=workspace,
        model_reference=str(item.get("model_reference", "registration:model")),
        configuration_reference=str(
            item.get("configuration_reference", "registration:configuration")
        ),
        launch_instruction=instruction_bytes,
        deadline=_aware(item["deadline"]),
        session_reference=item.get("session_reference"),
    )


def _parse_scripts(spec: Mapping[str, Any]) -> tuple[FakeRunnerScript, ...]:
    scripts = []
    for item in _require_list(spec, "fake_scripts"):
        if not isinstance(item, dict):
            raise CliError("fake_scripts must contain objects")
        scripts.append(
            FakeRunnerScript(
                product_id=str(item["product_id"]),
                replica_id=str(item["replica_id"]),
                round_id=str(item["round_id"]),
                preflight_ready=bool(item.get("preflight_ready", True)),
                preflight_failure_reason=item.get("preflight_failure_reason"),
                preflight_started_at=_aware(item["preflight_started_at"]),
                preflight_finished_at=_aware(item["preflight_finished_at"]),
                outcome=str(item.get("outcome", "completed")),
                run_started_at=_aware(item["run_started_at"]),
                run_finished_at=_aware(item["run_finished_at"]),
                exit_status=item.get("exit_status"),
                decision_bytes=(
                    str(item["decision_text"]).encode("utf-8")
                    if "decision_text" in item
                    else None
                ),
                session_reference=item.get("session_reference"),
            )
        )
    return tuple(scripts)


def _runners(spec: Mapping[str, Any], runner: FakeRunner) -> dict[str, FakeRunner]:
    product_ids = spec.get("product_ids")
    if not isinstance(product_ids, list) or not product_ids:
        raise CliError("product_ids must list every product")
    return {str(product_id): runner for product_id in product_ids}


def _parse_preflight(item: object) -> PreflightBarrierResult:
    if not isinstance(item, dict):
        raise CliError("preflight must be an object")
    results = []
    for raw in item.get("preflight_results", []):
        if not isinstance(raw, dict):
            raise CliError("preflight_results must contain objects")
        results.append(
            PreflightResult(
                contract_version=str(
                    raw.get("contract_version", RUNNER_CONTRACT_VERSION)
                ),
                product_id=str(raw["product_id"]),
                replica_id=str(raw["replica_id"]),
                round_id=str(raw["round_id"]),
                ready=bool(raw["ready"]),
                started_at=_aware(raw["started_at"]),
                finished_at=_aware(raw["finished_at"]),
                failure_reason=raw.get("failure_reason"),
            )
        )
    return PreflightBarrierResult(
        contract_version=str(item.get("contract_version", RUNNER_CONTRACT_VERSION)),
        round_id=str(item["round_id"]),
        ready=bool(item["ready"]),
        reason_codes=tuple(item.get("reason_codes", ())),
        due_replica_ids=tuple(item["due_replica_ids"]),
        skipped_replica_ids=tuple(item.get("skipped_replica_ids", ())),
        preflight_results=tuple(results),
    )


if __name__ == "__main__":
    raise SystemExit(main())
