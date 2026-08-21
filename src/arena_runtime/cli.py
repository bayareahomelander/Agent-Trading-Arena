"""Manual operator entry point.

R25 dispatches to existing runtime APIs. E9 optionally waits for one round
start. This module does not interpret decisions or choose disposition policy.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from arena_kernel.calendar import ScheduledRound, parse_calendar, rounds_for_day
from arena_kernel.marketdata import FixtureVendor, Vendor
from arena_kernel.schema.errors import FieldError, SchemaError
from arena_kernel.schema.market import parse_snapshot
from arena_kernel.schema.portfolio import parse_portfolio
from arena_kernel.types import parse_et_timestamp
from arena_runtime.adapters.codex import CodexAdapter, CodexSessionStore
from arena_runtime.adapters.fake import FakeRunner, FakeRunnerScript
from arena_runtime.adapters.grok_build import (
    GrokBuildAdapter,
    GrokBuildSessionStore,
)
from arena_runtime.audit import AuditArchive
from arena_runtime.disposition import decide_round_disposition
from arena_runtime.orchestrator import (
    CLOSE_DEFERRED,
    CLOSE_MARKED,
    PreflightBarrierResult,
    collect_sealed_decisions,
    evaluate_candidates,
    mark_official_close,
    preflight_round,
    publish_candidates,
    run_decision_barrier,
)
from arena_runtime.isolation import prepare_replica_launch
from arena_runtime.operator_spec import OperatorSpec, parse_operator_spec
from arena_runtime.runner import (
    RUNNER_CONTRACT_VERSION,
    PreflightResult,
    Runner,
    RunnerRequest,
    RunnerResult,
)
from arena_runtime.vendors.aggregates import AggregatesVendor
from arena_runtime.wait import wait_until

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
    spec, operator = _load_spec(args.spec)
    archive_root = _existing_dir(spec, "archive", create=True)
    registrations = operator.registrations
    if not registrations:
        raise CliError("registrations must list every product")
    duties = operator.duties
    if not duties:
        raise CliError("duties must list every replica")
    requests = tuple(_parse_request(item) for item in _require_list(spec, "requests"))
    for request in requests:
        _require_existing_dir(request.workspace, name="workspace")
    archive = AuditArchive(archive_root)
    runners = _construct_runners(spec, operator, requests, archive)
    result = preflight_round(
        registrations=registrations,
        duties=duties,
        requests=requests,
        runners=runners,
        common_data_status=str(spec["common_data_status"]),
        archive=archive,
        decided_at=_aware(spec["decided_at"]),
    )
    status = "ready" if result.ready else "paused"
    print(status)
    return EXIT_OK if result.ready else EXIT_PAUSED


def cmd_run_round(args: argparse.Namespace) -> int:
    spec, operator = _load_spec(args.spec)
    should_wait = spec.get("wait", True)
    if not isinstance(should_wait, bool):
        raise CliError("wait must be a boolean")
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
    runners = _construct_runners(spec, operator, requests, archive)
    if should_wait:
        wait_until(_scheduled_round(operator).start)
    barrier = run_decision_barrier(
        preflight=_parse_preflight(spec["preflight"]),
        requests=requests,
        runners=runners,
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
    spec, operator = _load_spec(args.spec)
    books_root = _existing_dir(spec, "books_root", create=False)
    result = mark_official_close(
        books_root=books_root,
        vendor=_construct_vendor(operator),
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


def _load_spec(path: Path) -> tuple[dict[str, Any], OperatorSpec]:
    resolved = Path(path)
    if not resolved.is_file():
        raise CliError(f"spec not found: {resolved}")
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CliError(f"spec is not JSON: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise CliError("spec must be a JSON object")
    try:
        operator = parse_operator_spec(payload)
    except SchemaError as exc:
        raise CliError(str(exc)) from exc
    return payload, operator


def _scheduled_round(operator: OperatorSpec) -> ScheduledRound:
    if operator.calendar is None:
        raise CliError("calendar: required when wait is enabled")
    if operator.round_id is None:
        raise CliError("round_id: required when wait is enabled")
    if not operator.calendar.is_file():
        raise CliError(f"calendar not found: {operator.calendar}")
    try:
        calendar = parse_calendar(operator.calendar.read_text(encoding="utf-8"))
    except SchemaError as exc:
        raise CliError(str(exc)) from exc
    scheduled = next(
        (
            item
            for item in rounds_for_day(
                calendar,
                date.fromisoformat(operator.round_id[:10]),
            )
            if item.round_id == operator.round_id
        ),
        None,
    )
    if scheduled is None:
        raise CliError("round_id: not scheduled by calendar")
    return scheduled


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


class _ReplicaRunner:
    """Route one product's requests to its workspace-bound adapters."""

    def __init__(self, runners: Mapping[str, Runner]) -> None:
        self._runners = dict(runners)

    def preflight(self, request: RunnerRequest) -> PreflightResult:
        return self._for(request).preflight(request)

    def run(self, request: RunnerRequest) -> RunnerResult:
        return self._for(request).run(request)

    def _for(self, request: RunnerRequest) -> Runner:
        try:
            return self._runners[request.replica_id]
        except KeyError as exc:
            raise CliError(
                f"requests.{request.replica_id}: no constructed adapter"
            ) from exc


def _construct_runners(
    spec: Mapping[str, Any],
    operator: OperatorSpec,
    requests: Sequence[RunnerRequest],
    archive: AuditArchive,
) -> dict[str, Runner]:
    selected = dict(operator.adapters)
    grouped: dict[str, list[RunnerRequest]] = {}
    for request in requests:
        grouped.setdefault(request.product_id, []).append(request)

    runners: dict[str, Runner] = {}
    fake_products = {
        product_id
        for product_id in grouped
        if selected.get(product_id, "fake") == "fake"
    }
    if fake_products:
        try:
            fake = FakeRunner(_parse_scripts(spec), archive=archive)
        except FieldError as exc:
            raise CliError(str(exc)) from exc
        runners.update({product_id: fake for product_id in fake_products})

    registrations = {item.product_id: item for item in operator.registrations}
    codex_store: CodexSessionStore | None = None
    grok_store: GrokBuildSessionStore | None = None
    for product_id, product_requests in grouped.items():
        adapter_id = selected.get(product_id, "fake")
        if adapter_id == "fake":
            continue
        registration = registrations.get(product_id)
        if registration is None:
            raise CliError(f"registrations.{product_id}: missing")
        if operator.season_root is None:
            raise CliError("season_root: required for subscription adapters")
        per_replica: dict[str, Runner] = {}
        try:
            if adapter_id == "codex" and codex_store is None:
                codex_store = CodexSessionStore(
                    archive.root.parent / "runtime-state" / "codex-sessions"
                )
            if adapter_id == "grok_build" and grok_store is None:
                grok_store = GrokBuildSessionStore(
                    archive.root.parent / "runtime-state" / "grok-sessions"
                )
            for request in product_requests:
                if request.replica_id in per_replica:
                    raise CliError(f"requests.{request.replica_id}: duplicate")
                launch = prepare_replica_launch(
                    operator.season_root,
                    request.replica_id,
                    host_environment=os.environ,
                )
                if adapter_id == "codex":
                    per_replica[request.replica_id] = CodexAdapter(
                        registration,
                        launch,
                        archive=archive,
                        session_store=codex_store,
                    )
                elif adapter_id == "grok_build":
                    per_replica[request.replica_id] = GrokBuildAdapter(
                        registration,
                        launch,
                        archive=archive,
                        session_store=grok_store,
                    )
                else:  # E7 rejects this before construction.
                    raise CliError(f"adapters.{product_id}: unknown adapter id")
        except FieldError as exc:
            raise CliError(str(exc)) from exc
        runners[product_id] = (
            next(iter(per_replica.values()))
            if len(per_replica) == 1
            else _ReplicaRunner(per_replica)
        )
    return runners


def _construct_vendor(operator: OperatorSpec) -> Vendor:
    options = dict(operator.vendor.options)
    if operator.vendor.kind == "fixture":
        root = options.get("root")
        if not isinstance(root, Path):
            raise CliError("vendor.root: required for fixture vendor")
        return FixtureVendor(_require_existing_dir(root, name="vendor.root"))

    base_url = options.get("base_url")
    if not isinstance(base_url, str) or not base_url.strip():
        raise CliError("vendor.base_url: required for aggregates vendor")
    timeout = options.get("timeout", 10)
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or timeout <= 0
    ):
        raise CliError("vendor.timeout: must be a positive number")
    if "api_key" in options:
        raise CliError("vendor.api_key: use api_key_path or ARENA_VENDOR_API_KEY")
    try:
        return AggregatesVendor(
            base_url=base_url,
            symbols=_universe_symbols(operator.universe),
            timeout=timeout,
            api_key=_vendor_api_key(operator, options.get("api_key_path")),
        )
    except FieldError as exc:
        raise CliError(str(exc)) from exc


def _universe_symbols(value: tuple[str, ...] | Path | None) -> tuple[str, ...]:
    raw: object = value
    if isinstance(value, Path):
        if not value.is_file():
            raise CliError(f"universe not found: {value}")
        try:
            raw = json.loads(value.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise CliError(f"universe is not JSON: {exc.msg}") from exc
    if not isinstance(raw, (list, tuple)) or not raw:
        raise CliError("universe must list at least one symbol")
    symbols: list[str] = []
    for index, item in enumerate(raw):
        if not isinstance(item, str) or not item or item.strip() != item:
            raise CliError(f"universe.{index}: expected a symbol")
        if item in symbols:
            raise CliError(f"universe.{index}: duplicate symbol")
        symbols.append(item)
    return tuple(symbols)


def _vendor_api_key(operator: OperatorSpec, value: object) -> str | None:
    if value is None:
        return os.environ.get("ARENA_VENDOR_API_KEY")
    if not isinstance(value, Path):
        raise CliError("vendor.api_key_path: expected an absolute path")
    if not value.is_file():
        raise CliError(f"vendor.api_key_path not found: {value}")
    resolved = value.resolve()
    workspaces = tuple(
        path.resolve(strict=False) for _replica, path in operator.workspaces
    )
    if operator.season_root is not None:
        workspaces += ((operator.season_root / "replicas").resolve(strict=False),)
    if any(resolved == root or resolved.is_relative_to(root) for root in workspaces):
        raise CliError("vendor.api_key_path: must be outside replica workspaces")
    key = value.read_text(encoding="utf-8").strip()
    if not key:
        raise CliError("vendor.api_key_path: file is empty")
    return key


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
