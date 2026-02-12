"""Entry point: single-shot or live-refreshing quota display.

  Single-shot (for Claude Code statusline hook):
    python -m statusline

  Live mode (standalone, refreshes every 10s):
    python -m statusline --live
"""

from __future__ import annotations

import signal
import sys
import time

from .quota import get_quota_path, read_quota
from .render import HIDE_CURSOR, SHOW_CURSOR, render_quota


def _run_once() -> None:
    quota = read_quota()
    render_quota(quota)


def _run_live() -> None:
    path = get_quota_path()
    last_mtime: float = 0
    quota = read_quota()
    prev_lines = 0

    sys.stdout.write(HIDE_CURSOR)
    sys.stdout.flush()

    def _cleanup(*_: object) -> None:
        sys.stdout.write(SHOW_CURSOR)
        sys.stdout.flush()
        sys.exit(0)

    signal.signal(signal.SIGINT, _cleanup)
    signal.signal(signal.SIGTERM, _cleanup)

    try:
        while True:
            try:
                mtime = path.stat().st_mtime
            except OSError:
                mtime = 0
            if mtime != last_mtime:
                quota = read_quota()
                last_mtime = mtime

            prev_lines = render_quota(quota, rewind=prev_lines)
            time.sleep(10)
    finally:
        sys.stdout.write(SHOW_CURSOR)
        sys.stdout.flush()


def main() -> None:
    if "--live" in sys.argv:
        _run_live()
    else:
        _run_once()


if __name__ == "__main__":
    main()
