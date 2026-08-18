"""Fake Grok Build executable for fresh-session capture and exact resume tests."""

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

    if arguments == ["version", "--json"]:
        print(json.dumps(scenario["version"]))
        return 0
    if arguments == ["models"]:
        print(scenario["models_output"], end="")
        if not str(scenario["models_output"]).endswith("\n"):
            print()
        return 0
    if arguments == ["--help"]:
        print("\n".join(scenario["help_items"]))
        return 0
    if arguments == ["agent", "--help"]:
        print("\n".join(scenario["agent_help_items"]))
        return 0
    if arguments == ["inspect", "--json"]:
        print(json.dumps(scenario["inspect"]))
        return 0

    if "--single" not in arguments:
        print(f"unexpected arguments: {arguments!r}", file=sys.stderr)
        return 99

    prompt = arguments[arguments.index("--single") + 1]
    is_resume = "--resume" in arguments
    session_argument = (
        arguments[arguments.index("--resume") + 1] if is_resume else None
    )
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

    mode = scenario.get("session_event_mode", "one")
    if mode == "invalid-json":
        print("not-json")
    elif mode != "missing":
        session_id = (
            scenario.get("resume_session_id", scenario["session_id"])
            if is_resume
            else scenario["session_id"]
        )
        print(json.dumps({"type": "text", "data": "wrote outbox/decision.json"}))
        print(
            json.dumps(
                {
                    "type": "end",
                    "stopReason": "end_turn",
                    "sessionId": session_id,
                }
            )
        )
        if mode == "duplicate":
            print(
                json.dumps(
                    {
                        "type": "end",
                        "stopReason": "end_turn",
                        "sessionId": session_id,
                    }
                )
            )
    else:
        print(json.dumps({"type": "text", "data": "no session"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
