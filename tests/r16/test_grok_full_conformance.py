"""R16: the complete Grok adapter passes the shared outcome conformance gate."""

import json
from pathlib import Path

from arena_runtime.runner import Runner, RunnerRequest
from tests.r6.conformance import RunnerConformanceSuite
from tests.r14.conftest import make_case


def _scenario_for(outcome: str) -> tuple[list[dict[str, object]], int, float]:
    if outcome in {"completed", "missing_decision"}:
        return (
            [
                {
                    "type": "end",
                    "stopReason": "end_turn",
                    "sessionId": f"session-{outcome}",
                }
            ],
            0,
            0,
        )
    if outcome == "timeout":
        return [], 1, 30
    codes = {
        "refusal": "refusal",
        "quota_exhausted": "usage_limit_reached",
        "provider_unavailable": "service_unavailable",
        "runner_error": "unknownNewFailure",
    }
    if outcome == "refusal":
        return (
            [
                {
                    "type": "end",
                    "stopReason": "refusal",
                    "sessionId": "session-refusal",
                }
            ],
            7,
            0,
        )
    return (
        [{"type": "error", "code": codes[outcome]}],
        7,
        0,
    )


class TestGrokFullConformance(RunnerConformanceSuite):
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
