"""Processing pipeline orchestration for site-level workflows."""

from __future__ import annotations

import gc
import os
import time as _time
import warnings
from collections import defaultdict
from collections.abc import Callable, Generator, Sequence
from concurrent.futures import (
    FIRST_COMPLETED,
    Future,
    ThreadPoolExecutor,
    as_completed,
    wait,
)
from concurrent.futures.process import BrokenProcessPool
from datetime import datetime
from functools import partial
from itertools import zip_longest
from pathlib import Path
from typing import TypeVar

import pint
import structlog
import xarray as xr
from loky import get_reusable_executor as _loky_reusable

from canvod.config import CanvodConfig, load_config
from canvod.config.models import mixed_format_error, reference_store_group
from canvod.ops import planned_settings, preprocess_files
from canvod.readers import MatchedDirs
from canvod.readers.gnss_specs.constants import UREG
from canvod.store import GnssResearchSite
from canvod.store_metadata import store_exists
from canvod.utils.logging import get_run_id, new_run_id, reset_run_id, set_run_id
from canvod.utils.tools import YYYYDOY, deprecated
from canvodpy.logging.logging_config import active_log_dir, ensure_file_logging
from canvodpy.orchestrator.discovery import (
    ReceiverDay,
    check_receivers,
    clear_discovery_cache,
    detect_reader_format,
    discover_files,
    is_compressed,
    receiver_days,
    recipe_file,
    unprocessed_files,
)
from canvodpy.orchestrator.processor import (
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
)
from canvodpy.orchestrator.store_retry import STORE_ERROR_TYPES, call_with_store_retries

# Old-style TypeVar (not PEP 695 `def f[T](...)`): CodeQL's Python analysis
# doesn't yet understand the newer generic syntax and flags T as a
# potentially-uninitialized local inside the nested _submit() closure below.
# A module-level TypeVar is unambiguous to both type checkers and CodeQL.
T = TypeVar("T")


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
    by_receiver: dict[str, list[tuple]] = {}
    for task_args in task_descriptors:
        by_receiver.setdefault(task_args[4], []).append(task_args)
    return [
        task_args
        for row in zip_longest(*by_receiver.values())
        for task_args in row
        if task_args is not None
    ]


def _build_ordered_tasks(
    ordered_date_keys: Sequence[str],
    task_descriptors_by_date: dict[str, list[tuple]],
) -> list[tuple[str, tuple]]:
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
    silently omitted, matching the previous behavior.
    """
    all_tasks: list[tuple[str, tuple]] = []
    for date_key in ordered_date_keys:
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
        Maximum parallel workers per day. ``None`` means auto-detect
        (via ``os.cpu_count()``).
    dry_run : bool
        If True, only simulate processing without executing
    days_per_batch : int
        Number of DOYs pooled per loky wave (default: 1)
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

    """

    @deprecate_no_effect_arguments
    def __init__(
        self,
        site: GnssResearchSite,
        n_max_workers: int | None = None,
        dry_run: bool = False,
        days_per_batch: int = 1,
        max_memory_gb: float | None = None,
        cpu_affinity: list[int] | None = None,
        nice_priority: int | None = None,
        threads_per_worker: int | None = None,
        on_group_written: Callable[[str], None] | None = None,
        config: CanvodConfig | None = None,
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
        # The log location comes from the configuration of this run.
        ensure_file_logging()
        # A new run sees files added since the previous one.
        clear_discovery_cache()
        check_receivers(
            site.receivers, site._site_config.get_base_path(), site.site_name
        )
        # A run started from Python gets a run_id like one of `canvodpy run`
        # (which sets its own first); close() removes it again.
        self._run_id_token = (
            set_run_id(new_run_id(site.site_name)) if get_run_id() is None else None
        )

        self.site = site
        self.n_max_workers = n_max_workers
        self.dry_run = dry_run
        self.days_per_batch = days_per_batch
        self._on_group_written = on_group_written
        self._batch_duration: pint.Quantity = days_per_batch * 24 * UREG.hour
        self._threads_per_worker = threads_per_worker
        self._memory_monitor = MemoryMonitor()
        self._logger = structlog.get_logger(__name__).bind(site=site.site_name)

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
            days_per_batch=days_per_batch,
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
        self,
    ) -> dict[str, dict[str, tuple[ReceiverDay, str, ReceiverDay | None, str]]]:
        """Group receivers by date, expanding references per paired canopy.

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

        for analysis in analyses:
            canopy_rx = analysis["canopy_receiver"]
            ref_name = analysis["reference_receiver"]
            common = sorted(set(days_of[canopy_rx]) & set(days_of[ref_name]))
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

        Returns
        -------
        dict
            Summary of dates, receivers, and files to process

        """
        grouped = self._group_by_date_and_receiver()
        dates = self._filter_dates(grouped, start, end)

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
    ) -> None:
        """Print a formatted preview of the processing plan."""
        plan = self.preview_processing_plan(start, end)

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
    ) -> tuple[RinexDataProcessor, list[tuple], list[tuple[str, list[Path]]]] | None:
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

    def _process_multi_day_batches(
        self,
        filtered_dates: list[
            tuple[str, dict[str, tuple[ReceiverDay, str, ReceiverDay | None, str]]]
        ],
        keep_vars: list[str] | None,
    ) -> Generator[tuple[str, dict[str, xr.Dataset], dict[str, float]]]:
        """Process dates in batches of ``days_per_batch`` days (1 or more).

        Each batch runs in three phases:

        1. Prepare, one thread per date: auxiliary data (SP3/CLK
           interpolation or cache), receiver positions, one task per file.
        2. Process the files of all dates of the batch in loky's reusable
           process pool, at most twice the worker count in flight.
        3. Write, in this process, as soon as all files of a receiver-day
           are back: ``processing.preprocessing`` (if set), then
           ``_append_to_icechunk`` (one commit for the data, one for the
           store metadata). The pool keeps working meanwhile.

        Dates are yielded after the batch is written; the caller computes
        VOD before the next batch starts.

        Parameters
        ----------
        filtered_dates : list
            Filtered ``(date_key, receivers)`` pairs.
        keep_vars : list[str] | None
            Variables to keep in datasets.

        Yields
        ------
        tuple[str, dict[str, xr.Dataset], dict[str, float]]
            ``(date_key, datasets, timings)`` per DOY.

        """
        days_per_batch = self.days_per_batch
        total_batches = (len(filtered_dates) + days_per_batch - 1) // days_per_batch
        self._logger.info(
            "multi_day_batch_strategy",
            days_per_batch=days_per_batch,
            total_dates=len(filtered_dates),
            total_batches=total_batches,
        )

        # Partition dates into batches
        for batch_idx, batch_start in enumerate(
            range(0, len(filtered_dates), days_per_batch)
        ):
            batch = filtered_dates[batch_start : batch_start + days_per_batch]
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

            # ── Phase 1: Prepare (concurrent across dates) ────────────
            t_phase1_start = _time.monotonic()
            doy_contexts: dict[
                str,
                tuple[RinexDataProcessor, list[tuple[str, list[Path]]]],
            ] = {}
            task_descriptors_by_date: dict[str, list[tuple]] = {}

            phase1_workers = len(batch)
            batch_receivers_by_date = dict(batch)
            with ThreadPoolExecutor(max_workers=phase1_workers) as tp:
                futures = {
                    tp.submit(
                        self._prepare_single_date, date_key, receivers, keep_vars
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
                            continue

                    if result is None:
                        continue

                    processor, task_descriptors, receiver_file_map = result
                    doy_contexts[date_key] = (processor, receiver_file_map)
                    task_descriptors_by_date[date_key] = task_descriptors

            all_tasks = _build_ordered_tasks(
                [date_key for date_key, _receivers in batch],
                task_descriptors_by_date,
            )

            t_phase1_end = _time.monotonic()
            self._logger.info(
                "phase1_prepare_complete",
                batch_index=batch_idx + 1,
                phase1_seconds=round(t_phase1_end - t_phase1_start, 2),
                doys_prepared=len(doy_contexts),
                total_tasks=len(all_tasks),
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
            n_wrk = self.n_max_workers or os.cpu_count() or 4
            _res = self._config.processing.params.resolve_resources()
            _pool = _loky_reusable(
                max_workers=n_wrk,
                # loky's own default idle timeout is 10s -- Phase 1 date-prep
                # (position computation, aux data) routinely takes 90-165s+,
                # so every worker idles out and gets respawned at every batch
                # boundary with the default. 900s comfortably outlasts a
                # single batch's prep gap while still letting the pool wind
                # down between separate cron invocations.
                timeout=900,
                initializer=_worker_init_with_run_id,
                initargs=(
                    _res["nice_priority"],
                    _res["cpu_affinity"],
                    get_run_id(),
                    active_log_dir(),
                ),
            )

            def _submit_task(task: tuple[str, tuple], *, _pool=_pool) -> Future:
                task_args = task[1]
                # Trailing element marks a reference fan-out task (dict
                # result, one canopy_positions arg instead of a single
                # receiver_position/receiver_name pair) vs. the normal
                # one-file-one-receiver shape -- see prepare_batch_tasks.
                if task_args[-1]:
                    return _pool.submit(
                        preprocess_reference_with_hermite_aux_fanout, *task_args[:-1]
                    )
                return _pool.submit(preprocess_with_hermite_aux, *task_args[:-1])

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
            pending_results: dict[tuple[str, str], list[tuple[Path, xr.Dataset]]] = (
                defaultdict(list)
            )
            pending_aux: dict[tuple[str, str], dict[Path, dict[str, xr.Dataset]]] = (
                defaultdict(dict)
            )
            completed_counts: dict[tuple[str, str], int] = defaultdict(int)
            tasks_succeeded = 0
            tasks_failed = 0

            # Per-date accumulators for final yield
            date_datasets: dict[str, dict[str, xr.Dataset]] = defaultdict(dict)
            date_timings: dict[str, dict[str, float]] = defaultdict(dict)
            groups_written: set[tuple[str, str]] = set()

            # Build file-size lookup for throughput display
            file_sizes_mb: dict[tuple[str, str], float] = {}
            for (dk, rn), files in receiver_files_lookup.items():
                file_sizes_mb[(dk, rn)] = sum(
                    f.stat().st_size / 1_048_576 for f in files if f.exists()
                )

            with _processing_progress(disable=True) as _progress_inner:
                # Stub tasks on the disabled inner progress (no-ops for rendering)
                _progress_inner.add_task(
                    f"[bold]batch {batch_idx + 1}",
                    total=len(all_tasks),
                )

                batch_t0 = _time.monotonic()
                for task, fut in completion_iter:
                    date_key, task_args = task
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
                            continue

                        processor = doy_contexts[date_key][0]
                        for fname, ds in group_results:
                            _warn_if_epoch_count_differs_from_name(
                                processor._logger,
                                fname,
                                processor._canonical_name(fname),
                                ds,
                            )
                        # processing.preprocessing (if set) on the whole
                        # receiver-day, so time bins can span two files
                        augmented = preprocess_files(
                            sorted(group_results, key=lambda x: x[0].name),
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
                            continue
                        t_write_end = _time.monotonic()

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
                        if len(augmented) == 1:
                            # Single-file day: use the processed dataset
                            # directly. The hash railguard guarantees
                            # in-memory data == store content whether the
                            # file was just written or already existed
                            # (re-run). No store round-trip needed.
                            daily_ds = augmented[0][1]
                            assembly_source = "memory"
                        else:
                            try:
                                daily_ds = call_with_store_retries(
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
                            except STORE_ERROR_TYPES:
                                self._logger.exception(
                                    "read_back_failed",
                                    date=date_key,
                                    receiver=receiver_name,
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

                        if self._on_group_written is not None:
                            self._on_group_written(receiver_name)
                        date_datasets[date_key][receiver_name] = daily_ds
                        date_timings[date_key][receiver_name] = (
                            t_read_end - t_write_start
                        )
                        groups_written.add(group_key)

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

            # Yield per date in batch order (deterministic output)
            doys_succeeded = 0
            doys_failed = 0
            for date_key, _receivers in batch:
                if date_datasets.get(date_key):
                    doys_succeeded += 1
                    yield (
                        date_key,
                        date_datasets[date_key],
                        date_timings[date_key],
                    )
                else:
                    doys_failed += 1

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

    def _check_preprocessing_before_run(
        self,
        dates: list[
            tuple[str, dict[str, tuple[ReceiverDay, str, ReceiverDay | None, str]]]
        ],
    ) -> None:
        """Refuse the run before processing if a group holds other preprocessing.

        Compares ``processing.preprocessing`` with the log books of every
        GNSS store group the run writes. The same comparison runs again on
        each dataset at write time; this one stops a run before it spends
        time on data that would be refused.

        Raises
        ------
        PreprocessingMismatchError
            If a group holds data preprocessed differently.
        """
        if not store_exists(self.site.gnss_store_path):
            return  # a first run: the store holds nothing to compare with
        settings = planned_settings(self._config.processing.preprocessing)
        for group in sorted({group for _, receivers in dates for group in receivers}):
            self.site.gnss_store.check_settings_match(group, settings)

    def process_by_date(
        self,
        keep_vars: list[str] | None = None,
        start_from: str | None = None,
        end_at: str | None = None,
    ) -> Generator[tuple[str, dict[str, xr.Dataset], dict[str, float]]]:
        """Process all receivers grouped by date.

        Each unique receiver is processed once per day with its actual name
        as the Icechunk group name. Dates are processed in batches of
        ``days_per_batch`` days (``_process_multi_day_batches``).

        Parameters
        ----------
        keep_vars : list[str], optional
            Variables to keep in datasets
        start_from : str, optional
            YYYYDOY string to start from
        end_at : str, optional
            YYYYDOY string to end at

        Yields
        ------
        tuple[str, dict[str, xr.Dataset], dict[str, float]]
            Date string, dict of {receiver_name: dataset}, and timings

        """
        if self.dry_run:
            self._logger.info(
                "dry_run_mode", message="Simulating processing without execution"
            )
            self.print_preview(start_from, end_at)
            return

        grouped = self._group_by_date_and_receiver()
        filtered_dates = self._filter_dates(grouped, start_from, end_at)

        if not filtered_dates:
            self._logger.warning(
                "no_dates_in_range", start_from=start_from, end_at=end_at
            )
            return

        self._check_preprocessing_before_run(filtered_dates)

        self._logger.info(
            "process_by_date_started",
            total_dates=len(filtered_dates),
            date_range_start=filtered_dates[0][0],
            date_range_end=filtered_dates[-1][0],
            days_per_batch=self.days_per_batch,
            n_max_workers=self.n_max_workers,
        )

        overall_start = _time.monotonic()

        yield from self._process_multi_day_batches(filtered_dates, keep_vars)

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
        days_per_batch=proc.days_per_batch,
        config=cfg,
    ) as orchestrator:
        for date_key, datasets, _timings in orchestrator.process_by_date(
            keep_vars=keep_vars
        ):
            print(f"\nProcessed date: {date_key}")
            for receiver_name, ds in datasets.items():
                print(f"  {receiver_name}: {dict(ds.sizes)}")
