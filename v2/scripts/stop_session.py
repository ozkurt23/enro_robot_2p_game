#!/usr/bin/env python3
"""Stop one dedicated process session and verify that every member exited."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import signal
import sys
import time


def _session_processes(session_id: int) -> tuple[tuple[int, int], ...]:
    """Return ``(pid, process_group)`` pairs for live members of one SID."""
    members: list[tuple[int, int]] = []
    for stat_path in Path("/proc").glob("[0-9]*/stat"):
        try:
            raw = stat_path.read_text(encoding="utf-8")
            # The executable name in /proc/PID/stat may contain spaces and
            # parentheses.  Fields after the final ')' begin with state,
            # parent PID and process-group ID.
            fields = raw[raw.rfind(")") + 2 :].split()
            state = fields[0]
            process_group = int(fields[2])
            process_session = int(fields[3])
            pid = int(stat_path.parent.name)
        except (OSError, ValueError, IndexError):
            continue
        if process_session == session_id and state != "Z":
            members.append((pid, process_group))
    return tuple(sorted(members))


def _session_members(session_id: int) -> tuple[int, ...]:
    return tuple(pid for pid, _group in _session_processes(session_id))


def _wait_empty(session_id: int, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _session_processes(session_id):
            return True
        time.sleep(0.10)
    return not _session_processes(session_id)


def _signal_session(session_id: int, signum: signal.Signals) -> None:
    # Gazebo's `gz sim` creates a separate process group for its server while
    # remaining in the launcher's session.  Signal every group in the SID,
    # taking a fresh snapshot at each escalation stage.
    groups = {group for _pid, group in _session_processes(session_id)}
    for process_group in groups:
        try:
            os.killpg(process_group, signum)
        except ProcessLookupError:
            continue


def stop_session(session_id: int) -> tuple[bool, tuple[int, ...]]:
    if session_id <= 1 or session_id in {os.getpid(), os.getsid(0)}:
        return False, _session_members(session_id)
    if not _session_processes(session_id):
        return True, ()

    for signum, timeout in (
        (signal.SIGINT, 6.0),
        (signal.SIGTERM, 3.0),
        (signal.SIGKILL, 2.0),
    ):
        try:
            _signal_session(session_id, signum)
        except PermissionError:
            return False, _session_members(session_id)
        if _wait_empty(session_id, timeout):
            return True, ()
    return False, _session_members(session_id)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("session_id", type=int)
    args = parser.parse_args()
    stopped, members = stop_session(args.session_id)
    if stopped:
        return 0
    print(
        f"process session {args.session_id} could not be stopped; members={members}",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
