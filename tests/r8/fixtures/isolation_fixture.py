"""Child fixture for R8 cwd, environment, and write-scope tests."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def _try_write(path: Path, text: str) -> bool:
    try:
        path.write_text(text, encoding="utf-8")
    except OSError:
        return False
    return True


def main() -> int:
    mode = sys.argv[1]
    workspace = Path.cwd()
    if mode == "report":
        print(
            json.dumps(
                {
                    "cwd": str(workspace),
                    "replica_id": os.environ.get("ARENA_REPLICA_ID"),
                    "workspace": os.environ.get("ARENA_WORKSPACE"),
                    "home": os.environ.get("HOME"),
                    "unrelated": os.environ.get("UNRELATED_SETTING"),
                    "api_key": os.environ.get("PROVIDER_API_KEY"),
                }
            )
        )
        return 0
    if mode == "write-scope":
        (workspace / "agent" / "notes" / "child.txt").write_text(
            "agent write\n",
            encoding="utf-8",
        )
        (workspace / "outbox" / "decision.json").write_text(
            "decision bytes\n",
            encoding="utf-8",
        )
        print(
            json.dumps(
                {
                    "rules_write": _try_write(
                        workspace / "RULES.md",
                        "changed\n",
                    ),
                    "state_write": _try_write(
                        workspace / "state" / "portfolio.json",
                        "changed\n",
                    ),
                    "state_create": _try_write(
                        workspace / "state" / "new.json",
                        "new\n",
                    ),
                    "root_create": _try_write(
                        workspace / "unexpected.txt",
                        "new\n",
                    ),
                }
            )
        )
        return 0
    raise ValueError(f"unknown mode {mode!r}")


if __name__ == "__main__":
    raise SystemExit(main())
