"""Reusable provider-neutral runner conformance suite.

Adapters with only successful execution implemented subclass
``SuccessfulRunnerConformanceSuite``. Fully normalized test doubles subclass
``RunnerConformanceSuite`` for all outcomes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from arena_runtime.runner import (
    RUNNER_OUTCOMES,
    Runner,
    RunnerRequest,
    require_matching_identity,
)


class SuccessfulRunnerConformanceSuite:
    """Shared success-path gate for any adapter test double."""

    __test__ = False

    def build_case(
        self,
        root: Path,
        *,
        outcome: str,
        decision_bytes: bytes | None,
    ) -> tuple[Runner, RunnerRequest]:
        raise NotImplementedError

    def test_runner_implements_shared_protocol(self, tmp_path: Path) -> None:
        runner, request = self.build_case(
            tmp_path,
            outcome="completed",
            decision_bytes=b"exact decision bytes",
        )

        assert isinstance(runner, Runner)
        assert require_matching_identity(request, runner.preflight(request)).ready
        assert require_matching_identity(request, runner.run(request)).outcome == (
            "completed"
        )

    def test_scripted_decision_bytes_are_not_rewritten(self, tmp_path: Path) -> None:
        exact = b" \x00not-json\r\n"
        runner, request = self.build_case(
            tmp_path,
            outcome="completed",
            decision_bytes=exact,
        )

        assert runner.preflight(request).ready
        result = runner.run(request)

        assert result.decision_present is True
        assert (request.workspace / "outbox" / "decision.json").read_bytes() == exact


class RunnerConformanceSuite(SuccessfulRunnerConformanceSuite):
    """Full normalized-outcome gate for deterministic adapter test doubles."""

    __test__ = False

    @pytest.mark.parametrize("outcome", RUNNER_OUTCOMES)
    def test_every_normalized_outcome_is_preserved(
        self,
        tmp_path: Path,
        outcome: str,
    ) -> None:
        decision = b"exact decision bytes" if outcome == "completed" else None
        runner, request = self.build_case(
            tmp_path / outcome,
            outcome=outcome,
            decision_bytes=decision,
        )

        result = require_matching_identity(request, runner.run(request))

        assert result.outcome == outcome
        assert result.decision_present is (decision is not None)
