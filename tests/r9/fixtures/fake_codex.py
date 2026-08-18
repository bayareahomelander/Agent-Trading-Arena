"""Fake Codex executable surface for R9 preflight tests."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    scenario_path = Path(sys.argv[1])
    arguments = sys.argv[2:]
    scenario = json.loads(scenario_path.read_text(encoding="utf-8"))
    log_path = Path(scenario["log_path"])
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(arguments) + "\n")

    if arguments == ["--version"]:
        print(f"codex-cli {scenario['version']}")
        return int(scenario.get("version_exit", 0))
    if arguments == ["login", "status"]:
        print(scenario["login_output"])
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
    print(f"unexpected arguments: {arguments!r}", file=sys.stderr)
    return 99


if __name__ == "__main__":
    raise SystemExit(main())
