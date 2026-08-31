#!/usr/bin/env python3
"""Execute one command as the stable leader of a fresh process session.

Unlike the external ``setsid`` utility, this helper never leaves a short-lived
wrapper PID behind.  The launcher can therefore signal the saved PID's process
group and reliably stop every Gazebo/ROS child on exit.
"""

from __future__ import annotations

import os
import signal
import sys


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: session_exec.py COMMAND [ARG ...]", file=sys.stderr)
        return 2
    # Non-interactive shells start asynchronous jobs with SIGINT/SIGQUIT
    # ignored.  An exec preserves ignored dispositions, which would make ROS
    # launch groups survive the launcher's graceful shutdown signal.  Restore
    # normal process semantics before becoming the session leader.
    for signum in (signal.SIGHUP, signal.SIGINT, signal.SIGQUIT, signal.SIGTERM):
        signal.signal(signum, signal.SIG_DFL)
    os.setsid()
    os.execvp(sys.argv[1], sys.argv[1:])
    return 127  # pragma: no cover - execvp either replaces us or raises.


if __name__ == "__main__":
    raise SystemExit(main())
