"""Small subprocess fixture for R7 supervision tests."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path


def main() -> int:
    mode = sys.argv[1]
    if mode == "success":
        sys.stdout.buffer.write(b"success stdout\n")
        sys.stderr.buffer.write(b"success stderr\n")
        return 0
    if mode == "fail":
        sys.stdout.buffer.write(b"failure stdout\n")
        sys.stderr.buffer.write(b"failure stderr\n")
        return 7
    if mode == "echo":
        print(json.dumps(sys.argv[2:]))
        return 0
    if mode == "spam":
        size = int(sys.argv[2])
        sys.stdout.buffer.write(b"O" * size)
        sys.stderr.buffer.write(b"E" * size)
        return 0
    if mode == "sleep":
        time.sleep(float(sys.argv[2]))
        return 0
    if mode == "spawn-child":
        pid_file = Path(sys.argv[2])
        heartbeat_file = Path(sys.argv[3])
        child_script = Path(__file__).with_name("child_heartbeat.py")
        child = subprocess.Popen(
            [sys.executable, str(child_script), str(heartbeat_file)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
        )
        pid_file.write_text(str(child.pid), encoding="ascii")
        time.sleep(30)
        return 0
    raise ValueError(f"unknown mode {mode!r}")


if __name__ == "__main__":
    raise SystemExit(main())
