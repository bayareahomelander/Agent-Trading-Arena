"""Fake Grok Build preflight and fresh-session executable for R14."""

from __future__ import annotations

import base64
import json
import sys
import time
from pathlib import Path


def main() -> int:
    scenario = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    arguments = sys.argv[2:]
    log_path = Path(scenario["command_log_path"])
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8", newline="\n") as stream:
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

    sleep_seconds = float(scenario.get("run_sleep_seconds", 0))
    if sleep_seconds:
        time.sleep(sleep_seconds)
    prompt = arguments[arguments.index("--single") + 1]
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
        decision_path = Path.cwd() / "outbox" / "decision.json"
        decision_path.write_bytes(base64.b64decode(encoded_decision))
    for event in scenario.get("stdout_events", []):
        print(json.dumps(event), flush=True)
    stderr_text = scenario.get("stderr_text", "")
    if stderr_text:
        print(stderr_text, file=sys.stderr, flush=True)
    return int(scenario.get("run_exit", 0))


if __name__ == "__main__":
    raise SystemExit(main())
