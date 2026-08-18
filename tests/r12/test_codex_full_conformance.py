"""R12: the complete Codex adapter passes the shared outcome conformance gate."""

import json
from pathlib import Path

from arena_runtime.runner import Runner, RunnerRequest
from tests.r6.conformance import RunnerConformanceSuite
from tests.r10.conftest import make_case


def _scenario_for(outcome: str) -> tuple[list[dict[str, object]], int, float]:
    thread = {"type": "thread.started", "thread_id": f"thread-{outcome}"}
    if outcome in {"completed", "missing_decision"}:
        return [thread, {"type": "turn.completed", "usage": {}}], 0, 0
    if outcome == "timeout":
        return [], 1, 30
    codes = {
        "refusal": "cyberPolicy",
        "quota_exhausted": "usageLimitExceeded",
        "provider_unavailable": "serverOverloaded",
        "runner_error": "unknownNewFailure",
    }
    return [
        thread,
        {
            "type": "turn.failed",
            "error": {"error_type": codes[outcome]},
        },
    ], 7, 0


class TestCodexFullConformance(RunnerConformanceSuite):
    __test__ = True

    def build_case(
        self,
        root: Path,
        *,
        outcome: str,
        decision_bytes: bytes | None,
    ) -> tuple[Runner, RunnerRequest]:
        events, exit_status, sleep_seconds = _scenario_for(outcome)
        adapter, request, _, _, _ = make_case(
            root,
            decision_bytes=decision_bytes,
            run_exit=exit_status,
            run_sleep_seconds=sleep_seconds,
            deadline_seconds=5 if outcome == "timeout" else 20,
        )
        scenario_path = root / "scenario.json"
        scenario = json.loads(scenario_path.read_text(encoding="utf-8"))
        scenario["stdout_events"] = events
        scenario_path.write_text(
            json.dumps(scenario, indent=2) + "\n",
            encoding="utf-8",
        )
        return adapter, request
