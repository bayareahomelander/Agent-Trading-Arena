"""Fake Grok Build executable surface for R13 preflight tests."""

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

    if arguments == ["version", "--json"]:
        print(json.dumps(scenario["version"]))
        return int(scenario.get("version_exit", 0))
    if arguments == ["models"]:
        print(scenario["models_output"], end="")
        if not scenario["models_output"].endswith("\n"):
            print()
        return int(scenario.get("models_exit", 0))
    if arguments == ["--help"]:
        print("\n".join(scenario["help_items"]))
        return int(scenario.get("help_exit", 0))
    if arguments == ["agent", "--help"]:
        print("\n".join(scenario["agent_help_items"]))
        return int(scenario.get("agent_help_exit", 0))
    if arguments == ["inspect", "--json"]:
        if scenario.get("inspect_invalid", False):
            print("not json")
        else:
            print(json.dumps(scenario["inspect"]))
        return int(scenario.get("inspect_exit", 0))
    print(f"unexpected arguments: {arguments!r}", file=sys.stderr)
    return 99


if __name__ == "__main__":
    raise SystemExit(main())
