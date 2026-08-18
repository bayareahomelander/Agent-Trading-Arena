"""Child process used to prove process-tree termination."""

from __future__ import annotations

import sys
import time
from pathlib import Path


def main() -> None:
    heartbeat = Path(sys.argv[1])
    count = 0
    while True:
        heartbeat.write_text(str(count), encoding="ascii")
        count += 1
        time.sleep(0.05)


if __name__ == "__main__":
    main()
