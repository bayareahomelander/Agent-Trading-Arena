"""Pure Protocol 0.2 mapping from sealed runner outcomes to round treatment.

R19 performs no I/O. It does not read decisions, change books, or write pause
state. Adapters and round coordination must not re-encode this policy.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Sequence

from arena_runtime.runner import RUNNER_OUTCOMES, RunnerResult

COMMON_DATA_AVAILABLE: Final[str] = "available"
COMMON_DATA_UNAVAILABLE: Final[str] = "unavailable"
COMMON_DATA_UNAVAILABLE_REASON: Final[str] = "common_data_unavailable"
COMMON_DATA_STATUSES: Final[tuple[str, ...]] = (
    COMMON_DATA_AVAILABLE,
    COMMON_DATA_UNAVAILABLE,
)

ROUND_TREATMENT_EVALUATE: Final[str] = "evaluate"
ROUND_TREATMENT_VOID_AND_PAUSE: Final[str] = "void_and_pause"
ROUND_TREATMENT_EVALUATOR_FAILURE: Final[str] = "evaluator_failure"
ROUND_TREATMENTS: Final[tuple[str, ...]] = (
    ROUND_TREATMENT_EVALUATE,
    ROUND_TREATMENT_VOID_AND_PAUSE,
    ROUND_TREATMENT_EVALUATOR_FAILURE,
)

REPLICA_TREATMENT_EVALUATE: Final[str] = "evaluate"
REPLICA_TREATMENT_HOLD_NO_ACTION: Final[str] = "hold_no_action"
REPLICA_TREATMENT_DISQUALIFY_REFUSAL: Final[str] = "disqualify_refusal"
REPLICA_TREATMENT_VOIDED: Final[str] = "voided"
REPLICA_TREATMENTS: Final[tuple[str, ...]] = (
    REPLICA_TREATMENT_EVALUATE,
    REPLICA_TREATMENT_HOLD_NO_ACTION,
    REPLICA_TREATMENT_DISQUALIFY_REFUSAL,
    REPLICA_TREATMENT_VOIDED,
)

SHARED_VOID_OUTCOMES: Final[frozenset[str]] = frozenset(
    {
        "quota_exhausted",
        "provider_unavailable",
    }
)
HOLD_OUTCOMES: Final[frozenset[str]] = frozenset(
    {
        "timeout",
        "missing_decision",
    }
)
_SHARED_VOID_ORDER: Final[tuple[str, ...]] = (
    "quota_exhausted",
    "provider_unavailable",
)


class DispositionError(ValueError):
    """Invalid disposition input with a stable field path."""

    def __init__(self, path: str, message: str) -> None:
        self.path = path
        self.message = message
        super().__init__(f"{path}: {message}")


@dataclass(frozen=True)
class ReplicaDisposition:
    """Protocol treatment for one sealed runner result."""

    product_id: str
    replica_id: str
    round_id: str
    outcome: str
    treatment: str

    def __post_init__(self) -> None:
        if self.outcome not in RUNNER_OUTCOMES:
            raise DispositionError(
                "outcome",
                f"must be one of {', '.join(RUNNER_OUTCOMES)}",
            )
        if self.treatment not in REPLICA_TREATMENTS:
            raise DispositionError(
                "treatment",
                f"must be one of {', '.join(REPLICA_TREATMENTS)}",
            )


@dataclass(frozen=True)
class RoundDisposition:
    """Round-level treatment plus one record for every sealed result."""

    treatment: str
    reason_codes: tuple[str, ...]
    replica_dispositions: tuple[ReplicaDisposition, ...]
    comparison_degraded: bool

    def __post_init__(self) -> None:
        if self.treatment not in ROUND_TREATMENTS:
            raise DispositionError(
                "treatment",
                f"must be one of {', '.join(ROUND_TREATMENTS)}",
            )
        if not isinstance(self.comparison_degraded, bool):
            raise DispositionError("comparison_degraded", "expected a boolean")
        if self.treatment == ROUND_TREATMENT_EVALUATE and not self.reason_codes:
            raise DispositionError(
                "reason_codes",
                "evaluate must record the selected replica treatments",
            )
        if self.treatment != ROUND_TREATMENT_EVALUATE and not self.reason_codes:
            raise DispositionError(
                "reason_codes",
                "required when the round is voided",
            )


def decide_round_disposition(
    results: Sequence[RunnerResult],
    common_data_status: str,
) -> RoundDisposition:
    """Map sealed outcomes and common-data status to Protocol 0.2 treatment."""

    if common_data_status not in COMMON_DATA_STATUSES:
        raise DispositionError(
            "common_data_status",
            f"must be one of {', '.join(COMMON_DATA_STATUSES)}",
        )
    sealed = _require_results(results)
    outcomes = tuple(result.outcome for result in sealed)
    if common_data_status == COMMON_DATA_UNAVAILABLE:
        return _voided(
            sealed,
            treatment=ROUND_TREATMENT_VOID_AND_PAUSE,
            reason_codes=(COMMON_DATA_UNAVAILABLE_REASON,),
        )
    shared = tuple(
        outcome for outcome in _SHARED_VOID_ORDER if outcome in outcomes
    )
    if shared:
        return _voided(
            sealed,
            treatment=ROUND_TREATMENT_VOID_AND_PAUSE,
            reason_codes=shared,
        )
    if "runner_error" in outcomes:
        return _voided(
            sealed,
            treatment=ROUND_TREATMENT_EVALUATOR_FAILURE,
            reason_codes=("runner_error",),
        )
    replica_dispositions = tuple(
        ReplicaDisposition(
            product_id=result.product_id,
            replica_id=result.replica_id,
            round_id=result.round_id,
            outcome=result.outcome,
            treatment=_replica_treatment(result.outcome),
        )
        for result in sealed
    )
    reason_codes = tuple(
        dict.fromkeys(item.treatment for item in replica_dispositions)
    )
    return RoundDisposition(
        treatment=ROUND_TREATMENT_EVALUATE,
        reason_codes=reason_codes,
        replica_dispositions=replica_dispositions,
        comparison_degraded=_comparison_degraded(replica_dispositions),
    )


def _require_results(results: Sequence[RunnerResult]) -> tuple[RunnerResult, ...]:
    if not results:
        raise DispositionError(
            "results",
            "must contain every sealed runner result",
        )
    sealed: list[RunnerResult] = []
    seen: set[tuple[str, str]] = set()
    round_id: str | None = None
    for index, result in enumerate(results):
        path = f"results.{index}"
        if not isinstance(result, RunnerResult):
            raise DispositionError(path, "expected RunnerResult")
        if round_id is None:
            round_id = result.round_id
        elif result.round_id != round_id:
            raise DispositionError(
                f"{path}.round_id",
                "must match the other results",
            )
        key = (result.product_id, result.replica_id)
        if key in seen:
            raise DispositionError(path, "duplicate replica result")
        seen.add(key)
        sealed.append(result)
    return tuple(sealed)


def _replica_treatment(outcome: str) -> str:
    if outcome == "completed":
        return REPLICA_TREATMENT_EVALUATE
    if outcome in HOLD_OUTCOMES:
        return REPLICA_TREATMENT_HOLD_NO_ACTION
    if outcome == "refusal":
        return REPLICA_TREATMENT_DISQUALIFY_REFUSAL
    raise DispositionError(
        "outcome",
        f"unexpected evaluate-path outcome {outcome!r}",
    )


def _voided(
    results: Sequence[RunnerResult],
    *,
    treatment: str,
    reason_codes: tuple[str, ...],
) -> RoundDisposition:
    return RoundDisposition(
        treatment=treatment,
        reason_codes=reason_codes,
        replica_dispositions=tuple(
            ReplicaDisposition(
                product_id=result.product_id,
                replica_id=result.replica_id,
                round_id=result.round_id,
                outcome=result.outcome,
                treatment=REPLICA_TREATMENT_VOIDED,
            )
            for result in results
        ),
        comparison_degraded=False,
    )


def _comparison_degraded(replicas: Sequence[ReplicaDisposition]) -> bool:
    return any(
        item.treatment == REPLICA_TREATMENT_DISQUALIFY_REFUSAL for item in replicas
    )
