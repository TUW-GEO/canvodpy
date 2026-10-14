"""Log handler that records a run's stage timings and problems in the run history.

Installed by :func:`~canvodpy.logging.logging_config.configure_logging` in
the main process and in every worker process, so the ``stage_timing``
events (:mod:`canvod.utils.logging.stage_timer`) and the warnings and
errors of a run reach the run history (ADR 0018) wherever they happen. A record counts
when it has the run ID of a run the run history holds; others are left
to the log files.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any

from canvod.utils.logging import get_run_id
from canvodpy.run_history import RunHistory


class RunHistoryHandler(logging.Handler):
    """Write stage timings, warnings and errors of recorded runs to the run history.

    The run history is opened at the first record that counts. If it
    cannot be opened or written, the handler stops: the log files still
    hold every record, and a run never fails because of its record.

    Parameters
    ----------
    log_dir : Path
        Log folder, which holds the run history.
    """

    def __init__(self, log_dir: Path) -> None:
        # stage_timing events are logged at INFO.
        super().__init__(level=logging.INFO)
        self._log_dir = log_dir
        self._history: RunHistory | None = None
        self._known_runs: set[str] = set()
        self._broken = False

    def emit(self, record: logging.LogRecord) -> None:
        if self._broken:
            return
        event = record.msg if isinstance(record.msg, dict) else {}
        is_timing = event.get("event") == "stage_timing"
        if not is_timing and record.levelno < logging.WARNING:
            return
        run_id = event.get("run_id") or get_run_id()
        if run_id is None:
            return
        try:
            history = self._open()
            if not self._is_recorded(history, run_id):
                return
            if is_timing:
                history.record_stage(
                    run_id,
                    str(event.get("stage")),
                    float(event.get("duration_seconds", 0.0)),
                    str(event.get("status", "ok")),
                    receiver=event.get("receiver") or event.get("group"),
                    day=_day(event),
                    pid=os.getpid(),
                )
            else:
                history.record_problem(
                    run_id,
                    level=record.levelname.lower(),
                    message=_plain_message(record, event),
                    receiver=event.get("receiver"),
                    day=_day(event),
                )
        except Exception:
            self._broken = True
            self.handleError(record)

    def close(self) -> None:
        if self._history is not None:
            self._history.close()
            self._history = None
        super().close()

    def _open(self) -> RunHistory:
        if self._history is None:
            self._history = RunHistory.open(self._log_dir)
        return self._history

    def _is_recorded(self, history: RunHistory, run_id: str) -> bool:
        # Only runs found are remembered: a run ID set before its run starts
        # (the command line sets it first) is recorded once the run exists.
        if run_id in self._known_runs:
            return True
        try:
            history.run(run_id)
        except KeyError:
            return False
        self._known_runs.add(run_id)
        return True


def _plain_message(record: logging.LogRecord, event: dict[str, Any]) -> str:
    """The event in words, with the exception that came with it."""
    if event:
        text = str(event.get("event", "")).replace("_", " ")
    else:
        text = record.getMessage()
    error = _exception(record, event)
    return text if error is None else f"{text}: {error}"


def _exception(record: logging.LogRecord, event: dict[str, Any]) -> str | None:
    """The exception of a record as ``Type: message``, if it has one."""
    # structlog has already turned it into the traceback text.
    traceback = event.get("exception")
    if isinstance(traceback, str) and traceback.strip():
        return traceback.strip().splitlines()[-1]
    exc_info = record.exc_info or event.get("exc_info")
    if exc_info is True:
        exc_info = sys.exc_info()
    if isinstance(exc_info, tuple) and len(exc_info) == 3:
        exc_info = exc_info[1]
    if isinstance(exc_info, BaseException):
        return f"{type(exc_info).__name__}: {exc_info}"
    return None


def _day(event: dict[str, Any]) -> str | None:
    day = event.get("date") or event.get("date_key")
    return None if day is None else str(day)
