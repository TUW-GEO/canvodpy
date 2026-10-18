"""Resource monitoring for pipeline processing."""

from __future__ import annotations

import os
import threading
import time
import types
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, date, datetime
from pathlib import Path

import psutil
import structlog

from canvod.utils.logging import get_run_id, set_run_id
from canvod.utils.tools import deprecated_argument, directory_size_bytes

logger = structlog.get_logger(__name__)

_NO_EFFECT_ARGUMENTS = {
    "cpu_affinity": (
        "It has no effect: the worker processes take their CPU cores from "
        "processing.params.cpu_affinity in canvod-settings.yaml. Set it there."
    ),
    "nice_priority": (
        "It has no effect: the worker processes take their priority from "
        "processing.params.nice_priority in canvod-settings.yaml. Set it there."
    ),
}


def deprecate_no_effect_arguments[F: Callable[..., object]](func: F) -> F:
    """Deprecate the resource arguments that have no effect on *func*."""
    if not isinstance(func, types.FunctionType):
        msg = f"deprecate_no_effect_arguments decorates functions, not {func!r}"
        raise TypeError(msg)
    caller = func.__qualname__.removesuffix(".__init__")
    for name, reason in _NO_EFFECT_ARGUMENTS.items():
        func = deprecated_argument(
            name,
            f"The {name!r} argument of {caller}() is left over "
            "from development and will be removed with the next major "
            f"version. {reason} Remove the argument.",
        )(func)
    return func


class MemoryMonitor:
    """Monitor system memory and log advisory snapshots.

    Used by ``PipelineOrchestrator`` for batch-level memory logging.
    Enforcement is advisory only; worker processes are not memory-capped.

    Parameters
    ----------
    max_memory_gb : float | None
        Soft RAM limit in GB (informational only). None means no limit.

    """

    def __init__(self, max_memory_gb: float | None = None) -> None:
        self.max_memory_gb = max_memory_gb

    def available_gb(self) -> float:
        """Current available system memory in GB."""
        return psutil.virtual_memory().available / (1024**3)

    def used_percent(self) -> float:
        """Current system memory usage percentage."""
        return psutil.virtual_memory().percent

    def log_memory_stats(self, context: str = "") -> None:
        """Log current memory statistics.

        Parameters
        ----------
        context : str
            Description of when this snapshot was taken.

        """
        mem = psutil.virtual_memory()
        logger.info(
            "memory_stats",
            context=context,
            available_gb=round(mem.available / (1024**3), 2),
            used_percent=round(mem.percent, 1),
            total_gb=round(mem.total / (1024**3), 2),
        )


def run_measured[R](input_bytes: int, func: Callable[..., R], *args: object) -> R:
    """Run ``func(*args)`` in a worker and log the worker's memory peak.

    The peak is sampled every 20 ms while the task runs. The log event
    ``worker_memory_peak`` gives the worker's memory before the task, its
    peak during the task, and the size of the task's input files, so the
    memory budget (``processing.params.max_memory_gb``) can be tuned.
    """
    process = psutil.Process()
    before = process.memory_info().rss
    peak = before
    done = threading.Event()

    def sample() -> None:
        nonlocal peak
        while not done.wait(0.02):
            peak = max(peak, process.memory_info().rss)

    sampler = threading.Thread(target=sample, name="worker-memory", daemon=True)
    sampler.start()
    t0 = time.perf_counter()
    try:
        return func(*args)
    finally:
        done.set()
        sampler.join()
        peak = max(peak, process.memory_info().rss)
        logger.info(
            "worker_memory_peak",
            pid=os.getpid(),
            task=getattr(func, "__name__", repr(func)),
            input_mb=round(input_bytes / 1024**2, 2),
            before_gb=round(before / 1024**3, 3),
            peak_gb=round(peak / 1024**3, 3),
            seconds=round(time.perf_counter() - t0, 2),
        )


class ResourceSampler:
    """Periodic background sampler for memory/CPU/disk I/O.

    ``MemoryMonitor.log_memory_stats`` only snapshots once per batch. This
    runs as a daemon thread emitting one ``resource_sample`` event every
    ``interval_seconds`` for the whole run (including time spent outside
    batch boundaries, e.g. aux data fetch/interpolation), so a wall-clock
    slowdown seen in stage_timing events can be correlated against actual
    resource pressure instead of assumed. :meth:`stop` takes one last
    sample, so a run shorter than the interval has one too.

    Parameters
    ----------
    interval_seconds : float
        Seconds between samples.
    disks : iterable of Path or str
        Folders whose free disk space each sample records.
    stores : mapping of name to Path, optional
        Local store folders whose on-disk size each sample measures. A
        store that is not on the local disk is left out. The measure is a
        walk of the folder, so it grows with the store; it runs on this
        background thread, never inside a stage or a commit.
    on_sample : callable, optional
        Called with ``cpu_percent``, ``memory_percent`` and ``free_disk``
        (bytes per folder of *disks*) for every sample; the run history
        records them this way (``canvodpy.run_history.recorded_run``).
    on_store_size : callable, optional
        Called with ``(store, day, bytes)`` for every store, once a day
        (when the UTC day changes, and once more when the sampler stops), so
        the last size of each day is kept.
    """

    def __init__(
        self,
        interval_seconds: float = 30.0,
        *,
        disks: Iterable[Path | str] = (),
        stores: Mapping[str, Path] | None = None,
        on_sample: Callable[..., None] | None = None,
        on_store_size: Callable[..., None] | None = None,
    ) -> None:
        self.interval_seconds = interval_seconds
        self.disks = [str(Path(folder).expanduser()) for folder in disks]
        self.stores = {
            name: Path(path).expanduser() for name, path in (stores or {}).items()
        }
        self.on_sample = on_sample
        self.on_store_size = on_store_size
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._run_id = get_run_id()
        self._sample_index = 0
        self._prev_io = None
        self._last_store_day: date | None = None

    def start(self) -> None:
        """Start sampling in a daemon thread. Safe to call once per run."""
        self._run_id = get_run_id()
        self._stop.clear()
        self._last_store_day = None
        # The first cpu_percent call only starts the measurement.
        psutil.cpu_percent(interval=None)
        try:
            self._prev_io = psutil.disk_io_counters()
        except Exception:
            self._prev_io = None
        self._thread = threading.Thread(
            target=self._run_loop, name="resource-sampler", daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        """Stop the sampler thread, then take the last sample."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None
            self._sample(final=True)

    def _run_loop(self) -> None:
        # Contextvars don't cross thread boundaries automatically -- carry
        # run_id in explicitly, matching _worker_init_with_run_id's pattern
        # for loky workers (pipeline.py).
        if self._run_id:
            set_run_id(self._run_id)
        while not self._stop.wait(self.interval_seconds):
            self._sample()

    def _sample(self, *, final: bool = False) -> None:
        self._sample_index += 1
        t0 = time.perf_counter()
        try:
            proc = psutil.Process()
            mem = psutil.virtual_memory()
            main_rss_gb = proc.memory_info().rss / (1024**3)

            children_rss_gb = 0.0
            try:
                for child in proc.children(recursive=True):
                    try:
                        children_rss_gb += child.memory_info().rss / (1024**3)
                    except psutil.NoSuchProcess, psutil.AccessDenied:
                        continue
            except Exception:
                pass

            read_mb = write_mb = None
            try:
                io = psutil.disk_io_counters()
                if io is not None and self._prev_io is not None:
                    read_mb = (io.read_bytes - self._prev_io.read_bytes) / (1024**2)
                    write_mb = (io.write_bytes - self._prev_io.write_bytes) / (1024**2)
                self._prev_io = io
            except Exception:
                pass

            cpu_percent = psutil.cpu_percent(interval=None)
            free_disk = _free_disk(self.disks)
            logger.info(
                "resource_sample",
                duration_seconds=round(time.perf_counter() - t0, 4),
                sample_index=self._sample_index,
                available_gb=round(mem.available / (1024**3), 2),
                used_percent=round(mem.percent, 1),
                main_rss_gb=round(main_rss_gb, 3),
                children_rss_gb=round(children_rss_gb, 3),
                cpu_percent=cpu_percent,
                disk_read_mb=round(read_mb, 2) if read_mb is not None else None,
                disk_write_mb=round(write_mb, 2) if write_mb is not None else None,
                free_disk=free_disk,
            )
            if self.on_sample is not None:
                self.on_sample(
                    cpu_percent=cpu_percent,
                    memory_percent=mem.percent,
                    free_disk=free_disk,
                )
            if self.stores and self.on_store_size is not None:
                today = datetime.now(UTC).date()
                if final or today != self._last_store_day:
                    for name, path in self.stores.items():
                        self.on_store_size(
                            name, today.isoformat(), directory_size_bytes(path)
                        )
                    self._last_store_day = today
        except Exception:
            logger.debug("resource_sample_failed", exc_info=True)


def _free_disk(folders: Iterable[str]) -> dict[str, int]:
    """Free bytes of the disk of each folder (or its nearest existing parent)."""
    free = {}
    for folder in folders:
        path = Path(folder)
        existing = next((p for p in (path, *path.parents) if p.exists()), None)
        if existing is not None:
            free[folder] = psutil.disk_usage(str(existing)).free
    return free


# Anchored to the user's home directory, not Path.cwd() -- `canvodpy run`
# and `canvodpy store maintain-due` are typically launched from different
# contexts (interactive shell vs. cron/systemd, each with its own working
# directory), and a cwd-relative default would silently produce two
# different paths, defeating the same-host concurrency check with no
# error. Same-user, same-host is still required (see is_pipeline_running's
# docstring for the network-mounted-store caveat this doesn't cover).
DEFAULT_RUN_PID_FILE = Path.home() / ".cache" / "canvodpy" / "run.pid"


def is_pipeline_running(pid_file: Path | None = None) -> bool:
    """Check whether a `canvodpy run` process is currently active.

    Used by ``canvodpy store maintain-due`` (a cron-safe, non-interactive
    entry point for scheduled Icechunk expiration/GC) to defend against
    running maintenance concurrently with an active pipeline write -- both
    are explicitly documented as unsafe to overlap (see
    ``MyIcechunkStore.maintenance()``'s docstring). Same-host only: this
    cannot see a pipeline run on a different host writing to the same
    network-mounted (CIFS/NFS) store -- that case must be kept apart by
    the operator (e.g. scheduling maintenance in a known-idle window).

    Liveness is checked via the recorded PID, not just the file's
    existence, so a stale file left behind by a hard crash (SIGKILL, OOM)
    correctly reads as "not running" without needing separate stale-lock
    cleanup.

    Parameters
    ----------
    pid_file : Path, optional
        Location written by :class:`PipelineRunLock`; ``DEFAULT_RUN_PID_FILE``
        if not given.

    Returns
    -------
    bool
        True if the recorded PID belongs to a live process.
    """
    # Read the default when called, not when defined, so tests can move it.
    pid_file = pid_file or DEFAULT_RUN_PID_FILE
    if not pid_file.exists():
        return False
    try:
        pid = int(pid_file.read_text().strip())
    except ValueError, OSError:
        return False
    return psutil.pid_exists(pid)


class PipelineRunLock:
    """Context manager marking a `canvodpy run` invocation as active.

    Writes this process's PID to ``pid_file`` on entry, removes it on
    clean exit. Does not prevent concurrent pipeline runs (loky/dask
    already have their own resource contention if that's attempted) --
    it exists solely as a same-host signal for
    :func:`is_pipeline_running`, so a scheduled maintenance job can skip
    itself while a pipeline write is in progress.
    """

    def __init__(self, pid_file: Path | None = None) -> None:
        self.pid_file = pid_file or DEFAULT_RUN_PID_FILE

    def __enter__(self) -> PipelineRunLock:
        self.pid_file.parent.mkdir(parents=True, exist_ok=True)
        self.pid_file.write_text(str(os.getpid()))
        return self

    def __exit__(self, *exc_info: object) -> None:
        try:
            self.pid_file.unlink()
        except FileNotFoundError:
            pass
