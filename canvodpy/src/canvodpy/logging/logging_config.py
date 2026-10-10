"""Logging configuration for canvodpy with dual-output system.

This module configures structured logging with multiple outputs:
- Agent-diagnostic JSON logs (machine/agent.json) -- a curated causal
  narrative (run_id, stage transitions, degraded-path events, crashes)
  meant to let a human or an AI agent reconstruct what happened on a
  remote, unattended run from the log file alone.
- Human-readable text logs for interactive debugging
- Component-specific logs for isolation
- Log rotation for manageable file sizes

Every log record automatically carries the current ``run_id`` (see
``run_context.py``), and any exception that would otherwise escape the
process uncaught is captured here via ``sys.excepthook`` before the
process dies -- since on a remote run, the log is the only evidence that
will ever exist.
"""

import logging
import multiprocessing
import os
import re
import sys
import time
import traceback
from collections.abc import Callable
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
from pathlib import Path
from typing import Any

import structlog

from canvod.config import load_config
from canvod.utils.logging import get_run_id
from canvod.utils.tools import deprecated, deprecated_argument

# Log folder that file logging currently writes to; None while console only.
_active_log_dir: Path | None = None

# Log files of worker processes: the process ID before the extension, e.g.
# ``agent.12345.json``, ``main.12345.log.2026-10-09``.
_WORKER_LOG_FILE = re.compile(r"^[a-z]+\.\d+\.(json|log)")


def _process_log_suffix() -> str:
    """Return a filename suffix identifying the current OS process.

    Empty in the main process (unchanged filenames, backwards compatible).
    Non-empty in any other process (e.g. a loky/ProcessPoolExecutor worker),
    since ``RotatingFileHandler``/``TimedRotatingFileHandler`` are only safe
    within a single process — multiple processes rotating the same physical
    file race on ``os.rename()``. Giving each process its own file set
    removes the shared path entirely instead of trying to coordinate rotation
    across processes.
    """
    if multiprocessing.current_process().name == "MainProcess":
        return ""
    return f".{os.getpid()}"


def _setup_log_directories(base_dir: Path) -> dict[str, Path]:
    """Create organized log directory structure.

    Parameters
    ----------
    base_dir : Path
        Base logging directory (e.g., .logs/)

    Returns
    -------
    dict[str, Path]
        Dictionary of log directories by category.
    """
    dirs = {
        "machine": base_dir / "machine",
        "human": base_dir / "human",
        "component": base_dir / "component",
    }

    for directory in dirs.values():
        directory.mkdir(parents=True, exist_ok=True)

    return dirs


def _delete_old_worker_logs(
    log_dirs: dict[str, Path], retention_days: int
) -> list[Path]:
    """Delete worker log files that have not changed for *retention_days*.

    Each worker process writes its own files (see ``_process_log_suffix``)
    and new workers get new process IDs, so rotation, which works per file
    name, never removes them.

    Returns
    -------
    list[Path]
        Files that could not be deleted.
    """
    cutoff = time.time() - retention_days * 86_400
    failed: list[Path] = []
    for directory in log_dirs.values():
        for path in directory.iterdir():
            if not _WORKER_LOG_FILE.match(path.name):
                continue
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink()
            except FileNotFoundError:
                continue
            except OSError:
                failed.append(path)
    return failed


def _create_human_renderer() -> Callable[..., Any]:
    """Create human-readable formatter function.

    Returns
    -------
    Callable
        Processor function for human-readable logs.
    """

    def human_format(logger, name, event_dict):
        """Format log entry in traditional log format."""
        timestamp = event_dict.get("timestamp", "")
        level = event_dict.get("level", "INFO").upper()
        event = event_dict.get("event", "")

        # Extract context fields
        context_parts = []
        for key, value in sorted(event_dict.items()):
            # Skip internal/standard fields
            if key in ("timestamp", "level", "event", "logger", "exc_info"):
                continue
            if key.startswith("_"):
                continue
            context_parts.append(f"{key}={value}")

        context = f" [{', '.join(context_parts)}]" if context_parts else ""

        return f"{timestamp} {level:8s} {event}{context}"

    return human_format


def _create_error_renderer() -> Callable[..., Any]:
    """Create detailed error formatter with stack traces.

    Returns
    -------
    Callable
        Processor function for error logs with full context.
    """

    def error_format(logger, name, event_dict):
        """Format error log entry with full details."""
        timestamp = event_dict.get("timestamp", "")
        level = event_dict.get("level", "INFO").upper()
        event = event_dict.get("event", "")
        logger_name = event_dict.get("logger", "")

        # Build header
        lines = [
            f"{'=' * 80}",
            f"{timestamp} {level} [{logger_name}]",
            f"Event: {event}",
        ]

        # Add context fields
        context_items = []
        for key, value in sorted(event_dict.items()):
            if key in (
                "timestamp",
                "level",
                "event",
                "logger",
                "exc_info",
                "exception",
            ):
                continue
            if key.startswith("_"):
                continue
            context_items.append(f"  {key}: {value}")

        if context_items:
            lines.append("Context:")
            lines.extend(context_items)

        # Add exception if present
        exc_info = event_dict.get("exc_info")
        exception = event_dict.get("exception")
        if exception:
            lines.append("Exception:")
            lines.append(exception)
        elif exc_info:
            lines.append(f"Exception Info: {exc_info}")

        lines.append("")  # Blank line between errors
        return "\n".join(lines)

    return error_format


class ErrorFilter(logging.Filter):
    """Filter that only passes ERROR and CRITICAL level logs."""

    def filter(self, record):
        """Return True only for ERROR/CRITICAL levels."""
        return record.levelno >= logging.ERROR


class PerformanceFilter(logging.Filter):
    """Filter that only passes performance-timing logs.

    Matches the canonical event emitted by ``stage_timer()``
    (``event="stage_timing"``), plus any event that carries a
    ``duration_seconds`` field under its own specific event name -- many
    call sites (e.g. ``ephemeris_interpolation_complete``,
    ``aux_pipeline_create_standard_complete``) are deliberately detailed,
    named events that already report timing alongside other business
    context (shapes, dims, counts); they're not a "ragged" convention that
    needs consolidating into a generic event name, just correctly-named
    already. Only the genuinely inconsistent field names
    (``processing_time_min``, ``hampel_processing_time_s``, etc.) needed
    fixing, not these.
    """

    def filter(self, record):
        """Return True for stage_timing events or any duration_seconds field."""
        if hasattr(record, "msg") and isinstance(record.msg, dict):
            msg = record.msg
            return msg.get("event") == "stage_timing" or "duration_seconds" in msg
        return False


class ComponentFilter(logging.Filter):
    """Filter that only passes logs from specific component."""

    def __init__(self, component_name: str):
        """Initialize filter for specific component.

        Parameters
        ----------
        component_name : str
            Name of component to filter (e.g., "processor", "auxiliary")
        """
        super().__init__()
        self.component_name = component_name

    def filter(self, record):
        """Return True only for logs from this component."""
        # Check logger name
        if self.component_name in record.name:
            return True

        # Check if log message dict has component field
        if (
            hasattr(record, "msg")
            and isinstance(record.msg, dict)
            and record.msg.get("component") == self.component_name
        ):
            return True

        # Check if record has component attribute (set by ProcessorFormatter)
        return hasattr(record, "component") and record.component == self.component_name


def _add_run_id(logger, name, event_dict):
    """Inject the current run_id (if any) into every log event.

    Lets every log record be correlated to a single pipeline invocation
    (see ``run_context.py``) without any call site passing it explicitly.
    """
    run_id = get_run_id()
    if run_id is not None:
        event_dict["run_id"] = run_id
    return event_dict


def _install_excepthook(logger: structlog.BoundLogger) -> None:
    """Install a process-wide safety net for uncaught exceptions.

    On a remote, unattended run there is no re-run and no debugger --
    the log file is the only forensic evidence that will ever exist. Any
    exception that reaches here would otherwise propagate to Python's
    default handler and be lost if stderr isn't captured, so this logs a
    structured ``uncaught_exception`` event (with the current run_id and
    full traceback) before chaining to the default hook, which still runs
    so console behavior for attended sessions is unchanged.

    Idempotent: ``configure_logging()`` usually runs once per process
    (through ``ensure_file_logging()``), but can run more than once (tests,
    or a second run in the same process with another log location). Without
    this guard, each call would wrap the *previous* call's hook, growing an
    ever-longer chain that re-logs the same exception once per wrap. The
    marker lives on ``sys.excepthook`` itself (not separate module state),
    so if something resets ``sys.excepthook`` externally between calls
    (e.g. a test fixture), the next call correctly reinstalls rather than
    silently no-op'ing against a hook that's no longer actually wired up.
    """
    if getattr(sys.excepthook, "_is_canvodpy_excepthook", False):
        sys.excepthook._logger_holder[0] = logger  # ty: ignore[unresolved-attribute]
        return

    default_hook = sys.excepthook
    logger_holder = [logger]

    def _excepthook(exc_type, exc_value, exc_tb):
        if not issubclass(exc_type, KeyboardInterrupt):
            try:
                logger_holder[0].error(
                    "uncaught_exception",
                    exc_type=exc_type.__name__,
                    exc_message=str(exc_value),
                    traceback="".join(
                        traceback.format_exception(exc_type, exc_value, exc_tb)
                    ),
                )
            except Exception:
                # The crash handler must never itself crash the crash report.
                pass
        default_hook(exc_type, exc_value, exc_tb)

    _excepthook._is_canvodpy_excepthook = True  # ty: ignore[unresolved-attribute]
    _excepthook._logger_holder = logger_holder  # ty: ignore[unresolved-attribute]
    sys.excepthook = _excepthook


def _shared_processors() -> list[Callable[..., Any]]:
    """Return the processors every log record passes, on every output."""
    return [
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.add_log_level,
        _add_run_id,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
        structlog.processors.format_exc_info,
    ]


def _reset_root_logger() -> logging.Logger:
    """Remove all handlers from the root logger and let it accept all levels."""
    logging.basicConfig(level=logging.DEBUG, format="%(message)s")
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(logging.DEBUG)
    return root_logger


def _console_handler(shared_processors: list[Callable[..., Any]]) -> logging.Handler:
    """Return the stdout handler: warnings and errors only."""
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.WARNING)
    console_handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared_processors,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.dev.ConsoleRenderer(),
            ],
        )
    )
    return console_handler


def _configure_structlog(shared_processors: list[Callable[..., Any]]) -> None:
    """Route structlog through the stdlib root logger's handlers."""
    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.make_filtering_bound_logger(logging.DEBUG),
        cache_logger_on_first_use=True,
    )
    logging.getLogger("canvodpy").setLevel(logging.DEBUG)


def configure_console_logging() -> None:
    """Log warnings and errors to stdout only, without reading the settings.

    Runs when canvodpy is imported. It writes no files: file logging starts
    with :func:`configure_logging`, which a pipeline calls once the
    configuration directory of the run is known.
    """
    global _active_log_dir
    shared_processors = _shared_processors()
    _reset_root_logger().addHandler(_console_handler(shared_processors))
    _configure_structlog(shared_processors)
    _active_log_dir = None


def active_log_dir() -> Path | None:
    """Return the folder file logging writes to, or None while console only."""
    return _active_log_dir


def ensure_file_logging() -> None:
    """Start file logging from the settings, unless it already writes there.

    Called when a pipeline is created, so the log location comes from the
    configuration of the run (for the CLI: after ``--config-dir`` and
    ``--config`` are applied), not from whatever configuration was found
    when canvodpy was imported. Worker processes get the resulting folder
    from their parent (``active_log_dir()``) instead of reading the
    settings again.

    Raises
    ------
    canvod.config.loader.ConfigValidationError
        If the settings are invalid.
    canvod.config.models.logging.LogDirNotSetError
        If ``processing.logging.log_dir`` is not set.
    """
    settings = load_config().processing.logging
    log_dir = settings.get_log_dir()
    if log_dir != _active_log_dir:
        configure_logging(
            log_dir=log_dir,
            worker_log_retention_days=settings.worker_log_retention_days,
        )


@deprecated_argument(
    "logfile",
    "The `logfile` argument of `configure_logging` is left over from development "
    "and will be removed with the next major version. Pass the folder as "
    "`log_dir` instead.",
)
def configure_logging(
    logfile: Path | None = None,
    *,
    log_dir: Path | None = None,
    worker_log_retention_days: int | None = None,
) -> structlog.BoundLogger:
    """Write the log files under *log_dir*, and warnings and errors to stdout.

    Creates the log tree (all file handlers rotate):

    - ``machine/agent.json``: every event, as JSON lines
    - ``machine/performance.json``: the timing events
    - ``human/main.log``, ``human/errors.log``: readable logs
    - ``component/{processor,auxiliary,icechunk}.log``: per component

    Parameters
    ----------
    log_dir : Path, optional
        Log folder. Without it, ``processing.logging.log_dir`` of the
        settings.
    worker_log_retention_days : int, optional
        In the main process, delete worker log files that have not changed
        for this many days. Without it: the setting
        ``processing.logging.worker_log_retention_days`` if *log_dir* is
        not given, otherwise no files are deleted.

    Raises
    ------
    canvod.config.loader.ConfigValidationError
        If ``log_dir`` is not given and the settings are invalid.
    canvod.config.models.logging.LogDirNotSetError
        If ``log_dir`` is not given and the settings set none.

    Returns
    -------
    structlog.BoundLogger
        Configured structlog logger.
    """
    global _active_log_dir
    if logfile is not None:
        log_dir = logfile.parent
    if log_dir is None:
        settings = load_config().processing.logging
        log_dir = settings.get_log_dir()
        if worker_log_retention_days is None:
            worker_log_retention_days = settings.worker_log_retention_days

    # Set up directory structure
    log_dirs = _setup_log_directories(log_dir)

    # Distinguishes worker-process log files from the main process's, so
    # concurrent processes never share a physical path (see _process_log_suffix).
    suffix = _process_log_suffix()

    shared_processors = _shared_processors()
    json_renderer = structlog.processors.JSONRenderer()
    root_logger = _reset_root_logger()
    console_handler = _console_handler(shared_processors)

    # ========================================================================
    # HANDLER 2: Agent-diagnostic JSON - always-on DEBUG causal narrative
    # ========================================================================
    # Deliberately always-on (never gated behind a debug flag): on a remote
    # unattended run there is no way to retroactively enable debug logging
    # after a failure, so this must already be capturing everything.
    agent_log = log_dirs["machine"] / f"agent{suffix}.json"
    agent_handler = RotatingFileHandler(
        agent_log,
        maxBytes=100 * 1024 * 1024,  # 100MB max per file
        # backupCount=10 (1GB) only reached ~1h back on a 15h overnight run
        # (~2.2GB/day observed, 2026-07-15) -- found by hitting it directly,
        # while investigating that same run's write-side degradation:
        # agent.json.10 (the oldest kept backup) started at 23:14 UTC, but
        # the run began at 22:15, so the first hour of debug detail for that
        # run was already gone. 150 (~15GB, ~7 days at this rate) is a
        # stopgap sized for "don't lose crash forensics within about a
        # week," not a durable fix -- same caveat as performance.json's
        # backupCount bump: the real answer is
        # exporting before rotation can touch it.
        backupCount=150,
        encoding="utf-8",
        # Opens the file at the first record: a worker that logs nothing
        # leaves no empty files behind.
        delay=True,
    )
    agent_handler.setLevel(logging.DEBUG)  # Capture everything
    agent_formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            json_renderer,
        ],
    )
    agent_handler.setFormatter(agent_formatter)

    # ========================================================================
    # HANDLER 3: Human-readable - Traditional logs with rotation
    # ========================================================================
    human_log = log_dirs["human"] / f"main{suffix}.log"
    human_handler = TimedRotatingFileHandler(
        human_log,
        when="midnight",  # Rotate at midnight
        interval=1,  # Daily rotation
        backupCount=30,  # Keep 30 days
        encoding="utf-8",
        # Opens the file at the first record: a worker that logs nothing
        # leaves no empty files behind.
        delay=True,
    )
    human_handler.setLevel(logging.INFO)
    human_formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            _create_human_renderer(),
        ],
    )
    human_handler.setFormatter(human_formatter)

    # ========================================================================
    # HANDLER 4: Errors Only - Detailed error logs with stack traces
    # ========================================================================
    error_log = log_dirs["human"] / f"errors{suffix}.log"
    error_handler = RotatingFileHandler(
        error_log,
        maxBytes=50 * 1024 * 1024,  # 50MB max per file
        backupCount=5,  # Keep 5 rotated files
        encoding="utf-8",
        # Opens the file at the first record: a worker that logs nothing
        # leaves no empty files behind.
        delay=True,
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.addFilter(ErrorFilter())
    error_formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            _create_error_renderer(),
        ],
    )
    error_handler.setFormatter(error_formatter)

    # ========================================================================
    # HANDLER 5: Performance Metrics - Timing and throughput data
    # ========================================================================
    perf_log = log_dirs["machine"] / f"performance{suffix}.json"
    perf_handler = RotatingFileHandler(
        perf_log,
        maxBytes=50 * 1024 * 1024,  # 50MB max per file
        # backupCount=10 (500MB) silently deleted history after ~5 days on a
        # real overnight backfill (~96MB/day observed, 2026-07-15) -- too
        # short for the "runs may take days, or are triggered daily and run
        # forever" case. 60 (~3GB/~31 days) is a stopgap, not a fix: the
        # durable answer is exporting machine/performance*.json into a
        # persistent store before rotation can touch it (not yet built).
        backupCount=60,
        encoding="utf-8",
        # Opens the file at the first record: a worker that logs nothing
        # leaves no empty files behind.
        delay=True,
    )
    perf_handler.setLevel(logging.DEBUG)
    perf_handler.addFilter(PerformanceFilter())
    perf_formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            json_renderer,
        ],
    )
    perf_handler.setFormatter(perf_formatter)

    # ========================================================================
    # HANDLER 6-8: Component-specific logs
    # ========================================================================
    component_handlers = []
    for component_name in ["processor", "auxiliary", "icechunk"]:
        comp_log = log_dirs["component"] / f"{component_name}{suffix}.log"
        comp_handler = TimedRotatingFileHandler(
            comp_log,
            when="midnight",
            interval=1,
            backupCount=7,  # Keep 1 week
            encoding="utf-8",
            delay=True,
        )
        comp_handler.setLevel(logging.DEBUG)
        comp_handler.addFilter(ComponentFilter(component_name))
        comp_formatter = structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared_processors,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                _create_human_renderer(),
            ],
        )
        comp_handler.setFormatter(comp_formatter)
        component_handlers.append(comp_handler)

    # Register all handlers
    root_logger.addHandler(console_handler)
    root_logger.addHandler(agent_handler)
    root_logger.addHandler(human_handler)
    root_logger.addHandler(error_handler)
    root_logger.addHandler(perf_handler)
    for handler in component_handlers:
        root_logger.addHandler(handler)

    _configure_structlog(shared_processors)
    logger = structlog.get_logger("canvodpy")
    _install_excepthook(logger)
    _active_log_dir = log_dir

    if worker_log_retention_days is not None and not suffix:
        failed = _delete_old_worker_logs(log_dirs, worker_log_retention_days)
        if failed:
            logger.warning(
                "worker_logs_not_deleted",
                files=[str(path) for path in failed],
                retention_days=worker_log_retention_days,
            )

    return logger


# Importing canvodpy reads no settings and writes no log files.
configure_console_logging()
LOGGER = structlog.get_logger("canvodpy")


@deprecated(
    "`get_file_logger` is left over from development and will be removed with "
    "the next major version. Use `structlog.get_logger(__name__).bind(file=...)` "
    "instead."
)
def get_file_logger(fname: Path) -> structlog.BoundLogger:
    """Return logger bound with parent/parent/file path.

    Parameters
    ----------
    fname : Path
        File path to include in the log context.

    """
    try:
        depth = load_config().processing.logging.log_path_depth
    except Exception:
        depth = 6
    rel_path = Path(*fname.parts[-depth:])
    return LOGGER.bind(file=str(rel_path))
