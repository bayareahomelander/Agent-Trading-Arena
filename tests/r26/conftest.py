"""Deterministic Phase D fixture: two products, two replicas each."""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from arena_kernel.calendar import parse_calendar, rounds_for_day
from arena_kernel.marketdata import (
    FixtureVendor,
    bars_at_reference,
    build_tape,
    publish_round,
)
from arena_kernel.schema.fills import FillsFile
from arena_kernel.schema.market import parse_snapshot
from arena_kernel.schema.portfolio import Portfolio, parse_portfolio
from arena_runtime.adapters.fake import FakeRunner
from arena_runtime.audit import AuditArchive
from arena_runtime.disposition import COMMON_DATA_AVAILABLE, decide_round_disposition
from arena_runtime.orchestrator import (
    REPLICA_STATUS_ACTIVE,
    ReplicaDuty,
    collect_sealed_decisions,
    evaluate_candidates,
    mark_official_close,
    preflight_round,
    publish_candidates,
    published_snapshot_checksum,
    reconstruct_published_round,
    run_archived_baselines,
    run_decision_barrier,
)
from arena_runtime.registration import RuntimeCapabilities, RuntimeRegistration
from arena_runtime.runner import RUNNER_CONTRACT_VERSION, RunnerRequest
from tests.r6.conftest import make_script

ET = ZoneInfo("America/New_York")
SESSION = date(2026, 11, 2)
ROUND_ID = "2026-11-02-morning"
CALENDAR = Path(__file__).resolve().parents[2] / "fixtures" / "golden" / "calendar" / "calendar.json"
VENDOR = Path(__file__).resolve().parents[2] / "fixtures" / "golden" / "calendar" / "vendor"
PRODUCTS = (
    ("product-a", ("product-a-1", "product-a-2")),
    ("product-b", ("product-b-1", "product-b-2")),
)
HOLD = json.dumps(
    {
        "round_id": ROUND_ID,
        "action": "hold",
        "orders": [],
        "thesis": "fixture hold",
        "confidence": 0.5,
        "risk_note": "fixture",
        "invalidation": "fixture",
        "intended_horizon": "fixture",
    },
    separators=(",", ":"),
).encode("utf-8")


def hold_decision() -> bytes:
    return HOLD


def cash_book(product_id: str, replica_id: str) -> Portfolio:
    return Portfolio(
        schema_version="1",
        replica_id=replica_id,
        product_id=product_id,
        cash=Decimal("1000.00"),
        positions=(),
        reported_equity=None,
    )


def registration(product_id: str, replica_ids: tuple[str, ...]) -> RuntimeRegistration:
    return RuntimeRegistration(
        schema_version="1",
        product_id=product_id,
        provider_id="test-provider",
        adapter_id="fake",
        subscription_tier="individual-usd-20",
        authentication_method="subscription",
        exact_model=f"registered-{product_id}-model",
        reasoning_mode="high",
        automatic_routing=False,
        expected_cli_version="1.0.0",
        replica_ids=replica_ids,
        capabilities=RuntimeCapabilities(True, True, True, True, True),
        provider_documentation_url="https://docs.example.test/product-cli",
        provider_documentation_retrieved_on=date(2026, 8, 17),
    )


def run_fixture_season(root: Path) -> dict[str, object]:
    """Drive the R17–R24 path on a clean temporary season root."""

    season = root / "season"
    archive_root = root / "archive"
    books_root = (root / "books").resolve()
    staging = (root / "staging").resolve()
    tape_dir = root / "tape"
    calendar = parse_calendar(CALENDAR.read_text(encoding="utf-8"))
    vendor = FixtureVendor(VENDOR)
    scheduled = rounds_for_day(calendar, SESSION)[0]
    assert scheduled.round_id == ROUND_ID
    bars = bars_at_reference(vendor, ("AAA", "SPY"), scheduled.reference_minute)
    books = [
        cash_book(product_id, replica_id)
        for product_id, replica_ids in PRODUCTS
        for replica_id in replica_ids
    ]
    publish_round(
        season,
        scheduled=scheduled,
        bars=bars,
        portfolios=books,
        raw_vendor_bytes=b'{"bars":[]}',
        fills={book.replica_id: FillsFile(schema_version="1", fills=()) for book in books},
        rules_md="# Frozen rules\n",
        prompt_md="Treat terminal simulated wealth as the thing you are accountable for.\n",
    )
    archive = AuditArchive(archive_root)
    scripts = []
    requests = []
    duties = []
    registrations = []
    for product_id, replica_ids in PRODUCTS:
        registrations.append(registration(product_id, replica_ids))
        for replica_id in replica_ids:
            workspace = (season / "replicas" / replica_id).resolve()
            duties.append(ReplicaDuty(product_id, replica_id, REPLICA_STATUS_ACTIVE))
            requests.append(
                RunnerRequest(
                    contract_version=RUNNER_CONTRACT_VERSION,
                    product_id=product_id,
                    replica_id=replica_id,
                    round_id=ROUND_ID,
                    workspace=workspace,
                    model_reference="registration:model",
                    configuration_reference="registration:configuration",
                    launch_instruction=b"Frozen launch instruction",
                    deadline=scheduled.deadline,
                )
            )
            scripts.append(
                make_script(
                    product_id=product_id,
                    replica_id=replica_id,
                    round_id=ROUND_ID,
                    outcome="completed",
                    decision_bytes=hold_decision(),
                    session_reference=f"session-{replica_id}",
                )
            )
    runner = FakeRunner(tuple(scripts), archive=archive)
    runners = {product_id: runner for product_id, _ids in PRODUCTS}
    preflight = preflight_round(
        registrations=registrations,
        duties=duties,
        requests=requests,
        runners=runners,
        common_data_status=COMMON_DATA_AVAILABLE,
        archive=archive,
        decided_at=datetime(2026, 11, 2, 9, 59, 30, tzinfo=ET),
    )
    checksum = published_snapshot_checksum(requests[0].workspace)
    barrier = run_decision_barrier(
        preflight=preflight,
        requests=requests,
        runners=runners,
        snapshot_checksum=checksum,
    )
    disposition = decide_round_disposition(barrier.results, COMMON_DATA_AVAILABLE)
    collection = collect_sealed_decisions(
        barrier=barrier,
        disposition=disposition,
        workspaces={request.replica_id: request.workspace for request in requests},
        staging_root=staging,
    )
    snapshot = parse_snapshot(
        (requests[0].workspace / "state" / "market" / "snapshot.json").read_text(
            encoding="utf-8"
        )
    )
    evaluation = evaluate_candidates(
        collection=collection,
        snapshot=snapshot,
        books={
            request.replica_id: parse_portfolio(
                (request.workspace / "state" / "portfolio.json").read_text(
                    encoding="utf-8"
                )
            )
            for request in requests
        },
    )
    publication = publish_candidates(
        candidates=evaluation,
        books_root=books_root,
        archive=archive,
        published_at=datetime(2026, 11, 2, 10, 16, tzinfo=ET),
    )
    close = mark_official_close(
        books_root=books_root,
        vendor=vendor,
        session_date=SESSION,
        replica_ids=tuple(request.replica_id for request in requests),
        marked_at=datetime(2026, 11, 2, 16, 0, tzinfo=ET),
    )
    starter = cash_book("baseline", "starter")
    built = build_tape(
        tape_dir,
        calendar,
        vendor,
        ("AAA", "SPY"),
        (SESSION,),
        starter,
        rules_md="# Frozen rules\n",
        prompt_md="Treat terminal simulated wealth as the thing you are accountable for.\n",
    )
    (built / "baselines.json").write_text(
        json.dumps({"schema_version": "1", "random_seed": 20260817}, indent=2) + "\n",
        encoding="utf-8",
    )
    baselines = run_archived_baselines(tape_dir=built, books_root=books_root)
    events = archive.events_path.read_text(encoding="utf-8")
    reconstructed = reconstruct_published_round(books_root, ROUND_ID)
    return {
        "preflight": preflight,
        "barrier": barrier,
        "disposition": disposition,
        "collection": collection,
        "evaluation": evaluation,
        "publication": publication,
        "close": close,
        "baselines": baselines,
        "events": events,
        "books": reconstructed,
        "nlvs": {mark.replica_id: str(mark.nlv) for mark in close.marks},
        "books_root": books_root,
        "tape": built,
    }
