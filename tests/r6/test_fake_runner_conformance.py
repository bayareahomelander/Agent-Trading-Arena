"""R6: FakeRunner passes the shared adapter conformance suite."""

from pathlib import Path

from arena_runtime.adapters.fake import FakeRunner
from arena_runtime.audit import AuditArchive
from arena_runtime.runner import Runner, RunnerRequest

from .conformance import RunnerConformanceSuite
from .conftest import make_request, make_script


class TestFakeRunnerConformance(RunnerConformanceSuite):
    __test__ = True

    def build_case(
        self,
        root: Path,
        *,
        outcome: str,
        decision_bytes: bytes | None,
    ) -> tuple[Runner, RunnerRequest]:
        request = make_request(root / "workspace")
        script = make_script(
            outcome=outcome,
            decision_bytes=decision_bytes,
            session_reference=f"session-{outcome}",
        )
        runner = FakeRunner(
            (script,),
            archive=AuditArchive(root / "archive"),
        )
        return runner, request
