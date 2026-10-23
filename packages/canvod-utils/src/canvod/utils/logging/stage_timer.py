"""Lightweight, always-on performance tracking.

Deliberately not full telemetry: no spans, no collectors, no exporters, no
extra dependency (see ``canvodpy/utils/telemetry.py``'s removal -- an
OpenTelemetry-based tracer that was dead weight because ``opentelemetry``
was never installed). ``stage_timer()`` replaces the previously ragged mix
of field names (``duration_seconds``, ``processing_time_min``,
``hampel_processing_time_s``, ...) scattered across the codebase with one
canonical event (``stage_timing``), and a small in-process accumulator
produces an end-of-run summary -- what a human skims first, and what an
agent uses to see how far a run got before it died (the crash-handling path
in ``cli/run.py`` calls ``emit_run_summary`` too, so a partial summary
exists even for a run that later failed).

Only the main process accumulates. Stages timed in a worker process
(``ProcessPoolExecutor``/loky) still reach the log -- each worker writes its
own per-PID log file, see ``canvodpy.logging.logging_config``'s
``_process_log_suffix`` -- but not the ``run_summary`` of the main process;
collecting them would need exactly the cross-process machinery this module
exists to avoid. Workers keep no totals, so long-lived workers don't
accumulate them across runs.
"""

from __future__ import annotations

import functools
import multiprocessing
import threading
import time
from collections.abc import Callable, Generator
from contextlib import contextmanager
from typing import Any, TypeVar

import structlog

from canvod.utils.logging.run_context import get_run_id

log = structlog.get_logger(__name__)

_F = TypeVar("_F", bound=Callable[..., Any])

_lock = threading.Lock()
# {run_id: {stage: {"count": float, "total_seconds": float, "errors": float}}}
_run_stats: dict[str, dict[str, dict[str, float]]] = {}

_NO_RUN_ID = "_no_run_id"


@contextmanager
def stage_timer(stage: str, **context: Any) -> Generator[None]:
    """Time a block of code and emit one canonical ``stage_timing`` event.

    Emits on both success and failure (``status="error"`` on the latter)
    before any exception propagates, so a run summary can still be produced
    for a run that later crashes.

    Parameters
    ----------
    stage : str
        Canonical stage name (e.g. ``"rinex.process_file"``,
        ``"icechunk.write"``).
    **context
        Extra fields attached to the emitted event (e.g. ``file=...``,
        ``site=...``).
    """
    start = time.perf_counter()
    status = "ok"
    try:
        yield
    except Exception:
        status = "error"
        raise
    finally:
        record_stage_timing(stage, time.perf_counter() - start, status, **context)


def record_stage_timing(
    stage: str, duration_seconds: float, status: str = "ok", **context: Any
) -> None:
    """Emit one ``stage_timing`` event for a duration measured by the caller.

    For code that measures several stages from one set of checkpoints
    instead of one block per stage. The stage counts toward the run summary
    like a :func:`stage_timer` block.

    Parameters
    ----------
    stage : str
        Stage name (e.g. ``"writing"``).
    duration_seconds : float
        Duration of the stage.
    status : {"ok", "error"}, default "ok"
        Whether the stage succeeded.
    **context
        Extra fields attached to the event (e.g. ``receiver=...``,
        ``date_key=...``).
    """
    log.info(
        "stage_timing",
        stage=stage,
        duration_seconds=round(duration_seconds, 3),
        status=status,
        **context,
    )
    _record(stage, duration_seconds, status)


def timed_stage(stage: str, **context: Any) -> Callable[[_F], _F]:
    """Decorator form of :func:`stage_timer`."""

    def decorator(func: _F) -> _F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            with stage_timer(stage, **context):
                return func(*args, **kwargs)

        return wrapper  # ty: ignore[invalid-return-type]

    return decorator


def _record(stage: str, duration: float, status: str) -> None:
    if multiprocessing.parent_process() is not None:
        return  # worker process: see the module docstring
    run_id = get_run_id() or _NO_RUN_ID
    with _lock:
        stats = _run_stats.setdefault(run_id, {})
        entry = stats.setdefault(
            stage, {"count": 0.0, "total_seconds": 0.0, "errors": 0.0}
        )
        entry["count"] += 1
        entry["total_seconds"] += duration
        if status == "error":
            entry["errors"] += 1


def emit_run_summary(**context: Any) -> None:
    """Emit a ``run_summary`` event: per-stage breakdown for the current run.

    The breakdown covers the stages timed in the main process (in canVODpy:
    writing the GNSS store, computing and writing VOD); the stages of the
    worker processes are only in the log. Called at the end of a successful
    run and also from the crash-handling path in ``cli/run.py``, so a
    partial summary exists even for a run that later failed -- showing how
    far it got before dying.
    """
    run_id = get_run_id() or _NO_RUN_ID
    with _lock:
        stages = {
            stage: dict(entry) for stage, entry in _run_stats.get(run_id, {}).items()
        }

    total_seconds = sum(entry["total_seconds"] for entry in stages.values())
    log.info(
        "run_summary",
        stages={
            stage: {
                "count": int(entry["count"]),
                "total_seconds": round(entry["total_seconds"], 3),
                "errors": int(entry["errors"]),
            }
            for stage, entry in stages.items()
        },
        total_seconds=round(total_seconds, 3),
        **context,
    )


def reset_run_stats(run_id: str | None = None) -> None:
    """Clear accumulated stage stats for ``run_id`` (or all, if None).

    Call after emitting a run's summary to avoid unbounded growth of the
    in-process accumulator across many runs in a long-lived interpreter
    (e.g. a scheduler that reuses the process across invocations).
    """
    with _lock:
        if run_id is None:
            _run_stats.clear()
        else:
            _run_stats.pop(run_id, None)
