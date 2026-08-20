"""Fake Codex CLI for preflight, fresh-session, and resume tests."""

from __future__ import annotations

import base64
import json
import sys
import time
from pathlib import Path


def main() -> int:
    scenario = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    arguments = sys.argv[2:]
    log_key = "command_log_path" if "command_log_path" in scenario else "log_path"
    log_path = Path(scenario[log_key])
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(arguments) + "\n")

    if arguments == ["--version"]:
        print(f"codex-cli {scenario['version']}")
        return int(scenario.get("version_exit", 0))
    if arguments == ["login", "status"]:
        print(scenario.get("login_output", "Logged in using ChatGPT"))
        return int(scenario.get("login_exit", 0))
    if arguments == ["exec", "--help"]:
        print("\n".join(scenario["exec_help_items"]))
        return int(scenario.get("exec_help_exit", 0))
    if arguments == ["doctor", "--json"]:
        if scenario.get("doctor_invalid", False):
            print("not json")
        else:
            print(json.dumps(scenario["doctor"]))
        return int(scenario.get("doctor_exit", 0))

    if "exec" not in arguments:
        print(f"unexpected arguments: {arguments!r}", file=sys.stderr)
        return 99

    sleep_seconds = float(scenario.get("run_sleep_seconds", 0))
    if sleep_seconds:
        time.sleep(sleep_seconds)

    if "run_capture_path" in scenario:
        prompt = arguments[-1]
        capture = {
            "argv": arguments,
            "cwd": str(Path.cwd()),
            "prompt_base64": base64.b64encode(prompt.encode("utf-8")).decode("ascii"),
        }
        Path(scenario["run_capture_path"]).write_text(
            json.dumps(capture, indent=2) + "\n",
            encoding="utf-8",
        )
        encoded_decision = scenario.get("decision_base64")
        if encoded_decision is not None:
            (Path.cwd() / "outbox" / "decision.json").write_bytes(
                base64.b64decode(encoded_decision)
            )
        for event in scenario.get("stdout_events", []):
            print(json.dumps(event), flush=True)
        stderr_text = scenario.get("stderr_text", "")
        if stderr_text:
            print(stderr_text, file=sys.stderr, flush=True)
        return int(scenario.get("run_exit", 0))

    prompt = arguments[-1]
    is_resume = "resume" in arguments
    session_argument = arguments[-2] if is_resume else None
    capture_log = Path(scenario["capture_log_path"])
    with capture_log.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(
            json.dumps(
                {
                    "argv": arguments,
                    "cwd": str(Path.cwd()),
                    "is_resume": is_resume,
                    "session_argument": session_argument,
                    "prompt": prompt,
                }
            )
            + "\n"
        )
    decision = scenario.get("decisions", {}).get(prompt)
    if decision is not None:
        (Path.cwd() / "outbox" / "decision.json").write_bytes(
            base64.b64decode(decision)
        )

    mode = scenario.get("thread_event_mode", "one")
    if mode == "invalid-json":
        print("not-json")
    elif mode != "missing":
        thread_id = (
            scenario.get("resume_thread_id", scenario["thread_id"])
            if is_resume
            else scenario["thread_id"]
        )
        print(json.dumps({"type": "thread.started", "thread_id": thread_id}))
        if mode == "duplicate":
            print(json.dumps({"type": "thread.started", "thread_id": thread_id}))
    print(json.dumps({"type": "turn.completed", "usage": {}}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
