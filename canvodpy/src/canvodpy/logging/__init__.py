"""Logging utilities for canvodpy.

Uses structlog for LLM-friendly log output. Scientists can feed logs to
LLMs for debugging assistance.

Examples
--------
Get a logger:

    >>> import structlog
    >>> log = structlog.get_logger(__name__)
    >>> log.info("processing_started", site="ExampleSite", date="2025001")

Importing canvodpy logs warnings and errors to the console only and reads
no settings. File logging (the log tree under
``processing.logging.log_dir``) starts when a pipeline is created.
To start it yourself, for example before calling the functional API:

    >>> from canvodpy.logging import setup_logging
    >>> setup_logging()
"""

from typing import Any

import structlog

# The deprecated submodules are loaded first: importing a submodule binds its
# name in this package, which must stay the stage_timer function below.
import canvodpy.logging.run_context
import canvodpy.logging.stage_timer
from canvod.utils.logging import (
    emit_run_summary,
    get_run_id,
    new_run_id,
    record_stage_timing,
    reset_run_id,
    set_run_id,
    stage_timer,
    timed_stage,
)
from canvod.utils.tools import deprecated
from canvodpy.logging.logging_config import configure_logging, ensure_file_logging

# Alias for API compatibility
setup_logging = configure_logging


@deprecated(
    "`canvodpy.logging.get_logger` is left over from development and will be "
    "removed with the next major version. Use `structlog.get_logger` instead."
)
def get_logger(name: str | None = None) -> Any:
    """Return ``structlog.get_logger(name)``.

    .. deprecated::
        Use ``structlog.get_logger(__name__)`` instead.
    """
    return structlog.get_logger(name)


__all__ = [
    "configure_logging",
    "emit_run_summary",
    "ensure_file_logging",
    "get_logger",
    "get_run_id",
    "new_run_id",
    "record_stage_timing",
    "reset_run_id",
    "set_run_id",
    "setup_logging",
    "stage_timer",
    "timed_stage",
]
