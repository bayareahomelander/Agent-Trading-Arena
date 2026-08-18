"""Reusable provider-neutral runner conformance suite.

Future adapter test doubles subclass ``RunnerConformanceSuite`` and implement
``build_case`` without changing these shared assertions.
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


class RunnerConformanceSuite:
    """Shared behavioral gate for any deterministic adapter test double."""

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

    def test_scripted_decision_bytes_are_not_rewritten(self, tmp_path: Path) -> None:
        exact = b" \x00not-json\r\n"
        runner, request = self.build_case(
            tmp_path,
            outcome="completed",
            decision_bytes=exact,
        )

        result = runner.run(request)

        assert result.decision_present is True
        assert (request.workspace / "outbox" / "decision.json").read_bytes() == exact
