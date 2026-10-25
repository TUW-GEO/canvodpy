"""Shut down the dashboard that ``canvodpy run --dashboard`` started.

The run hands its process to the dashboard in an environment variable, so
the dashboard can tell whether the run is still going and offer a button
that shuts the dashboard down once you are done with it.
"""

from __future__ import annotations

import os
import signal
import threading
from collections.abc import Mapping

import psutil

#: Set by ``canvodpy run --dashboard``: the run's process ID and start time.
RUN_VARIABLE = "CANVODPY_DASHBOARD_RUN"

#: Seconds from the click to the shutdown, so the page can still show that
#: the dashboard is shutting down.
SHUTDOWN_DELAY = 1.0


def run_marker() -> str:
    """The value of ``RUN_VARIABLE`` for the current process."""
    return f"{os.getpid()} {psutil.Process().create_time()!r}"


def run_going(environ: Mapping[str, str]) -> bool | None:
    """Whether the run that started this dashboard is still going.

    None when no run started it, as with ``canvodpy dashboard``, or when
    the variable doesn't hold a run. The start time tells the run apart
    from a later process that got its ID; a process this user may not
    look at is not the run either.
    """
    try:
        pid, started = environ.get(RUN_VARIABLE, "").split()
        pid_number, start_time = int(pid), float(started)
    except ValueError:
        return None
    try:
        return abs(psutil.Process(pid_number).create_time() - start_time) < 1
    except psutil.Error:  # gone, or another user's (AccessDenied)
        return False


def shut_down() -> None:
    """Stop the marimo server of this dashboard after ``SHUTDOWN_DELAY``.

    ``marimo run`` runs the notebook's cells in a thread of its server
    process, so signalling this process stops the server.
    """
    threading.Timer(SHUTDOWN_DELAY, os.kill, (os.getpid(), signal.SIGTERM)).start()
