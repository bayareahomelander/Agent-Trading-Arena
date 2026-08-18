"""Shared two-product preflight-barrier fixtures."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from arena_runtime.adapters.fake import FakeRunner, FakeRunnerScript
from arena_runtime.audit import AuditArchive
from arena_runtime.orchestrator import (
    COMMON_DATA_AVAILABLE,
    REPLICA_STATUS_ACTIVE,
    REPLICA_STATUS_DQ_REFUSAL,
    ReplicaDuty,
    preflight_round,
)
from arena_runtime.registration import (
    RuntimeCapabilities,
    RuntimeRegistration,
)
from tests.r6.conftest import make_request, make_script

ET = ZoneInfo("America/New_York")
ROUND_ID = "2026-08-17-morning"
DECIDED_AT = datetime(2026, 8, 17, 9, 59, 30, tzinfo=ET)
PRODUCT_A = "product-a"
PRODUCT_B = "product-b"
REPLICA_A1 = "product-a-1"
REPLICA_B1 = "product-b-1"
REPLICA_B2 = "product-b-2"


def make_registration(product_id: str, replica_ids: tuple[str, ...]) -> RuntimeRegistration:
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


def two_product_registrations() -> tuple[RuntimeRegistration, RuntimeRegistration]:
    return (
        make_registration(PRODUCT_A, (REPLICA_A1,)),
        make_registration(PRODUCT_B, (REPLICA_B1, REPLICA_B2)),
    )


def default_duties() -> tuple[ReplicaDuty, ...]:
    return (
        ReplicaDuty(PRODUCT_A, REPLICA_A1, REPLICA_STATUS_ACTIVE),
        ReplicaDuty(PRODUCT_B, REPLICA_B1, REPLICA_STATUS_ACTIVE),
        ReplicaDuty(PRODUCT_B, REPLICA_B2, REPLICA_STATUS_DQ_REFUSAL),
    )


def script_for(
    product_id: str,
    replica_id: str,
    *,
    ready: bool = True,
    failure_reason: str | None = None,
) -> FakeRunnerScript:
    return make_script(
        product_id=product_id,
        replica_id=replica_id,
        round_id=ROUND_ID,
        preflight_ready=ready,
        preflight_failure_reason=failure_reason,
        outcome="completed",
        session_reference=f"session-{replica_id}",
    )


def run_barrier(
    root: Path,
    *,
    scripts: tuple[FakeRunnerScript, ...],
    duties: tuple[ReplicaDuty, ...] | None = None,
    common_data_status: str = COMMON_DATA_AVAILABLE,
):
    archive = AuditArchive(root / "archive")
    runner = FakeRunner(scripts, archive=archive)
    registrations = two_product_registrations()
    resolved_duties = default_duties() if duties is None else duties
    due = [
        duty
        for duty in resolved_duties
        if duty.status == REPLICA_STATUS_ACTIVE
    ]
    requests = [
        make_request(
            root / duty.replica_id,
            product_id=duty.product_id,
            replica_id=duty.replica_id,
            round_id=ROUND_ID,
        )
        for duty in due
    ]
    result = preflight_round(
        registrations=registrations,
        duties=resolved_duties,
        requests=requests,
        runners={PRODUCT_A: runner, PRODUCT_B: runner},
        common_data_status=common_data_status,
        archive=archive,
        decided_at=DECIDED_AT,
    )
    return result, archive, runner
