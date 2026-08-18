"""R10: fresh Codex execution passes the shared success-path gate."""

from pathlib import Path

from arena_runtime.runner import Runner, RunnerRequest
from tests.r6.conformance import SuccessfulRunnerConformanceSuite

from .conftest import make_case


class TestCodexFreshConformance(SuccessfulRunnerConformanceSuite):
    __test__ = True

    def build_case(
        self,
        root: Path,
        *,
        outcome: str,
        decision_bytes: bytes | None,
    ) -> tuple[Runner, RunnerRequest]:
        assert outcome == "completed"
        adapter, request, _, _, _ = make_case(
            root,
            decision_bytes=decision_bytes,
        )
        return adapter, request
