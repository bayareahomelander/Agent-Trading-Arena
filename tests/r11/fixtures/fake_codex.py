"""Fake Codex executable for fresh-thread capture and exact resume tests."""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path


def main() -> int:
    scenario = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    arguments = sys.argv[2:]
    command_log = Path(scenario["command_log_path"])
    command_log.parent.mkdir(parents=True, exist_ok=True)
    with command_log.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(arguments) + "\n")

    if arguments == ["--version"]:
        print(f"codex-cli {scenario['version']}")
        return 0
    if arguments == ["login", "status"]:
        print("Logged in using ChatGPT")
        return 0
    if arguments == ["exec", "--help"]:
        print("\n".join(scenario["exec_help_items"]))
        return 0
    if arguments == ["doctor", "--json"]:
        print(json.dumps(scenario["doctor"]))
        return 0

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
    decision = scenario["decisions"].get(prompt)
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
