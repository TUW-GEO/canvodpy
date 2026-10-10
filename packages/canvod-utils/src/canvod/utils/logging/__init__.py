"""Logging helpers shared by the canvod packages.

The packages log through structlog: every module gets its logger with
``structlog.get_logger(__name__)``. The output (console, log files) is
configured by ``canvodpy.logging.configure_logging``; a package used without
canvodpy logs through structlog's defaults.

- :mod:`~canvod.utils.logging.run_context`: the run identifier added to every
  log record and Icechunk commit message of a run.
- :mod:`~canvod.utils.logging.stage_timer`: timing of the processing stages
  and the end-of-run summary.
"""

from canvod.utils.logging.run_context import (
    get_run_id,
    new_run_id,
    reset_run_id,
    set_run_id,
)
from canvod.utils.logging.stage_timer import (
    emit_run_summary,
    record_stage_timing,
    reset_run_stats,
    stage_timer,
    timed_stage,
)

__all__ = [
    "emit_run_summary",
    "get_run_id",
    "new_run_id",
    "record_stage_timing",
    "reset_run_id",
    "reset_run_stats",
    "set_run_id",
    "stage_timer",
    "timed_stage",
]
