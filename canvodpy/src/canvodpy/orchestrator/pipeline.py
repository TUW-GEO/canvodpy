"""Processing pipeline orchestration for site-level workflows."""

from __future__ import annotations

import contextvars
import gc
import os
import queue
import threading
import time as _time
import warnings
from collections import defaultdict
from collections.abc import Callable, Generator, Hashable, Iterable, Sequence
from concurrent.futures import (
    FIRST_COMPLETED,
    Executor,
    Future,
    ThreadPoolExecutor,
    as_completed,
    wait,
)
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass
from datetime import datetime
from functools import partial
from itertools import zip_longest
from pathlib import Path
from typing import TypeVar, cast

import icechunk
import numpy as np
import pandas as pd
import psutil
import structlog
import xarray as xr
from icechunk.session import ForkSession
from loky import get_reusable_executor as _loky_reusable

from canvod.config import CanvodConfig, load_config
from canvod.config.models import mixed_format_error, reference_store_group
from canvod.ops import preprocess_files
from canvod.readers import MatchedDirs
from canvod.store import GnssResearchSite
from canvod.store.store import _with_run_id
from canvod.store_metadata import (
    check_content_settings,
    missing_store_settings,
    missing_store_settings_message,
    read_repository_metadata,
    store_command,
    store_exists,
)
from canvod.utils.logging import (
    get_run_id,
    new_run_id,
    record_stage_timing,
    reset_run_id,
    set_run_id,
    stage_timer,
)
from canvod.utils.tools import (
    YYYYDOY,
    deprecated,
    deprecated_argument,
    file_hash,
    get_version_from_pyproject,
)
from canvodpy.logging.logging_config import active_log_dir, ensure_file_logging
from canvodpy.orchestrator.discovery import (
    ReceiverDay,
    check_receivers,
    clear_discovery_cache,
    detect_reader_format,
    discover_files,
    files_per_day,
    is_compressed,
    receiver_days,
    recipe_file,
    require_filemap,
    saved_file_index,
    scan_directory,
    unprocessed_files,
)
from canvodpy.orchestrator.forked_writes import (
    ForkedDay,
    ForkResult,
    ForkTask,
    stored_spans,
    write_files_into_fork,
)
from canvodpy.orchestrator.memory_budget import (
    GB,
    InputFile,
    chunk_tasks,
    largest_task,
    plan_memory,
)
from canvodpy.orchestrator.processor import (
    GroupWriteResult,
    RinexDataProcessor,
    _processing_progress,
    _warn_if_epoch_count_differs_from_name,
    _worker_init_with_run_id,
    preprocess_reference_with_hermite_aux_fanout,
    preprocess_with_hermite_aux,
)
from canvodpy.orchestrator.resources import (
    MemoryMonitor,
    deprecate_no_effect_arguments,
    run_measured,
)
from canvodpy.orchestrator.store_retry import (
    CONFLICT_TRIES,
    STORE_ERROR_TYPES,
    call_with_store_retries,
    wait_after_conflict,
)
from canvodpy.run_history import (
    ActiveRun,
    DayResult,
    FolderListing,
)

# Old-style TypeVar (not PEP 695 `def f[T](...)`): CodeQL's Python analysis
# doesn't yet understand the newer generic syntax and flags T as a
# potentially-uninitialized local inside the nested _submit() closure below.
# A module-level TypeVar is unambiguous to both type checkers and CodeQL.
T = TypeVar("T")

#: Days of a unit prepared at the same time. Each one may download its
#: orbit and clock files, and a unit has up to 31 days; more connections at
#: once than this risk being refused by the download server.
PREPARE_THREADS = 4

# A day prepared in Phase 1: its processor, file tasks and files per receiver.
_PreparedDate = tuple[RinexDataProcessor, list[tuple], list[tuple[str, list[Path]]]]


def _windowed_completions(  # noqa: UP047 -- see TypeVar comment above
    submit: Callable[[T], Future], tasks: Sequence[T], window: int
) -> Generator[tuple[T, Future]]:
    """Submit ``tasks`` keeping at most ``window`` futures in flight.

    Seeds ``window`` tasks, then on each completion submits one more from
    the backlog before yielding ``(task, future)``. Unlike submitting the
    whole batch upfront and draining via ``as_completed()``, this bounds
    how many workers can be concurrently active while a caller is busy
    handling a completed result (e.g. writing to Icechunk) -- a full-batch
    submission let the write path race a still-fully-loaded worker pool.

    Never calls ``future.result()`` itself -- the caller owns exception
    handling. Each future is popped from the in-flight mapping before being
    yielded, so a consumed future's retained result isn't held here.

    If ``submit`` itself raises ``BrokenProcessPool`` (e.g. a worker was
    OOM-killed), that used to only ever surface via a pre-submitted
    future's ``.result()`` -- submission all happened upfront, before any
    worker had a chance to die. Submitting mid-stream here means a
    ``submit()`` call can now hit an already-broken pool directly. Once
    that happens, stop calling ``submit`` (it would just keep failing) and
    synthesize an already-failed future for every remaining task instead,
    so the caller's existing per-task ``except BrokenProcessPool`` handling
    (`_process_multi_day_batches`) still sees one exception per task, not
    one uncaught exception that kills the whole generator.
    """
    in_flight: dict[Future, T] = {}
    idx = 0
    pool_broken: BrokenProcessPool | None = None

    def _submit(task: T) -> Future:
        nonlocal pool_broken
        if pool_broken is not None:
            fut: Future = Future()
            fut.set_exception(pool_broken)
            return fut
        try:
            return submit(task)
        except BrokenProcessPool as exc:
            pool_broken = exc
            fut = Future()
            fut.set_exception(exc)
            return fut

    try:
        while idx < min(window, len(tasks)):
            in_flight[_submit(tasks[idx])] = tasks[idx]
            idx += 1
        while in_flight:
            done, _ = wait(list(in_flight), return_when=FIRST_COMPLETED)
            for fut in done:
                task = in_flight.pop(fut)
                if idx < len(tasks):
                    in_flight[_submit(tasks[idx])] = tasks[idx]
                    idx += 1
                yield task, fut
    finally:
        # A caller that stops early (a run told to stop) leaves the tasks
        # not yet started; the running ones finish and are dropped.
        for fut in in_flight:
            fut.cancel()


def _run_ahead(  # noqa: UP047 -- see TypeVar comment above
    items: Callable[[threading.Event], Generator[T]], ahead: int, name: str
) -> Generator[T]:
    """Iterate ``items(stop)`` in a thread of its own, ``ahead`` items ahead.

    The caller works on an item while the thread makes the next ones; the
    thread waits while ``ahead`` items wait for the caller. An error in the
    thread is raised here, after the items made before it. When the caller
    stops early (an error, or closing this generator), ``stop`` is set and
    this waits for the thread, which finishes the commit it is in and makes
    no more items.
    """
    stop = threading.Event()
    waiting: queue.Queue[tuple[str, object]] = queue.Queue(maxsize=max(1, ahead))

    def put(kind: str, payload: object) -> bool:
        while not stop.is_set():
            try:
                waiting.put((kind, payload), timeout=0.1)
            except queue.Full:
                continue
            return True
        return False

    def produce() -> None:
        # Every error reaches the caller, which would otherwise wait forever.
        try:
            made = items(stop)
            try:
                for item in made:
                    if not put("item", item):
                        return
            finally:
                made.close()
            put("done", None)
        except BaseException as exc:  # handed to the caller, raised there
            put("error", exc)

    # The thread runs in a copy of this context, so its log events carry
    # the run ID like those of the caller.
    thread = threading.Thread(
        target=contextvars.copy_context().run, args=(produce,), name=name
    )
    thread.start()
    try:
        while True:
            kind, payload = waiting.get()
            if kind == "done":
                return
            if kind == "error":
                raise cast("BaseException", payload)
            yield cast("T", payload)
    finally:
        stop.set()
        thread.join()


@dataclass(frozen=True)
class _ForkJob:
    """A task of a forked day: write its files into its fork (ADR 0016)."""

    task: ForkTask
    fork: ForkSession


@dataclass
class _UnitDay:
    """A forked day of a unit: its processor, plan, tasks and fork results."""

    processor: RinexDataProcessor
    planned: ForkedDay
    task_descriptors: Sequence[tuple]
    results: list[ForkResult]


def _input_bytes(files: Iterable[Path | str]) -> int:
    """The size of a task's input files on disk (0 for a missing file)."""
    total = 0
    for f in files:
        try:
            total += Path(f).stat().st_size
        except OSError:
            continue
    return total


def _round_robin[I](items: Sequence[I], key: Callable[[I], Hashable]) -> list[I]:
    """Reorder *items* round-robin across the values of *key*."""
    by_key: dict[Hashable, list[I]] = {}
    for item in items:
        by_key.setdefault(key(item), []).append(item)
    return [
        item
        for row in zip_longest(*by_key.values())
        for item in row
        if item is not None
    ]


def _interleave_by_receiver(task_descriptors: list[tuple]) -> list[tuple]:
    """Reorder one date's task descriptors round-robin across receivers.

    ``prepare_batch_tasks`` builds descriptors receiver-major, file-minor
    (all of receiver A's files, then all of receiver B's). Handed straight
    to ``_windowed_completions``, a receiver's daily file count (e.g. 96 at
    15-min cadence) typically exceeds ``window``, so the window stays
    saturated on one receiver until its group nearly drains before the next
    receiver's tasks even enter it -- groups then complete in near-strict
    submission order instead of interleaved.
    Round-robining here means the window always spans multiple receivers'
    groups regardless of group size; uneven group sizes just mean the
    shorter receiver's tail drops out of rotation first, not an error.
    """
    return _round_robin(task_descriptors, lambda task_args: task_args[4])


def _build_ordered_tasks(
    ordered_date_keys: Sequence[str],
    task_descriptors_by_date: dict[str, list[tuple]],
    forked_days: dict[str, ForkedDay] | None = None,
) -> list[tuple[str, tuple | _ForkJob]]:
    """Flatten per-date task descriptors in ``ordered_date_keys`` order.

    Phase 1 prepares dates concurrently and collects results via
    ``as_completed()``, whose order is completion order, not submission
    order -- inserting straight into the flat task list from there let
    whichever date's prep happened to finish first jump ahead of
    chronologically-earlier dates, scrambling the write/dashboard order.
    Iterating ``ordered_date_keys``
    (the original, already-chronological batch list) instead restores
    that order regardless of prep completion order. Each date's own
    tasks are further round-robined across receivers via
    ``_interleave_by_receiver``. A date missing from
    ``task_descriptors_by_date`` (failed/skipped Phase 1 prep) is
    silently omitted, matching the previous behavior. A date in
    ``forked_days`` gets its fork jobs instead of its file tasks,
    round-robined across their store groups.
    """
    all_tasks: list[tuple[str, tuple | _ForkJob]] = []
    for date_key in ordered_date_keys:
        planned = (forked_days or {}).get(date_key)
        if planned is not None:
            jobs = [_ForkJob(task, fork) for task, fork in planned.tasks]
            for job in _round_robin(jobs, lambda job: job.task.groups):
                all_tasks.append((date_key, job))
            continue
        task_descriptors = task_descriptors_by_date.get(date_key)
        if task_descriptors is None:
            continue
        for task_args in _interleave_by_receiver(task_descriptors):
            all_tasks.append((date_key, task_args))
    return all_tasks


class PipelineOrchestrator:
    """Orchestrate RINEX processing pipeline for all receiver pairs at a site.

    Processes each unique receiver once per day, regardless of how many
    pairs it's involved in.

    Parameters
    ----------
    site : GnssResearchSite
        Research site configuration
    n_max_workers : int | None
        Most parallel workers. ``None`` means the number of cores
        (``os.cpu_count()``). Fewer workers run if they do not fit in the
        memory budget (:mod:`canvodpy.orchestrator.memory_budget`).
    dry_run : bool
        If True, only simulate processing without executing
    max_memory_gb : float | None
        Memory budget of the run in GB; ``None`` means the memory available
        when the run starts. The workers and the days per unit are sized to
        fit it before the first file is read (ADR 0021).
    threads_per_worker : int | None
        Threads per worker process (used to cap BLAS thread env vars).
        None defaults to 1.
    config : CanvodConfig
        The settings of this run, for example from
        ``canvod.config.load_config()``.
    on_group_written : Callable[[str], None] | None
        Called with the receiver-group name (e.g. ``"canopy_01"``,
        ``"reference_01_canopy_02"``) each time a group's data for one day
        finishes writing to Icechunk. Lets a caller drive its own progress
        display (e.g. the CLI's per-site/receiver rows) without this class
        owning any display itself — two independently-created Rich ``Live``
        instances on the same terminal corrupt each other's output, so
        display ownership belongs entirely to the caller. Default None
        (no-op) for standalone/programmatic use.
    run : ActiveRun | None
        The run recorded in the run history (``Pipeline`` starts it): the
        orchestrator records the receiver-days it plans and finishes.
        ``None``: nothing is recorded.
    on_discovery_start : Callable[[str, Path], None] | None
        Called with the receiver name and its data folder when the run starts
        finding that receiver's files, so the CLI can say what it is doing.
        Default None (no-op) for standalone/programmatic use.
    on_discovery_end : Callable[[str, int, int, float], None] | None
        Called with the receiver name, the number of files found, the number
        of days and the elapsed seconds when the run has found them. Default
        None (no-op) for standalone/programmatic use.
    on_new_files : Callable[[list[tuple[str, str]]], None] | None
        With ``new_files_only``, called with the ``(YYYYDOY, receiver)``
        pairs that have a file the GNSS store doesn't hold, before they are
        processed. Default None (no-op).
    on_incomplete_day : Callable[[str, str, int, int], None] | None
        Called with ``(receiver, YYYYDOY, files_found, files_expected)`` for
        each receiver-day to process with missing files
        (:meth:`_warn_incomplete_days`). Default None (no-op).
    on_days_without_vod : Callable[[str, list[str]], None] | None
        Called with a receiver and the days in the range on which it has no
        files while its pair has (:meth:`_warn_days_without_vod`). Default
        None (no-op).

    """

    @deprecate_no_effect_arguments
    @deprecated_argument(
        "days_per_batch",
        "The 'days_per_batch' argument of PipelineOrchestrator() is left over "
        "from development and will be removed with the next major version. A "
        "run derives its days per unit from the memory budget; until then the "
        "argument caps them. Remove the argument.",
    )
    def __init__(
        self,
        site: GnssResearchSite,
        n_max_workers: int | None = None,
        dry_run: bool = False,
        days_per_batch: int | None = None,
        max_memory_gb: float | None = None,
        cpu_affinity: list[int] | None = None,
        nice_priority: int | None = None,
        threads_per_worker: int | None = None,
        on_group_written: Callable[[str], None] | None = None,
        on_discovery_start: Callable[[str, Path], None] | None = None,
        on_discovery_end: Callable[[str, int, int, float], None] | None = None,
        on_new_files: Callable[[list[tuple[str, str]]], None] | None = None,
        on_incomplete_day: Callable[[str, str, int, int], None] | None = None,
        on_days_without_vod: Callable[[str, list[str]], None] | None = None,
        config: CanvodConfig | None = None,
        run: ActiveRun | None = None,
    ) -> None:
        if config is None:
            warnings.warn(
                "Creating PipelineOrchestrator without config= is left over "
                "from development and will be removed with the next major "
                "version. Pass config=canvod.config.load_config() instead.",
                FutureWarning,
                stacklevel=2,
            )
            config = load_config()
        self._config = config
        self.site = site
        self._on_group_written = on_group_written
        self._on_discovery_start = on_discovery_start
        self._on_discovery_end = on_discovery_end
        self._on_new_files = on_new_files
        self._on_incomplete_day = on_incomplete_day
        self._on_days_without_vod = on_days_without_vod
        self._days_without_pair: dict[str, set[str]] = {}
        self._run = run
        self._logger = structlog.get_logger(__name__).bind(site=site.site_name)
        # The log location comes from the configuration of this run.
        ensure_file_logging()
        # A new run sees files added since the previous one. The files are
        # found once the days to process are known (_find_files).
        clear_discovery_cache()
        # A run started from Python gets a run_id like one of `canvodpy run`
        # (which sets its own first); close() removes it again.
        self._run_id_token = (
            set_run_id(new_run_id(site.site_name)) if get_run_id() is None else None
        )

        self.n_max_workers = n_max_workers
        self.max_memory_gb = max_memory_gb
        # Set by _size_to_memory when a run starts.
        self._workers: int | None = None
        self.dry_run = dry_run
        # The deprecated cap on the days per unit, from the argument or the
        # settings; None: the memory budget alone sets them (ADR 0021).
        self._days_per_batch_cap = (
            days_per_batch
            if days_per_batch is not None
            else config.processing.params.days_per_batch
        )
        # Set by _size_to_memory when a run starts.
        self.unit_days = 1
        self._threads_per_worker = threads_per_worker
        self._memory_monitor = MemoryMonitor()

        if n_max_workers is not None:
            effective_workers: int | None = min(
                n_max_workers, os.cpu_count() or n_max_workers
            )
            self._logger.info(
                "resource_mode_manual",
                n_workers=effective_workers,
                threads_per_worker=threads_per_worker,
            )
        else:
            effective_workers = None
            self._logger.info(
                "resource_mode_auto",
                detected_cores=os.cpu_count(),
                threads_per_worker=threads_per_worker,
            )

        self._logger.info(
            "pipeline_initialized",
            site=site.site_name,
            analysis_pairs=len(site.active_vod_analyses),
            n_max_workers=n_max_workers,
            dry_run=dry_run,
            days_per_batch_cap=self._days_per_batch_cap,
        )

    def close(self) -> None:
        """End the pipeline and remove the run_id it set, if any.

        loky's reusable executor is shared and left running.
        """
        self._logger.info("pipeline_orchestrator_closed")
        if self._run_id_token is not None:
            reset_run_id(self._run_id_token)
            self._run_id_token = None

    def __enter__(self) -> PipelineOrchestrator:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _find_files(self, start: str | None, end: str | None) -> None:
        """Find the files of every receiver for the days to process, and report it.

        Lists the folders that hold a day from *start* to *end* (``YYYYDOY``,
        inclusive, ``None`` open), folders without data files and folders
        not in the file index; the others come from the index (ADR 0020).
        ``check_receivers`` then reads a no-recipe receiver's identity from
        the scan, and ``_receiver_days`` reads the same scan when the run
        schedules a receiver's days; the scan is cached, so both get it for
        free. On a network drive the listing is the slowest quiet part of a
        run, so this says, per receiver, what the run is finding.
        """
        site_config = self.site._site_config
        # A receiver with a naming recipe needs the optional canvod-filemap
        # extra; fail before scanning with the same message check_receivers
        # would raise, so a run reports the missing extra the same way.
        recipe_receivers = [
            name for name, cfg in site_config.receivers.items() if cfg.recipe
        ]
        require_filemap(recipe_receivers)
        for receiver_name, cfg in site_config.receivers.items():
            reader_format = None if cfg.reader_format == "auto" else cfg.reader_format
            directory = site_config.get_base_path() / cfg.directory
            recipe = recipe_file(self.site.site_name, cfg.recipe)
            if self._on_discovery_start is not None:
                self._on_discovery_start(receiver_name, directory)
            t_discovery = _time.perf_counter()
            scan = scan_directory(
                directory,
                recipe,
                file_index=self._file_index(directory, recipe),
                days=(start, end),
            )
            if self._run is not None:
                self._run.save_file_index(directory, recipe, scan.listings)
            self._logger.info(
                "files_found",
                receiver=receiver_name,
                folders_listed=len(scan.listings) - scan.folders_from_index,
                folders_from_index=scan.folders_from_index,
            )
            days = receiver_days(receiver_name, directory, reader_format, recipe)
            unprocessed_files(directory, reader_format, recipe)
            dt_discovery = _time.perf_counter() - t_discovery
            if self._on_discovery_end is not None:
                n_files = sum(len(discover_files(day, reader_format)) for day in days)
                self._on_discovery_end(receiver_name, n_files, len(days), dt_discovery)
        check_receivers(
            self.site.receivers,
            site_config.get_base_path(),
            self.site.site_name,
        )

    def _file_index(
        self, directory: Path, recipe: Path | None
    ) -> dict[str, FolderListing] | None:
        """The receiver directory's file index from the run history, if any.

        A run reads it from its own run history; a dry run reads the run
        history of the log folder without writing to it, so it finds the
        files a run would find.
        """
        if self._run is not None:
            return self._run.history.file_index(directory, recipe)
        return saved_file_index(self._config, directory, recipe)

    def _receiver_days(self, receiver_name: str) -> dict[str, ReceiverDay]:
        """Days with files to process for one receiver, keyed by ``YYYYDOY``.

        Uses the run's file discovery (recipe, otherwise canonical names), so
        a day is scheduled only if files would actually be read for it.
        Files the run never reads are reported in one warning per receiver,
        and the run continues with the others.
        """
        site_config = self.site._site_config
        cfg = site_config.receivers[receiver_name]
        reader_format = None if cfg.reader_format == "auto" else cfg.reader_format
        directory = site_config.get_base_path() / cfg.directory
        recipe = recipe_file(self.site.site_name, cfg.recipe)
        days = receiver_days(receiver_name, directory, reader_format, recipe)
        skipped = unprocessed_files(directory, reader_format, recipe)
        from canvodpy.orchestrator.data_check import group_by_file_type

        compressed = [p for p in skipped if is_compressed(p)]
        skipped = [p for p in skipped if not is_compressed(p)]
        if compressed:
            self._logger.warning(
                "compressed_files_not_processed",
                receiver=receiver_name,
                directory=str(directory),
                n_files=len(compressed),
                by_file_type={
                    kind: f"{count} (e.g. {example.name})"
                    for kind, count, example in group_by_file_type(compressed)
                },
                hint=(
                    "canVODpy does not decompress yet. Decompress these files "
                    "first (gzip/zip, and crx2rnx for Hatanaka-compressed "
                    "RINEX)."
                ),
            )
        if skipped:
            self._logger.warning(
                "files_not_processed",
                receiver=receiver_name,
                directory=str(directory),
                n_files=len(skipped),
                by_file_type={
                    kind: f"{count} (e.g. {example.name})"
                    for kind, count, example in group_by_file_type(skipped)
                },
                hint=(
                    "Neither the naming recipe nor the canVOD naming convention "
                    "recognizes these files, or the receiver's reader_format "
                    "does not read them. Run 'canvodpy config validate' for "
                    "details."
                ),
            )
        return {day.yyyydoy: day for day in days}

    @staticmethod
    def _detect_reader_format(day: ReceiverDay) -> str:
        """Detect the reader format of a receiver configured as ``auto``.

        Returns
        -------
        str
            ``"sbf"`` if all files a run would process for ``day`` are SBF,
            otherwise ``"rinex3"``.
        """
        return detect_reader_format(discover_files(day))

    def _group_by_date_and_receiver(
        self, start: str | None = None, end: str | None = None
    ) -> dict[str, dict[str, tuple[ReceiverDay, str, ReceiverDay | None, str]]]:
        """Group receivers by date, expanding references per paired canopy.

        Finds the files first (:meth:`_find_files`): the folders of the days
        from *start* to *end* are listed, the others come from the file
        index, so the days outside the range may miss files added since the
        index was saved. Callers keep only the days in the range.

        A date is scheduled for an analysis when both its canopy and its
        reference receiver have files for that day (see
        :mod:`canvodpy.orchestrator.discovery`). Canopy receivers are
        deduplicated (processed once with own position). Reference receivers
        are expanded: one entry per paired canopy, stored as
        ``{ref_name}_{canopy_name}``, with the canopy's day as position
        source.

        Returns
        -------
        dict[str, dict[str, tuple[ReceiverDay, str, ReceiverDay | None, str]]]
            {date: {store_group_name: (day, receiver_type, position_day, reader_format)}}

        """
        self._find_files(start, end)
        grouped: dict[
            str, dict[str, tuple[ReceiverDay, str, ReceiverDay | None, str]]
        ] = defaultdict(dict)
        site_config = self.site._site_config

        analyses = [
            cfg.model_dump() if hasattr(cfg, "model_dump") else cfg
            for cfg in self.site.vod_analyses.values()
        ]
        days_of: dict[str, dict[str, ReceiverDay]] = {}
        for analysis in analyses:
            for name in (analysis["canopy_receiver"], analysis["reference_receiver"]):
                if name not in days_of:
                    days_of[name] = self._receiver_days(name)

        # The days on which one receiver of a pair has files and the other
        # none: they are not processed (_warn_days_without_vod).
        self._days_without_pair = defaultdict(set)
        for analysis in analyses:
            canopy_rx = analysis["canopy_receiver"]
            ref_name = analysis["reference_receiver"]
            canopy_days, ref_days = set(days_of[canopy_rx]), set(days_of[ref_name])
            self._days_without_pair[ref_name] |= canopy_days - ref_days
            self._days_without_pair[canopy_rx] |= ref_days - canopy_days
            common = sorted(canopy_days & ref_days)
            for date_key in common:
                canopy_day = days_of[canopy_rx][date_key]
                reference_day = days_of[ref_name][date_key]

                # Add canopy receiver if not already present (uses own position)
                if canopy_rx not in grouped[date_key]:
                    canopy_cfg = site_config.receivers.get(canopy_rx)
                    canopy_fmt = canopy_cfg.reader_format if canopy_cfg else "auto"
                    if canopy_fmt == "auto":
                        canopy_fmt = self._detect_reader_format(canopy_day)
                    grouped[date_key][canopy_rx] = (
                        canopy_day,
                        "canopy",
                        None,
                        canopy_fmt,
                    )

                # Expand reference receiver per paired canopy
                ref_cfg = site_config.receivers.get(ref_name)
                if not (ref_cfg and ref_cfg.type == "reference"):
                    continue
                ref_fmt = ref_cfg.reader_format
                if ref_fmt == "auto":
                    ref_fmt = self._detect_reader_format(reference_day)
                mixed = mixed_format_error(
                    canopy_rx, grouped[date_key][canopy_rx][3], ref_name, ref_fmt
                )
                if mixed:
                    raise ValueError(f"{date_key}: {mixed}")
                for canopy_name in site_config.resolve_paired_canopies(ref_name):
                    store_group = reference_store_group(ref_name, canopy_name)
                    if store_group in grouped[date_key]:
                        continue
                    # The canopy's files of the same day give the position
                    canopy_cfg = site_config.receivers.get(canopy_name)
                    canopy_position_day = (
                        ReceiverDay(
                            canopy_name,
                            site_config.get_base_path() / canopy_cfg.directory,
                            date_key,
                            recipe_file(self.site.site_name, canopy_cfg.recipe),
                        )
                        if canopy_cfg
                        else None
                    )
                    grouped[date_key][store_group] = (
                        reference_day,
                        "reference",
                        canopy_position_day,
                        ref_fmt,
                    )

        return grouped

    def preview_processing_plan(
        self,
        start: str | None = None,
        end: str | None = None,
        *,
        new_files_only: bool = False,
    ) -> dict:
        """Preview what would be processed without executing.

        Parameters
        ----------
        start : str, optional
            YYYYDOY string to start from (inclusive). ``None`` previews
            every available date, matching legacy behavior.
        end : str, optional
            YYYYDOY string to end at (inclusive). ``None`` previews every
            available date, matching legacy behavior.
        new_files_only : bool, default False
            Only the dates on which a receiver has a file the GNSS store
            doesn't hold (:meth:`_dates_with_new_files`).

        Returns
        -------
        dict
            Summary of dates, receivers, and files to process

        """
        grouped = self._group_by_date_and_receiver(start, end)
        dates = self._filter_dates(grouped, start, end)
        if new_files_only:
            dates = self._dates_with_new_files(dates)
        self._warn_days_without_vod(start, end)
        self._warn_incomplete_days(dates)

        plan = {
            "site": self.site.site_name,
            "dates": [],
            "total_receivers": 0,
            "total_files": 0,
        }

        for date_key, receivers in dates:
            date_info = {"date": date_key, "receivers": []}

            for receiver_name, (day, receiver_type, _pos_day, fmt) in sorted(
                receivers.items()
            ):
                # Same selection as the real run (processor._get_rinex_files).
                files = discover_files(day, fmt)

                receiver_info = {
                    "name": receiver_name,
                    "type": receiver_type,
                    "files": len(files),
                    "dir": str(day.directory),
                }

                date_info["receivers"].append(receiver_info)
                plan["total_files"] += len(files)

            plan["dates"].append(date_info)
            plan["total_receivers"] += len(receivers)

        return plan

    def print_preview(
        self,
        start: str | None = None,
        end: str | None = None,
        *,
        new_files_only: bool = False,
    ) -> None:
        """Print a formatted preview of the processing plan."""
        plan = self.preview_processing_plan(start, end, new_files_only=new_files_only)

        print(f"\n{'=' * 70}")
        print(f"PROCESSING PLAN FOR SITE: {plan['site']}")
        print(f"{'=' * 70}")
        print(f"Total unique receivers to process: {plan['total_receivers']}")
        print(f"Total RINEX files: {plan['total_files']}")
        print(f"{'=' * 70}\n")

        for date_info in plan["dates"]:
            print(f"Date: {date_info['date']}")
            for receiver_info in date_info["receivers"]:
                print(
                    f"  {receiver_info['name']} ({receiver_info['type']}): "
                    f"{receiver_info['files']} files"
                )
                print(f"    {receiver_info['dir']}")
            print()

    def _filter_dates(
        self,
        grouped: dict[str, dict[str, tuple[ReceiverDay, str, ReceiverDay | None, str]]],
        start_from: str | None,
        end_at: str | None,
    ) -> list[tuple[str, dict[str, tuple[ReceiverDay, str, ReceiverDay | None, str]]]]:
        """Filter and sort dates within the requested range.

        Parameters
        ----------
        grouped : dict
            Date-grouped receiver configs from ``_group_by_date_and_receiver()``.
        start_from : str | None
            YYYYDOY string to start from (inclusive).
        end_at : str | None
            YYYYDOY string to end at (inclusive).

        Returns
        -------
        list[tuple[str, dict]]
            Filtered and sorted ``(date_key, receivers)`` pairs.

        """
        filtered = []
        before = [d for d in sorted(grouped) if start_from and d < start_from]
        if before:
            self._logger.info(
                "dates_skipped_before_range",
                n_dates=len(before),
                first=before[0],
                last=before[-1],
                start_from=start_from,
            )
        for date_key, receivers in sorted(grouped.items()):
            if start_from and date_key < start_from:
                continue
            if end_at and date_key > end_at:
                self._logger.info(
                    "date_range_complete",
                    date=date_key,
                    end_at=end_at,
                )
                break
            filtered.append((date_key, receivers))
        return filtered

    def _dates_with_new_files(
        self,
        dates: list[
            tuple[str, dict[str, tuple[ReceiverDay, str, ReceiverDay | None, str]]]
        ],
    ) -> list[tuple[str, dict[str, tuple[ReceiverDay, str, ReceiverDay | None, str]]]]:
        """The dates on which a receiver has a file the GNSS store doesn't hold.

        A file counts as held when its canonical name is in the log book of
        its store group, so finding new files reads no file. A date is kept
        with all its receivers: the VOD of the day needs the data of both,
        and the files already held are not written again. Reports the
        ``(YYYYDOY, receiver)`` pairs with new files through
        ``on_new_files`` (#386).
        """
        held = self._held_file_names({group for _, groups in dates for group in groups})
        kept = []
        new_receiver_days: list[tuple[str, str]] = []
        for date_key, groups in dates:
            receivers = sorted(
                {
                    day.receiver
                    for group, (day, _type, _position, fmt) in groups.items()
                    if {f.canonical_name for f in discover_files(day, fmt)}
                    - held.get(group, set())
                }
            )
            if receivers:
                kept.append((date_key, groups))
                new_receiver_days.extend((date_key, r) for r in receivers)
        self._logger.info(
            "receiver_days_with_new_files",
            n_receiver_days=len(new_receiver_days),
            n_dates=len(kept),
        )
        if self._on_new_files is not None:
            self._on_new_files(new_receiver_days)
        return kept

    def _warn_incomplete_days(
        self,
        dates: list[
            tuple[str, dict[str, tuple[ReceiverDay, str, ReceiverDay | None, str]]]
        ],
    ) -> None:
        """Warn of each receiver-day to process that misses files (#387).

        A receiver-day is complete with as many files as its file length
        gives for a whole day (:func:`files_per_day`). Today is not checked:
        its files are still arriving. Each warning is logged, so it reaches
        the run history, and passed to ``on_incomplete_day``.
        """
        today = datetime.now().strftime("%Y%j")
        for date_key, groups in dates:
            if date_key == today:
                continue
            checked: set[str] = set()
            for day, _type, _position, fmt in groups.values():
                if day.receiver in checked:
                    continue
                checked.add(day.receiver)
                files = discover_files(day, fmt)
                expected = files_per_day(files)
                if len(files) >= expected:
                    continue
                self._logger.warning(
                    "receiver_day_incomplete",
                    receiver=day.receiver,
                    date=date_key,
                    files_found=len(files),
                    files_expected=expected,
                    summary=(
                        f"{day.receiver} has {len(files)} of {expected} files "
                        f"on {date_key}"
                    ),
                )
                if self._on_incomplete_day is not None:
                    self._on_incomplete_day(
                        day.receiver, date_key, len(files), expected
                    )

    def _warn_days_without_vod(self, start: str | None, end: str | None) -> None:
        """Warn of the days in the range that one receiver of a pair lacks.

        Such a day is not processed, so it gets no VOD (#387). One warning
        per receiver, logged and passed to ``on_days_without_vod``.
        """
        for receiver, days in sorted(self._days_without_pair.items()):
            in_range = sorted(
                d for d in days if (not start or d >= start) and (not end or d <= end)
            )
            if not in_range:
                continue
            self._logger.warning(
                "days_without_vod",
                receiver=receiver,
                n_days=len(in_range),
                first=in_range[0],
                last=in_range[-1],
                summary=(
                    f"no VOD on {len(in_range)} day(s) from {in_range[0]} to "
                    f"{in_range[-1]}: {receiver} has no files"
                ),
            )
            if self._on_days_without_vod is not None:
                self._on_days_without_vod(receiver, in_range)

    def _split_stored_dates(
        self,
        dates: list[
            tuple[str, dict[str, tuple[ReceiverDay, str, ReceiverDay | None, str]]]
        ],
    ) -> tuple[
        list[tuple[str, dict[str, tuple[ReceiverDay, str, ReceiverDay | None, str]]]],
        list[tuple[str, dict[str, tuple[ReceiverDay, str, ReceiverDay | None, str]]]],
    ]:
        """Split off the dates whose files every group of theirs holds.

        A file is held when its hash is in a log-book row of the group that
        wrote data, the test a task applies before writing it
        (``gnss_store_strategy: skip``). Hashing a file reads its bytes but
        does not parse it, so a stored date costs neither auxiliary data
        nor reading. With ``gnss_store_strategy: overwrite`` no date is
        split off.

        Returns
        -------
        tuple
            The stored dates and the dates to process, each in date order.
        """
        storage = self._config.processing.storage
        if storage.gnss_store_strategy != "skip" or not store_exists(
            self.site.gnss_store_path
        ):
            return [], dates
        t_start = _time.monotonic()
        store = self.site.gnss_store
        held = {
            group: frozenset(
                h
                for _, h, _, _ in stored_spans(store.load_metadata_for_dedup(group))
                if h
            )
            for group in {group for _, groups in dates for group in groups}
        }
        files = {
            (date_key, group): [f.path for f in discover_files(day, fmt)]
            for date_key, groups in dates
            for group, (day, _type, _position, fmt) in groups.items()
        }
        paths = sorted({path for group_files in files.values() for path in group_files})
        with ThreadPoolExecutor(
            max_workers=min(8, os.cpu_count() or 1),
            thread_name_prefix="canvodpy-hash",
        ) as pool:
            hashes = dict(zip(paths, pool.map(file_hash, paths), strict=True))
        stored, rest = [], []
        for date_key, groups in dates:
            group_files = [(g, files[date_key, g]) for g in groups]
            # A group without files on the date is not held: its day is
            # processed, so the run reports it as it does today.
            if all(paths_of for _, paths_of in group_files) and all(
                hashes[path] in held[group]
                for group, paths_of in group_files
                for path in paths_of
            ):
                stored.append((date_key, groups))
            else:
                rest.append((date_key, groups))
        self._logger.info(
            "stored_days_skipped",
            days=[date_key for date_key, _ in stored],
            files_hashed=len(paths),
            seconds=round(_time.monotonic() - t_start, 2),
        )
        return stored, rest

    def _held_file_names(self, groups: set[str]) -> dict[str, set[str]]:
        """The canonical names in each group's log book; none without a store."""
        if not store_exists(self.site.gnss_store_path):
            return {}
        store = self.site.gnss_store
        held = {}
        for group in groups:
            rows = stored_spans(store.load_metadata_for_dedup(group))
            held[group] = {name for name, *_ in rows if name}
        return held

    @staticmethod
    def _build_receiver_configs(
        receivers: dict[str, tuple[ReceiverDay, str, ReceiverDay | None, str]],
    ) -> list[tuple[str, str, ReceiverDay, ReceiverDay | None, str]]:
        """Build sorted receiver config tuples from the receivers dict.

        Parameters
        ----------
        receivers : dict
            ``{store_group: (data_dir, receiver_type, position_data_dir, reader_format)}``.

        Returns
        -------
        list[tuple[str, str, ReceiverDay, ReceiverDay | None, str]]
            ``(receiver_name, receiver_type, data_dir, position_data_dir, reader_format)`` tuples.

        """
        return [
            (name, rtype, ddir, pdir, fmt)
            for name, (ddir, rtype, pdir, fmt) in sorted(receivers.items())
        ]

    def _create_processor_for_date(
        self,
        date_key: str,
        receivers: dict[str, tuple[ReceiverDay, str, ReceiverDay | None, str]],
    ) -> RinexDataProcessor:
        """Create a RinexDataProcessor for a single DOY.

        Parameters
        ----------
        date_key : str
            YYYYDOY string.
        receivers : dict
            ``{store_group: (data_dir, receiver_type, position_data_dir, reader_format)}``.

        Returns
        -------
        RinexDataProcessor

        """
        receiver_configs = self._build_receiver_configs(receivers)
        first_data_dir = receiver_configs[0][2]
        matched_dirs = MatchedDirs(
            canopy_data_dir=first_data_dir.directory,
            reference_data_dir=first_data_dir.directory,
            yyyydoy=YYYYDOY.from_str(date_key),
        )
        return RinexDataProcessor(
            matched_data_dirs=matched_dirs,
            site=self.site,
            n_max_workers=self.n_max_workers,
            config=self._config,
        )

    def _prepare_single_date(
        self,
        date_key: str,
        receivers: dict[str, tuple[ReceiverDay, str, ReceiverDay | None, str]],
        keep_vars: list[str] | None,
    ) -> _PreparedDate | None:
        """Prepare one DOY for flat loky submission (Phase 1 helper).

        Thread-safe: each date downloads different SP3/CLK files,
        aux Zarr paths are date-specific, and position computation reads
        independent RINEX headers.

        Returns
        -------
        tuple or None
            ``(processor, task_descriptors, receiver_file_map)`` or None
            if no RINEX files found.

        Raises
        ------
        RuntimeError
            If auxiliary data download fails.

        """
        processor = self._create_processor_for_date(date_key, receivers)
        receiver_configs = self._build_receiver_configs(receivers)
        task_descriptors, receiver_file_map = processor.prepare_batch_tasks(
            keep_vars, receiver_configs
        )
        if not task_descriptors:
            return None
        return processor, task_descriptors, receiver_file_map

    def _grow_day_blocks(
        self,
        doy_contexts: dict[
            str, tuple[RinexDataProcessor, list[tuple[str, list[Path]]]]
        ],
        batch_index: int,
    ) -> None:
        """Grow the batch's day blocks in one small commit, before reading.

        Only the days whose Phase 1 succeeded (``doy_contexts``) get a
        block, so days whose orbit products are not out yet get none. A
        block of a day whose files fail later stays as fill and is reused
        when the day is run again (ADR 0016).
        """
        days: dict[str, dict[np.datetime64, float]] = defaultdict(dict)
        for processor, receiver_file_map in doy_contexts.values():
            for group, cadences in processor.day_blocks_to_grow(
                receiver_file_map
            ).items():
                days[group].update(cadences)
        if not days:
            return
        message = _with_run_id(
            f"[v{get_version_from_pyproject()}] Day blocks for "
            f"{', '.join(sorted(doy_contexts))}"
        )
        t_start = _time.monotonic()
        snapshot_id = call_with_store_retries(
            partial(self.site.gnss_store.grow_day_blocks, days, message=message),
            logger=self._logger,
            date=",".join(sorted(doy_contexts)),
            op="grow_day_blocks",
        )
        seconds = _time.monotonic() - t_start
        record_stage_timing("day_block_growth", seconds)
        self._logger.info(
            "day_blocks_grown",
            batch_index=batch_index,
            groups=sorted(days),
            committed=snapshot_id is not None,
            seconds=round(seconds, 2),
        )

    def _prepare_in_context(
        self,
        context: contextvars.Context,
        date_key: str,
        receivers: dict[str, tuple[ReceiverDay, str, ReceiverDay | None, str]],
        keep_vars: list[str] | None,
    ) -> _PreparedDate | None:
        """:meth:`_prepare_single_date` in *context*, a copy of the caller's."""
        return cast(
            "_PreparedDate | None",
            context.run(self._prepare_single_date, date_key, receivers, keep_vars),
        )

    def _prepare_batch(
        self,
        batch: list[
            tuple[str, dict[str, tuple[ReceiverDay, str, ReceiverDay | None, str]]]
        ],
        keep_vars: list[str] | None,
        batch_index: int,
    ) -> tuple[
        dict[str, tuple[RinexDataProcessor, list[tuple[str, list[Path]]]]],
        dict[str, list[tuple]],
    ]:
        """Phase 1 of a batch: prepare its dates, one thread per date.

        Auxiliary data (SP3/CLK interpolation or cache), receiver positions
        and one task per file. Reads no store, so it runs while the batch
        before is read and written. A date whose orbit products cannot be
        downloaded is left out. A receiver-day that gets no tasks (its
        files give no receiver position, for example), or whose date fails
        otherwise, also on a second try, is recorded as failed.

        Returns
        -------
        tuple
            ``(doy_contexts, task_descriptors_by_date)``: per prepared date,
            its processor and files per receiver, and its file tasks.
        """
        t_phase1_start = _time.monotonic()
        doy_contexts: dict[
            str,
            tuple[RinexDataProcessor, list[tuple[str, list[Path]]]],
        ] = {}
        task_descriptors_by_date: dict[str, list[tuple]] = {}

        phase1_workers = min(len(batch), PREPARE_THREADS)
        batch_receivers_by_date = dict(batch)
        with ThreadPoolExecutor(max_workers=phase1_workers) as tp:
            # Each thread runs in a copy of this context, so its log
            # events carry the run ID like those of the main thread.
            futures = {
                tp.submit(
                    self._prepare_in_context,
                    contextvars.copy_context(),
                    date_key,
                    receivers,
                    keep_vars,
                ): date_key
                for date_key, receivers in batch
            }
            for fut in as_completed(futures):
                date_key = futures[fut]
                try:
                    result = fut.result()
                except RuntimeError as e:
                    if "Failed to download" in str(e):
                        self._logger.warning(
                            "auxiliary_download_failed",
                            date=date_key,
                            error=str(e),
                        )
                        continue
                    raise
                except (OSError, ValueError) as e:
                    # Transient race: Zarr's internal directory listing can
                    # briefly see a concurrent thread's .DS_Store cleanup
                    # mid-scan during Phase-1 aux cache prep. Retry once
                    # synchronously before dropping the date.
                    self._logger.warning(
                        "prepare_batch_failed_retrying",
                        date=date_key,
                        error=str(e),
                    )
                    try:
                        result = self._prepare_single_date(
                            date_key,
                            batch_receivers_by_date[date_key],
                            keep_vars,
                        )
                    except (OSError, ValueError) as retry_e:
                        self._logger.error(
                            "prepare_batch_failed",
                            date=date_key,
                            error=str(retry_e),
                        )
                        self._fail_receiver_days(
                            date_key, list(batch_receivers_by_date[date_key]), retry_e
                        )
                        continue

                # A receiver with files that got no tasks (no position from
                # its files, for example) is a failed receiver-day, not a
                # day left out without a word.
                prepared = {name for name, _ in result[2]} if result else set()
                not_prepared = [
                    receiver
                    for receiver in batch_receivers_by_date[date_key]
                    if receiver not in prepared
                ]
                if not_prepared:
                    self._fail_receiver_days(
                        date_key,
                        not_prepared,
                        RuntimeError(
                            "Preparing the day gave no tasks for this receiver "
                            "(no receiver position from its files, or no files); "
                            "see the warnings before this message."
                        ),
                    )
                if result is None:
                    continue

                processor, task_descriptors, receiver_file_map = result
                doy_contexts[date_key] = (processor, receiver_file_map)
                task_descriptors_by_date[date_key] = task_descriptors

        t_phase1_end = _time.monotonic()
        self._logger.info(
            "phase1_prepare_complete",
            batch_index=batch_index,
            phase1_seconds=round(t_phase1_end - t_phase1_start, 2),
            doys_prepared=len(doy_contexts),
            total_tasks=sum(map(len, task_descriptors_by_date.values())),
        )

        return doy_contexts, task_descriptors_by_date

    def _process_multi_day_batches(
        self,
        filtered_dates: list[
            tuple[str, dict[str, tuple[ReceiverDay, str, ReceiverDay | None, str]]]
        ],
        keep_vars: list[str] | None,
        stop: threading.Event,
        *,
        read_back: bool = True,
    ) -> Generator[list[tuple[str, dict[str, xr.Dataset | None], dict[str, float]]]]:
        """Process dates in units of ``unit_days`` days (ADR 0021).

        Each unit (a batch, in the code) runs in three phases:

        1. Prepare (:meth:`_prepare_batch`), while the unit before is read
           and written. The prepared dates then get their day blocks in one
           growth commit (:meth:`_grow_day_blocks`), after the unit before
           is committed, and are planned on one session. The next unit's
           preparing starts after this growth commit, not beside it.
        2. Process the files of all dates of the unit in loky's reusable
           process pool, at most twice the worker count in flight. Each
           task of a day with its blocks writes into a fork of the unit's
           session.
        3. Commit, in a thread of this process, the forks of all days of
           the unit once all are back (:meth:`_write_forked_unit`). A day
           written in one session instead (the first day of a group) is
           written here as soon as all its files are back:
           ``processing.preprocessing`` (if set), then
           ``_append_to_icechunk``.

        A new store's first day is a unit of its own, so it creates the
        groups the next units fork from. A unit is yielded once it is
        written. :meth:`process_by_date` and :meth:`store_by_unit` run this
        in a thread of their own, so the next unit is read while the caller
        works on this one (:func:`_run_ahead`).

        Parameters
        ----------
        filtered_dates : list
            Filtered ``(date_key, receivers)`` pairs.
        keep_vars : list[str] | None
            Variables to keep in datasets.
        stop : threading.Event
            Set when the caller stops early: no file result is taken any
            more, the receiver-days being committed finish, and nothing
            more is yielded.
        read_back : bool, default True
            Read each stored receiver-day back from the store. Without it
            (a run, whose VOD phase reads the days itself), a group's
            dataset is ``None``.

        Yields
        ------
        list[tuple[str, dict[str, xr.Dataset | None], dict[str, float]]]
            Per unit with a stored day, ``(date_key, datasets, timings)``
            of each of its stored days, in date order.

        """
        batches = self._units(filtered_dates)
        total_batches = len(batches)
        self._logger.info(
            "run_units",
            unit_days=self.unit_days,
            total_dates=len(filtered_dates),
            units=total_batches,
            first_day_alone=len(batches[0]) < min(self.unit_days, len(filtered_dates)),
        )
        # Phase 1 of the next batch runs in this thread while the current
        # batch is read and written; it reads no store. Leaving the block
        # waits for a Phase 1 that is still running.
        with ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="canvodpy-phase1"
        ) as phase1_ahead:

            def prepare(index: int) -> Future:
                return phase1_ahead.submit(
                    contextvars.copy_context().run,
                    self._prepare_batch,
                    batches[index],
                    keep_vars,
                    index + 1,
                )

            prepared = prepare(0)
            for batch_idx, batch in enumerate(batches):
                if stop.is_set():
                    return
                batch_date_keys = [dk for dk, _ in batch]
                batch_start_time = _time.monotonic()

                self._logger.info(
                    "batch_started",
                    batch_index=batch_idx + 1,
                    total_batches=total_batches,
                    batch_dates=batch_date_keys,
                    batch_size=len(batch),
                )

                self._memory_monitor.log_memory_stats(
                    context=f"before_batch_{batch_idx + 1}"
                )

                doy_contexts, task_descriptors_by_date = prepared.result()

                try:
                    self._grow_day_blocks(doy_contexts, batch_idx + 1)
                except STORE_ERROR_TYPES as exc:
                    # A lost growth fails the batch's days, not the run; the
                    # next run grows and writes them.
                    self._logger.exception(
                        "day_block_growth_failed",
                        batch_index=batch_idx + 1,
                        batch_dates=batch_date_keys,
                    )
                    for date_key, (
                        _processor,
                        receiver_file_map,
                    ) in doy_contexts.items():
                        self._fail_receiver_days(
                            date_key, [name for name, _ in receiver_file_map], exc
                        )
                    continue
                finally:
                    # The next unit's Phase 1 starts after the growth commit:
                    # beside it, the commit took 15 times as long (#433).
                    if batch_idx + 1 < len(batches):
                        prepared = prepare(batch_idx + 1)

                forked_days: dict[str, ForkedDay] = {}
                unit_session = self._unit_session()
                for date_key, (processor, _receiver_file_map) in doy_contexts.items():
                    try:
                        with stage_timer("planning", date_key=date_key):
                            planned = call_with_store_retries(
                                partial(
                                    processor.plan_forked_day,
                                    task_descriptors_by_date[date_key],
                                    session=unit_session,
                                ),
                                logger=self._logger,
                                date=date_key,
                                op="plan_forked_day",
                            )
                    except STORE_ERROR_TYPES as exc:
                        self._logger.exception(
                            "forked_day_planning_failed", date=date_key
                        )
                        self._fail_receiver_days(
                            date_key, [name for name, _ in _receiver_file_map], exc
                        )
                        task_descriptors_by_date.pop(date_key)
                        continue
                    if planned is not None:
                        forked_days[date_key] = planned

                all_tasks = _build_ordered_tasks(
                    [date_key for date_key, _receivers in batch],
                    task_descriptors_by_date,
                    forked_days,
                )

                if not all_tasks:
                    self._logger.warning(
                        "batch_no_tasks",
                        batch_index=batch_idx + 1,
                        batch_dates=batch_date_keys,
                    )
                    continue

                # ── Phase 2+3: Pipelined loky processing + streaming writes ─
                #
                # Submit all tasks to loky, then write to Icechunk as soon as
                # all tasks for a (date, receiver) group complete. This frees
                # raw results immediately instead of buffering everything.

                # Build expected counts and receiver→files lookup
                expected_counts: dict[tuple[str, str], int] = {}
                receiver_files_lookup: dict[tuple[str, str], list[Path]] = {}
                reader_format_lookup: dict[tuple[str, str], str | None] = {}
                for date_key in doy_contexts:
                    if date_key in forked_days:
                        continue  # written by fork jobs and the writer thread
                    _processor, receiver_file_map = doy_contexts[date_key]
                    for receiver_name, rinex_files in receiver_file_map:
                        key = (date_key, receiver_name)
                        expected_counts[key] = len(rinex_files)
                        receiver_files_lookup[key] = rinex_files
                # Build reader_format lookup from the original receivers dict
                for date_key, receivers in batch:
                    for store_group, (_, _, _, fmt) in receivers.items():
                        reader_format_lookup[(date_key, store_group)] = fmt

                # ── Phase 2: submit all tasks ─────────────────────────────────────
                # Cap BLAS/OpenMP thread counts so workers don't each spawn
                # os.cpu_count() threads (n_workers × blas_threads = oversubscription).
                _effective_blas_threads = self._threads_per_worker or 1
                _thread_str = str(_effective_blas_threads)
                for _var in (
                    "OMP_NUM_THREADS",
                    "MKL_NUM_THREADS",
                    "OPENBLAS_NUM_THREADS",
                    "NUMEXPR_NUM_THREADS",
                    "VECLIB_MAXIMUM_THREADS",
                ):
                    if _var not in os.environ:
                        os.environ[_var] = _thread_str

                t_submit_start = _time.monotonic()
                n_wrk = self.pool_workers
                _pool = self.worker_pool()

                def _submit_fork(job: _ForkJob, *, _pool=_pool) -> Future:
                    return _pool.submit(
                        run_measured,
                        _input_bytes(ft[0] for ft in job.task.file_tasks),
                        write_files_into_fork,
                        job.fork,
                        job.task,
                    )

                def _submit_task(
                    task: tuple[str, tuple | _ForkJob],
                    *,
                    _pool=_pool,
                    _submit_fork=_submit_fork,
                ) -> Future:
                    task_args = task[1]
                    if isinstance(task_args, _ForkJob):
                        return _submit_fork(task_args)
                    # Trailing element marks a reference fan-out task (dict
                    # result, one canopy_positions arg instead of a single
                    # receiver_position/receiver_name pair) vs. the normal
                    # one-file-one-receiver shape -- see prepare_batch_tasks.
                    func = (
                        preprocess_reference_with_hermite_aux_fanout
                        if task_args[-1]
                        else preprocess_with_hermite_aux
                    )
                    return _pool.submit(
                        run_measured,
                        _input_bytes([task_args[0]]),
                        func,
                        *task_args[:-1],
                    )

                fork_results: dict[str, list[ForkResult]] = defaultdict(list)
                fork_jobs_left = sum(len(p.tasks) for p in forked_days.values())
                unit_write: Future | None = None

                # Windowed submission (~2x worker count in flight), not the whole
                # batch upfront: submitting all ~n_days*n_receivers*n_files tasks
                # before draining left the write path racing a fully-loaded pool
                # for the earliest-completing groups. Streaming-write behavior
                # (write the moment a group completes) is unchanged.
                window = max(1, 2 * n_wrk)
                t_setup_end = _time.monotonic()
                self._logger.info(
                    "phase2_windowed_scheduling_started",
                    batch_index=batch_idx + 1,
                    # Submission is now lazy -- spread across the batch by
                    # _windowed_completions, not done upfront -- so this is the
                    # total that *will* be submitted, not a completed count, and
                    # setup_seconds times pool/window setup only, not submission.
                    tasks_to_submit=len(all_tasks),
                    n_workers=n_wrk,
                    window=window,
                    setup_seconds=round(t_setup_end - t_submit_start, 4),
                )
                completion_iter = _windowed_completions(_submit_task, all_tasks, window)

                # Streaming collection: write as groups complete
                pending_results: dict[
                    tuple[str, str], list[tuple[Path, xr.Dataset]]
                ] = defaultdict(list)
                pending_aux: dict[
                    tuple[str, str], dict[Path, dict[str, xr.Dataset]]
                ] = defaultdict(dict)
                completed_counts: dict[tuple[str, str], int] = defaultdict(int)
                tasks_succeeded = 0
                tasks_failed = 0

                # Per-date accumulators for final yield
                date_datasets: dict[str, dict[str, xr.Dataset | None]] = defaultdict(
                    dict
                )
                date_timings: dict[str, dict[str, float]] = defaultdict(dict)
                groups_written: set[tuple[str, str]] = set()

                # Build file-size lookup for throughput display
                file_sizes_mb: dict[tuple[str, str], float] = {}
                for (dk, rn), files in receiver_files_lookup.items():
                    file_sizes_mb[(dk, rn)] = sum(
                        f.stat().st_size / 1_048_576 for f in files if f.exists()
                    )

                # One thread commits the unit's forked days once their fork
                # jobs are back, while this thread writes the other days.
                # Leaving the block, also by an error, waits for the commit.
                with (
                    ThreadPoolExecutor(max_workers=1) as day_writer,
                    _processing_progress(disable=True) as _progress_inner,
                ):
                    # Stub tasks on the disabled inner progress (no-ops for rendering)
                    _progress_inner.add_task(
                        f"[bold]batch {batch_idx + 1}",
                        total=len(all_tasks),
                    )

                    batch_t0 = _time.monotonic()
                    for task, fut in completion_iter:
                        if stop.is_set():
                            # The caller stopped: take no more results. A
                            # unit being committed finishes when this block
                            # is left; the files still out are dropped.
                            break
                        date_key, task_args = task
                        if isinstance(task_args, _ForkJob):
                            fork_result = self._fork_result(
                                date_key, task_args, fut, batch_idx + 1
                            )
                            if fork_result.files or not fork_result.failed:
                                tasks_succeeded += 1
                            else:
                                tasks_failed += 1
                            fork_results[date_key].append(fork_result)
                            fork_jobs_left -= 1
                            if not fork_jobs_left:
                                unit_write = day_writer.submit(
                                    contextvars.copy_context().run,
                                    self._write_forked_unit,
                                    [
                                        _UnitDay(
                                            doy_contexts[dk][0],
                                            planned,
                                            task_descriptors_by_date[dk],
                                            fork_results.pop(dk, []),
                                        )
                                        for dk, planned in forked_days.items()
                                    ],
                                    _submit_fork,
                                    batch_idx + 1,
                                )
                            continue
                        is_fanout = bool(task_args[-1])
                        lane_key = task_args[4]
                        # A reference fan-out task's pairing names are known from its
                        # submitted args (canopy_positions' keys), independent of
                        # whether the call below succeeds or fails.
                        pairing_names = (
                            list(task_args[3].keys()) if is_fanout else [lane_key]
                        )
                        group_keys = [(date_key, p) for p in pairing_names]

                        try:
                            if is_fanout:
                                fname, ds_by_pairing, aux, _sids = fut.result()
                                for pairing_name in pairing_names:
                                    ds = ds_by_pairing.get(pairing_name)
                                    if ds is None:
                                        continue
                                    pk = (date_key, pairing_name)
                                    pending_results[pk].append((fname, ds))
                                    if aux:
                                        pending_aux[pk][fname] = aux
                            else:
                                fname, ds, aux, _sids = fut.result()
                                pk = group_keys[0]
                                pending_results[pk].append((fname, ds))
                                if aux:
                                    pending_aux[pk][fname] = aux
                            tasks_succeeded += 1
                        except BrokenProcessPool:
                            tasks_failed += 1
                            self._logger.exception(
                                "worker_pool_broken",
                                date=date_key,
                                receiver=lane_key,
                                batch_index=batch_idx + 1,
                                hint="worker process likely killed by OOM or segfault",
                            )
                        except Exception:
                            tasks_failed += 1
                            self._logger.exception(
                                "task_failed",
                                date=date_key,
                                receiver=lane_key,
                                batch_index=batch_idx + 1,
                            )

                        # A fan-out task can complete multiple pairing groups at
                        # once (one per canopy sharing this reference file) --
                        # count/check/write independently for each.
                        for group_key in group_keys:
                            receiver_name = group_key[1]

                            # Count both successes and failures toward completion
                            completed_counts[group_key] += 1

                            # Check if this group is fully complete
                            if completed_counts[group_key] < expected_counts.get(
                                group_key, 0
                            ):
                                continue

                            # ── Group complete: write to Icechunk immediately ──
                            group_results = pending_results.pop(group_key, [])
                            if not group_results:
                                self._logger.warning(
                                    "receiver_all_tasks_failed",
                                    date=date_key,
                                    receiver=receiver_name,
                                    batch_index=batch_idx + 1,
                                )
                                self._finish_receiver_day(
                                    receiver_name, date_key, "failed"
                                )
                                continue

                            processor = doy_contexts[date_key][0]
                            for fname, ds in group_results:
                                _warn_if_epoch_count_differs_from_name(
                                    processor._logger,
                                    fname,
                                    processor._canonical_name(fname),
                                    ds,
                                )
                            # The receiver's `metadata` setting, then
                            # processing.preprocessing (if set) on the whole
                            # receiver-day, so time bins can span two files
                            augmented = preprocess_files(
                                [
                                    (
                                        fname,
                                        processor.site.add_receiver_metadata(
                                            ds, receiver_name
                                        ),
                                    )
                                    for fname, ds in sorted(
                                        group_results, key=lambda x: x[0].name
                                    )
                                ],
                                processor._config.processing.preprocessing,
                            )
                            rinex_files = receiver_files_lookup[group_key]
                            group_aux = pending_aux.pop(group_key, None)
                            group_fmt = reader_format_lookup.get(group_key)

                            t_write_start = _time.monotonic()
                            try:
                                skipped = call_with_store_retries(
                                    partial(
                                        processor._append_to_icechunk,
                                        augmented,
                                        receiver_name,
                                        rinex_files,
                                        aux_datasets=group_aux or None,
                                        reader_format=group_fmt,
                                    ),
                                    logger=self._logger,
                                    date=date_key,
                                    receiver=receiver_name,
                                    op="write",
                                )
                            except STORE_ERROR_TYPES:
                                self._logger.exception(
                                    "icechunk_write_failed",
                                    date=date_key,
                                    receiver=receiver_name,
                                )
                                self._finish_receiver_day(
                                    receiver_name, date_key, "failed"
                                )
                                continue
                            t_write_end = _time.monotonic()
                            # Data of files already stored were not written again.
                            bytes_added = sum(
                                int(ds.nbytes)
                                for _, ds in augmented
                                if ds.attrs.get("File Hash") not in skipped
                            )
                            day_result: DayResult = (
                                "written" if bytes_added else "skipped"
                            )

                            # Build the daily dataset: from in-memory parts when
                            # nothing was skipped by dedup (avoids a full store
                            # round-trip), or fall back to a store read on
                            # resume / overlap runs.
                            date_obj = processor.matched_data_dirs.yyyydoy.date
                            assert date_obj is not None, "yyyydoy.date must not be None"
                            time_range = (
                                datetime.combine(date_obj, datetime.min.time()),
                                datetime.combine(date_obj, datetime.max.time()),
                            )
                            daily_ds: xr.Dataset | None
                            if not read_back:
                                daily_ds = None
                                assembly_source = "none"
                            elif len(augmented) == 1:
                                # Single-file day: use the processed dataset
                                # directly. The hash railguard guarantees
                                # in-memory data == store content whether the
                                # file was just written or already existed
                                # (re-run). No store round-trip needed.
                                daily_ds = augmented[0][1]
                                assembly_source = "memory"
                            else:
                                try:
                                    daily_ds = self._read_back_day(
                                        receiver_name, date_key, time_range
                                    )
                                except STORE_ERROR_TYPES:
                                    self._logger.exception(
                                        "read_back_failed",
                                        date=date_key,
                                        receiver=receiver_name,
                                    )
                                    self._finish_receiver_day(
                                        receiver_name,
                                        date_key,
                                        "failed",
                                        bytes_added=bytes_added,
                                    )
                                    continue
                                assembly_source = "store"
                            t_read_end = _time.monotonic()

                            self._logger.info(
                                "group_write_complete",
                                date=date_key,
                                receiver=receiver_name,
                                write_seconds=round(t_write_end - t_write_start, 2),
                                assembly_seconds=round(t_read_end - t_write_end, 2),
                                assembly_source=assembly_source,
                                total_seconds=round(t_read_end - t_write_start, 2),
                            )

                            self._finish_receiver_day(
                                receiver_name,
                                date_key,
                                day_result,
                                bytes_added=bytes_added,
                            )
                            if self._on_group_written is not None:
                                self._on_group_written(receiver_name)
                            date_datasets[date_key][receiver_name] = daily_ds
                            date_timings[date_key][receiver_name] = (
                                t_read_end - t_write_start
                            )
                            groups_written.add(group_key)

                unit_outcome = self._unit_outcome(unit_write)
                for date_key in sorted(forked_days if unit_write else ()):
                    groups_done = self._finish_forked_day(
                        date_key,
                        forked_days[date_key],
                        unit_outcome.get(date_key)
                        if isinstance(unit_outcome, dict)
                        else unit_outcome,
                        read_back=read_back,
                    )
                    for receiver_name, (daily_ds, seconds) in groups_done.items():
                        date_datasets[date_key][receiver_name] = daily_ds
                        date_timings[date_key][receiver_name] = seconds
                        groups_written.add((date_key, receiver_name))

                self._logger.info(
                    "flat_loky_complete",
                    batch_index=batch_idx + 1,
                    tasks_succeeded=tasks_succeeded,
                    tasks_failed=tasks_failed,
                    groups_written=len(groups_written),
                )

                # Guard: skip yield if all tasks failed
                if tasks_succeeded == 0:
                    self._logger.error(
                        "batch_all_tasks_failed",
                        batch_index=batch_idx + 1,
                        total_tasks=len(all_tasks),
                        batch_dates=batch_date_keys,
                    )
                    batch_elapsed = _time.monotonic() - batch_start_time
                    self._logger.info(
                        "batch_complete",
                        batch_index=batch_idx + 1,
                        total_batches=total_batches,
                        batch_dates=batch_date_keys,
                        doys_succeeded=0,
                        doys_failed=len(batch),
                        batch_seconds=round(batch_elapsed, 2),
                    )
                    gc.collect()
                    continue

                if stop.is_set():
                    return

                # The unit's stored dates, in batch order (deterministic output)
                stored = [
                    (date_key, date_datasets[date_key], date_timings[date_key])
                    for date_key, _receivers in batch
                    if date_datasets.get(date_key)
                ]
                doys_succeeded = len(stored)
                doys_failed = len(batch) - doys_succeeded
                if stored:
                    yield stored

                batch_elapsed = _time.monotonic() - batch_start_time
                self._logger.info(
                    "batch_complete",
                    batch_index=batch_idx + 1,
                    total_batches=total_batches,
                    batch_dates=batch_date_keys,
                    doys_succeeded=doys_succeeded,
                    doys_failed=doys_failed,
                    batch_seconds=round(batch_elapsed, 2),
                )

                # Belt-and-suspenders: these should already be empty (pending_
                # results/aux are .pop()'d as groups complete, and the windowed
                # completion iterator above pops each future before yielding
                # it), but this whole method is one generator whose frame spans
                # the entire multi-batch run via `yield from` -- clearing plus
                # an explicit gc.collect() bounds any reference-cycle garbage
                # (xarray/Dask objects are known to form cycles refcounting
                # alone can't clear) that would otherwise accumulate for the
                # rest of the run.
                pending_results.clear()
                pending_aux.clear()
                completed_counts.clear()
                date_datasets.clear()
                date_timings.clear()
                doy_contexts.clear()
                receiver_files_lookup.clear()
                expected_counts.clear()
                gc.collect()

    @property
    def pool_workers(self) -> int:
        """The number of workers of the run's pool (:meth:`worker_pool`)."""
        return self._workers or self.n_max_workers or os.cpu_count() or 4

    def worker_pool(self) -> Executor:
        """The run's worker pool: loky's reusable executor, sized for the run.

        The GNSS phase and a run's VOD phase share it; asking loky for an
        executor with other settings would restart its workers.
        """
        resources = self._config.processing.params.resolve_resources()
        return _loky_reusable(
            max_workers=self.pool_workers,
            # loky's own default idle timeout is 10s -- Phase 1 date-prep
            # (position computation, aux data) routinely takes 90-165s+,
            # so every worker idles out and gets respawned at every batch
            # boundary with the default. 900s comfortably outlasts a
            # single batch's prep gap while still letting the pool wind
            # down between separate cron invocations.
            timeout=900,
            initializer=_worker_init_with_run_id,
            initargs=(
                resources["nice_priority"],
                resources["cpu_affinity"],
                get_run_id(),
                active_log_dir(),
            ),
        )

    def _check_content_settings_before_run(self) -> None:
        """Refuse the run before any file is read if its settings don't fit the store.

        Compares the run's content settings (ADR 0019), preprocessing
        included, with those of the GNSS store, key by key. The same
        comparison runs at the tip before each commit; this one stops a run
        before it spends time on data that would be refused. A store
        without content settings is refused too, naming the migrate
        command.

        Raises
        ------
        ContentSettingsError
            If a content setting differs, or the store has none.
        """
        path = self.site.gnss_store_path
        if not store_exists(path):
            return  # a first run: the run's settings become the store's
        repository = read_repository_metadata(path)
        if not repository:
            return  # predates repository metadata; the write names the migration
        check_content_settings(
            repository,
            self._config,
            store_path=path,
            migrate_command=store_command(
                "migrate-metadata", self.site.site_name, "gnss_store"
            ),
        )

    def _check_new_store_settings(self) -> None:
        """Refuse a first run before processing if a new store's settings are missing.

        A store records its site description, publisher, license and naming
        authority when it is created (DataCite/STAC). A first run on a site
        whose GNSS store does not exist yet must not read every day and
        compute geometry only to fail at the write: this checks the settings
        up front, before any file is read. An existing store is never checked:
        its metadata is already written.

        Raises
        ------
        ValueError
            If the new store is missing one of the settings, naming them all.
        """
        if store_exists(self.site.gnss_store_path):
            return  # not a first run: the store's metadata is already written
        missing = missing_store_settings(
            self.site.site_name, self.site._site_config, self._config
        )
        if not missing:
            return
        raise ValueError(
            missing_store_settings_message(missing, store_label="GNSS store")
        )

    def _fail_receiver_days(
        self, date_key: str, receivers: Sequence[str], error: BaseException
    ) -> None:
        """Record *receivers* of *date_key* as failed, with the error."""
        for receiver_name in receivers:
            self._logger.error(
                "receiver_day_not_written",
                date=date_key,
                receiver=receiver_name,
                error=f"{type(error).__name__}: {error}",
            )
            self._finish_receiver_day(receiver_name, date_key, "failed")

    def _fork_result(
        self, date_key: str, job: _ForkJob, fut: Future, batch_index: int
    ) -> ForkResult:
        """The result of a fork job; a failed job lists all its files as failed."""
        try:
            return cast("ForkResult", fut.result())
        except Exception as exc:
            event = (
                "worker_pool_broken"
                if isinstance(exc, BrokenProcessPool)
                else "task_failed"
            )
            self._logger.exception(
                event,
                date=date_key,
                receiver=",".join(job.task.groups),
                batch_index=batch_index,
            )
            return ForkResult(
                task=job.task,
                fork=job.fork,
                failed=[
                    (group, Path(file_task[0]).name, repr(exc))
                    for file_task in job.task.file_tasks
                    for group in job.task.groups
                ],
            )

    def _units(
        self,
        filtered_dates: list[
            tuple[str, dict[str, tuple[ReceiverDay, str, ReceiverDay | None, str]]]
        ],
    ) -> list[
        list[tuple[str, dict[str, tuple[ReceiverDay, str, ReceiverDay | None, str]]]]
    ]:
        """The run's dates in units of :attr:`unit_days` days.

        If the GNSS store lacks a group of the first date, that date is a
        unit of its own: it is written in one session and creates the
        group, so the days after it can be written by forks (ADR 0016).
        """
        days = max(1, self.unit_days)
        first: list = []
        rest = filtered_dates
        if filtered_dates and days > 1:
            stored = (
                set(self.site.gnss_store.list_groups() or [])
                if store_exists(self.site.gnss_store_path)
                else set()
            )
            if not set(filtered_dates[0][1]) <= stored:
                first, rest = [filtered_dates[0]], filtered_dates[1:]
        units = [rest[start : start + days] for start in range(0, len(rest), days)]
        return [first, *units] if first else units

    def _unit_session(self) -> icechunk.Session | None:
        """A writable session of the GNSS store for a unit's forks, if it exists."""
        if not store_exists(self.site.gnss_store_path):
            return None
        return self.site.gnss_store.repo.writable_session("main")

    def _write_forked_unit(
        self,
        days: list[_UnitDay],
        submit_fork: Callable[[_ForkJob], Future],
        batch_index: int,
    ) -> dict[str, dict[str, GroupWriteResult]]:
        """Commit a unit's forked days once; after a lost conflict, write it again.

        Runs in the writer thread. A conflict means another run committed
        first: after :func:`~canvod.store_metadata.io.wait_after_conflict`
        the unit's days are planned again on one session at the new tip
        (whose log book now holds that run's files), their fork jobs run
        again in the pool, and the unit is committed; up to
        :data:`~canvod.store_metadata.io.CONFLICT_TRIES` tries in all
        (#339, ADR 0021).

        Returns
        -------
        dict[str, dict[str, GroupWriteResult]]
            Per day, per store group, what was written.

        Raises
        ------
        icechunk.ConflictError
            If the unit lost the conflict on every try.
        RuntimeError
            If a day could not be planned again.
        """
        date_keys = ",".join(d.planned.date_key for d in days)
        for retry in range(1, CONFLICT_TRIES):
            try:
                return days[0].processor._commit_forked_unit(
                    [(d.processor, d.planned, d.results) for d in days]
                )
            except icechunk.ConflictError as exc:
                seconds = wait_after_conflict(retry)
                self._logger.warning(
                    "forked_unit_conflict_retrying",
                    date=date_keys,
                    retry=retry,
                    of=CONFLICT_TRIES - 1,
                    waited_seconds=round(seconds, 1),
                    error=str(exc),
                )
            session = self._unit_session()
            replanned_days: list[_UnitDay] = []
            for day in days:
                with stage_timer("planning", date_key=day.planned.date_key):
                    replanned = day.processor.plan_forked_day(
                        day.task_descriptors, session=session
                    )
                if replanned is None:
                    msg = (
                        f"Day {day.planned.date_key} could not be planned again "
                        "after a lost conflict: the store no longer has its day "
                        "blocks."
                    )
                    raise RuntimeError(msg)
                replanned_days.append(
                    _UnitDay(day.processor, replanned, day.task_descriptors, [])
                )
            futures = [
                (day, job, submit_fork(job))
                for day in replanned_days
                for job in (_ForkJob(task, fork) for task, fork in day.planned.tasks)
            ]
            for day, job, fut in futures:
                day.results.append(
                    self._fork_result(day.planned.date_key, job, fut, batch_index)
                )
            days = replanned_days
        return days[0].processor._commit_forked_unit(
            [(d.processor, d.planned, d.results) for d in days]
        )

    def _unit_outcome(
        self, write: Future | None
    ) -> dict[str, dict[str, GroupWriteResult]] | BaseException:
        """What the unit's commit wrote per day, or the store error it failed with.

        Other errors (a file over another stored file's epochs, data
        preprocessed differently) stop the run.
        """
        if write is None:
            return {}
        try:
            return cast("dict[str, dict[str, GroupWriteResult]]", write.result())
        except STORE_ERROR_TYPES as exc:
            self._logger.exception("icechunk_write_failed")
            return exc

    def _read_back_day(
        self,
        receiver_name: str,
        date_key: str,
        time_range: tuple[datetime, datetime],
    ) -> xr.Dataset:
        """Read a written receiver-day back from the GNSS store, for VOD.

        Timed as the stage ``assembly``.
        """
        with stage_timer("assembly", receiver=receiver_name, date_key=date_key):
            return call_with_store_retries(
                partial(
                    self.site.read_receiver_data,
                    receiver_name=receiver_name,
                    time_range=time_range,
                ),
                logger=self._logger,
                date=date_key,
                receiver=receiver_name,
                op="read_back",
            )

    def _finish_forked_day(
        self,
        date_key: str,
        planned: ForkedDay,
        outcome: dict[str, GroupWriteResult] | BaseException | None,
        *,
        read_back: bool = True,
    ) -> dict[str, tuple[xr.Dataset | None, float]]:
        """Record a forked day's groups and, with ``read_back``, read them back.

        ``outcome`` is what the unit's commit wrote of the day, or the error
        the commit failed with. A group is failed when the commit failed,
        or when none of its files has a log-book row and some failed;
        otherwise written, or skipped when every file was already stored.

        Returns
        -------
        dict[str, tuple[xarray.Dataset | None, float]]
            Per group stored: its day's data (``None`` without
            ``read_back``) and the seconds of its write and read back.
        """
        groups = sorted({g for task, _ in planned.tasks for g in task.groups})
        if outcome is None or isinstance(outcome, BaseException):
            error = outcome or RuntimeError("The unit's commit did not run.")
            self._fail_receiver_days(date_key, groups, error)
            return {}

        time_range = (
            datetime.combine(planned.date, datetime.min.time()),
            datetime.combine(planned.date, datetime.max.time()),
        )
        done: dict[str, tuple[xr.Dataset | None, float]] = {}
        for receiver_name in groups:
            result = outcome[receiver_name]
            if not result.metadata_records:
                if result.failed_files:
                    self._logger.warning(
                        "receiver_all_tasks_failed",
                        date=date_key,
                        receiver=receiver_name,
                    )
                    self._finish_receiver_day(receiver_name, date_key, "failed")
                else:
                    self._finish_receiver_day(receiver_name, date_key, "skipped")
                continue
            bytes_added = result.total_nbytes
            day_result: DayResult = "written" if bytes_added else "skipped"
            t_read = _time.monotonic()
            try:
                daily_ds = (
                    self._read_back_day(receiver_name, date_key, time_range)
                    if read_back
                    else None
                )
            except STORE_ERROR_TYPES:
                self._logger.exception(
                    "read_back_failed", date=date_key, receiver=receiver_name
                )
                self._finish_receiver_day(
                    receiver_name, date_key, "failed", bytes_added=bytes_added
                )
                continue
            read_seconds = _time.monotonic() - t_read
            self._logger.info(
                "group_write_complete",
                date=date_key,
                receiver=receiver_name,
                write_seconds=round(result.duration_seconds, 2),
                assembly_seconds=round(read_seconds, 2),
                assembly_source="store" if read_back else "none",
                total_seconds=round(result.duration_seconds + read_seconds, 2),
                forked=True,
            )
            self._finish_receiver_day(
                receiver_name, date_key, day_result, bytes_added=bytes_added
            )
            if self._on_group_written is not None:
                self._on_group_written(receiver_name)
            done[receiver_name] = (daily_ds, result.duration_seconds + read_seconds)
        return done

    #: Receiver-days of this run that ended "failed", as ``(receiver,
    #: YYYYDOY)``. A class default, so an orchestrator made without
    #: ``__init__`` (tests) has it too.
    _failed_receiver_days: tuple[tuple[str, str], ...] = ()
    # Receiver-days finish in the batch thread, the day-writer thread and
    # the thread preparing the next batch.
    _finish_lock = threading.Lock()

    @property
    def failed_receiver_days(self) -> tuple[tuple[str, str], ...]:
        """Receiver-days of this run that failed (#334).

        ``(receiver, YYYYDOY)`` pairs, in the order they failed: every file
        failed, the write failed, reading the written day back failed, or a
        forked day was not written (``receiver_all_tasks_failed``,
        ``icechunk_write_failed``, ``read_back_failed``,
        ``receiver_day_not_written``).
        """
        return self._failed_receiver_days

    def _finish_receiver_day(
        self,
        receiver: str,
        date_key: str,
        result: DayResult,
        *,
        bytes_added: int | None = None,
    ) -> None:
        """Record a finished receiver-day in the run history, if recorded."""
        with self._finish_lock:
            if result == "failed":
                self._failed_receiver_days = (
                    *self._failed_receiver_days,
                    (receiver, date_key),
                )
            if self._run is not None:
                self._run.finish(receiver, date_key, result, bytes_added=bytes_added)

    def _size_to_memory(
        self,
        filtered_dates: list[
            tuple[str, dict[str, tuple[ReceiverDay, str, ReceiverDay | None, str]]]
        ],
    ) -> None:
        """Size the workers and the days per unit to the memory budget.

        See :mod:`canvodpy.orchestrator.memory_budget`. A reference receiver
        paired with several canopies is counted once per pairing: one task
        reads its file for all pairings.

        Raises
        ------
        MemoryBudgetError
            If not even one worker fits with one day per unit.
        """
        preprocessing = self._config.processing.preprocessing
        aggregation = (
            None if preprocessing is None else preprocessing.temporal_aggregation
        )
        cadence_s = (
            pd.Timedelta(aggregation.freq).total_seconds()
            if aggregation is not None and aggregation.enabled
            else None
        )
        epoch_chunk = self._config.processing.icechunk.chunk_strategies.gnss_store.epoch
        tasks: list[list[InputFile]] = []
        day_input = 0
        for _date_key, groups in filtered_dates:
            pairings: dict[tuple[str, str], int] = defaultdict(int)
            days: dict[tuple[str, str], tuple[ReceiverDay, str]] = {}
            for day, _type, _position_day, fmt in groups.values():
                key = (day.receiver, fmt)
                pairings[key] += 1
                days[key] = (day, fmt)
            this_day = 0
            # discover_files reads the scans _find_files cached for this
            # run: no folder is listed again.
            for key, (day, fmt) in days.items():
                files = [
                    InputFile(
                        path=found.path,
                        size=_input_bytes([found.path]) * pairings[key],
                        reader=fmt,
                        canonical_name=found.canonical_name,
                    )
                    for found in discover_files(day, fmt)
                ]
                this_day += sum(f.size for f in files)
                tasks.extend(
                    chunk_tasks(files, epoch_chunk=epoch_chunk, cadence_s=cadence_s)
                )
            day_input = max(day_input, this_day)

        main_now = psutil.Process().memory_info().rss
        if self.max_memory_gb is not None:
            budget = int(self.max_memory_gb * GB)
            source = "processing.params.max_memory_gb"
        else:
            budget = psutil.virtual_memory().available + main_now
            source = "the memory available at the start"
        max_workers = self.n_max_workers or os.cpu_count() or 4
        plan = plan_memory(
            budget_bytes=budget,
            main_now_bytes=main_now,
            day_input_bytes=day_input,
            task=largest_task(tasks),
            tasks_per_day=len(tasks) / max(1, len(filtered_dates)),
            max_workers=max_workers,
            days_to_run=len(filtered_dates),
            days_per_batch=self._days_per_batch_cap,
            budget_source=source,
        )
        limited = plan.workers < max_workers or plan.unit_limit == "memory"
        (self._logger.warning if limited else self._logger.info)(
            "memory_budget",
            budget_source=source,
            max_workers=max_workers,
            **plan.log_fields(),
        )
        self._workers = plan.workers
        self.unit_days = plan.unit_days
        if self._run is not None:
            self._run.set_workers(plan.workers)

    def process_by_date(
        self,
        keep_vars: list[str] | None = None,
        start_from: str | None = None,
        end_at: str | None = None,
        new_files_only: bool = False,
    ) -> Generator[tuple[str, dict[str, xr.Dataset], dict[str, float]]]:
        """Process all receivers grouped by date; yield each day read back.

        Each unique receiver is processed once per day with its actual name
        as the Icechunk group name. Dates are processed in units of days
        (``_process_multi_day_batches``); each stored receiver-day is read
        back from the store for the caller. A run, which needs no data back,
        uses :meth:`store_by_unit`.

        Parameters
        ----------
        keep_vars : list[str], optional
            Variables to keep in datasets
        start_from : str, optional
            YYYYDOY string to start from
        end_at : str, optional
            YYYYDOY string to end at
        new_files_only : bool, default False
            Only the dates on which a receiver has a file the GNSS store
            doesn't hold (:meth:`_dates_with_new_files`); a run without
            dates uses this (#386).

        Yields
        ------
        tuple[str, dict[str, xr.Dataset], dict[str, float]]
            Date string, dict of {receiver_name: dataset}, and timings

        """
        for unit in self._units_stored(
            keep_vars, start_from, end_at, new_files_only, read_back=True
        ):
            for date_key, datasets, timings in unit:
                yield date_key, cast("dict[str, xr.Dataset]", datasets), timings

    def store_by_unit(
        self,
        start_from: str | None = None,
        end_at: str | None = None,
        new_files_only: bool = False,
    ) -> Generator[dict[str, tuple[str, ...]]]:
        """Store the days in units of days and read nothing back (ADR 0021).

        The GNSS phase of a run: as :meth:`process_by_date`, but no
        receiver-day is read back. The VOD phase reads the days it needs
        from the store.

        Parameters
        ----------
        start_from, end_at, new_files_only
            As :meth:`process_by_date`.

        Yields
        ------
        dict[str, tuple[str, ...]]
            Per unit once it is committed: each stored day (YYYYDOY) with
            the groups that stored it, in date order. A day of which no
            group was stored is left out.
        """
        for unit in self._units_stored(
            None, start_from, end_at, new_files_only, read_back=False
        ):
            yield {date_key: tuple(sorted(datasets)) for date_key, datasets, _ in unit}

    def _units_stored(
        self,
        keep_vars: list[str] | None,
        start_from: str | None,
        end_at: str | None,
        new_files_only: bool,
        *,
        read_back: bool,
    ) -> Generator[list[tuple[str, dict[str, xr.Dataset | None], dict[str, float]]]]:
        """Find, plan and store the dates; yield each unit once it is written."""
        if self.dry_run:
            self._logger.info(
                "dry_run_mode", message="Simulating processing without execution"
            )
            self.print_preview(start_from, end_at, new_files_only=new_files_only)
            return

        # A first run whose new store is missing settings is refused before
        # any file is read; the write would refuse every day at the end. So
        # is a run whose settings don't fit the store's content settings.
        self._check_new_store_settings()
        self._check_content_settings_before_run()

        grouped = self._group_by_date_and_receiver(start_from, end_at)
        filtered_dates = self._filter_dates(grouped, start_from, end_at)
        if new_files_only:
            filtered_dates = self._dates_with_new_files(filtered_dates)
        self._warn_days_without_vod(start_from, end_at)
        self._warn_incomplete_days(filtered_dates)

        if not filtered_dates:
            self._logger.warning(
                "no_dates_in_range", start_from=start_from, end_at=end_at
            )
            return

        if self._run is not None:
            self._run.plan(
                (group, date_key)
                for date_key, groups in filtered_dates
                for group in groups
            )

        # A run without read-back passes stored days on without reading
        # them; with read-back the caller needs their data.
        if not read_back:
            stored_dates, filtered_dates = self._split_stored_dates(filtered_dates)
            for date_key, groups in stored_dates:
                for group in groups:
                    self._finish_receiver_day(group, date_key, "skipped")
            days = max(1, self.unit_days)
            for start in range(0, len(stored_dates), days):
                yield [
                    (date_key, dict.fromkeys(groups), {})
                    for date_key, groups in stored_dates[start : start + days]
                ]
            if not filtered_dates:
                return

        self._size_to_memory(filtered_dates)

        self._logger.info(
            "process_by_date_started",
            total_dates=len(filtered_dates),
            date_range_start=filtered_dates[0][0],
            date_range_end=filtered_dates[-1][0],
            unit_days=self.unit_days,
            n_max_workers=self.n_max_workers,
        )

        overall_start = _time.monotonic()

        # The units run in a thread of their own, one unit ahead of the
        # caller: while the caller works on a unit (VOD, or the days read
        # back), the next unit is read and written. Two units' data are in
        # memory at most.
        yield from _run_ahead(
            partial(
                self._process_multi_day_batches,
                filtered_dates,
                keep_vars,
                read_back=read_back,
            ),
            ahead=1,
            name="canvodpy-batches",
        )

        overall_elapsed = _time.monotonic() - overall_start
        self._logger.info(
            "process_by_date_complete",
            total_dates=len(filtered_dates),
            total_seconds=round(overall_elapsed, 2),
        )


@deprecated(
    "SingleReceiverProcessor is left over from development and will be removed with the next major version. "
    "Its process() method raises NotImplementedError. Use "
    "canvodpy.Site(<site>).pipeline().process_date(<YYYYDOY>) instead."
)
class SingleReceiverProcessor:
    """Process a single receiver for one day.

    Parameters
    ----------
    receiver_name : str
        Actual receiver name (e.g., 'canopy_01', 'reference_01')
    receiver_type : str
        Receiver type ('canopy' or 'reference')
    data_dir : Path
        Directory containing RINEX files
    yyyydoy : YYYYDOY
        Date to process
    site : GnssResearchSite
        Research site
    n_max_workers : int
        Maximum parallel workers

    """

    def __init__(
        self,
        receiver_name: str,
        receiver_type: str,
        data_dir: Path,
        yyyydoy: YYYYDOY,
        site: GnssResearchSite,
        n_max_workers: int = 12,
        reader_name: str = "rinex3",
    ) -> None:
        self.receiver_name = receiver_name
        self.receiver_type = receiver_type
        self.data_dir = data_dir
        self.yyyydoy = yyyydoy
        self.site = site
        self.n_max_workers = n_max_workers
        self.reader_name = reader_name
        self._logger = structlog.get_logger(__name__).bind(
            receiver=receiver_name,
            date=yyyydoy.to_str(),
        )

    def _get_rinex_files(self) -> list[Path]:
        """Get sorted list of GNSS data files, as the run selects them.

        Delegates to :func:`canvodpy.orchestrator.discovery.discover_files`.
        """
        receiver_cfg = self.site._site_config.receivers.get(self.receiver_name)
        day = ReceiverDay(
            self.receiver_name,
            self.data_dir,
            self.yyyydoy.to_str(),
            recipe_file(self.site.site_name, receiver_cfg.recipe)
            if receiver_cfg
            else None,
        )
        return [found.path for found in discover_files(day, self.reader_name)]

    def process(self, keep_vars: list[str] | None = None) -> xr.Dataset:
        """Refuse: this class can no longer process a receiver.

        Use ``canvodpy.Site(<site>).pipeline().process_date(<YYYYDOY>)``,
        which returns the dataset of every receiver of the site for that
        day, keyed by receiver name.

        Parameters
        ----------
        keep_vars : list[str], optional
            Ignored.

        Raises
        ------
        NotImplementedError
            Always.
        """
        msg = (
            "SingleReceiverProcessor.process() no longer works: it relied on "
            "a processor method that has been removed. Use "
            f"canvodpy.Site({self.site.site_name!r}).pipeline().process_date("
            f"{self.yyyydoy.to_str()!r})[{self.receiver_name!r}] instead."
        )
        raise NotImplementedError(msg)


if __name__ == "__main__":
    from canvod.config import load_config
    from canvod.store import GnssResearchSite

    cfg = load_config()
    proc = cfg.processing.params
    site = GnssResearchSite(site_name="ExampleSite")

    # All params from config — no hardcoded defaults
    keep_vars = proc.keep_gnss_observables
    resources = proc.resolve_resources()
    with PipelineOrchestrator(
        site=site,
        dry_run=False,
        n_max_workers=resources["n_workers"],
        config=cfg,
    ) as orchestrator:
        for date_key, datasets, _timings in orchestrator.process_by_date(
            keep_vars=keep_vars
        ):
            print(f"\nProcessed date: {date_key}")
            for receiver_name, ds in datasets.items():
                print(f"  {receiver_name}: {dict(ds.sizes)}")
