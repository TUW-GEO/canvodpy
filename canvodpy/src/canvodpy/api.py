"""High-level public API for canvodpy.

This module provides the user-friendly API.

Recommended surfaces:
- Run the pipeline via the ``canvodpy`` CLI (production runs, resumable).
- Script a configured pipeline run in Python via ``Site.pipeline()``
  (``Pipeline`` class) — this is what the CLI wraps internally.

``canvodpy.functional`` is deprecated: it is no longer maintained and gives
different results than ``canvodpy run``.

``process_date()``, ``calculate_vod()``, and ``preview_processing()`` below
are deprecated convenience wrappers around ``Pipeline`` — use
``Site.pipeline()`` directly instead.

Examples
--------
Object-oriented (recommended for Python-native pipeline runs):
    >>> from canvodpy import Site, Pipeline
    >>> site = Site("ExampleSite")
    >>> pipeline = site.pipeline()
    >>> data = pipeline.process_date("2025001")

Low-level (full control):
    >>> from canvod.store import GnssResearchSite
    >>> from canvodpy.processor.pipeline_orchestrator import PipelineOrchestrator
    >>> # Direct access to internals

"""

from __future__ import annotations

import sys
import time
import warnings
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

from canvod.utils.tools import deprecated, deprecated_argument
from canvodpy.orchestrator.resources import deprecate_no_effect_arguments

# Lazy imports to avoid circular dependencies

if TYPE_CHECKING:
    from collections.abc import Callable, Generator, Sequence
    from pathlib import Path
    from types import TracebackType

    import xarray as xr

    from canvod.store import MyIcechunkStore
    from canvodpy.orchestrator.vod_phase import VodUnitReport
    from canvodpy.vod_computer import VodComputer


def _passed(**arguments: object) -> dict[str, object]:
    """The arguments that are not ``None``.

    For passing on a deprecated argument only when the caller gave it, so
    that the callee warns only then.
    """
    return {name: value for name, value in arguments.items() if value is not None}


@contextmanager
def _forwarded_days_per_batch() -> Generator[None]:
    """Warn about ``days_per_batch`` once: the caller warned, the callee doesn't."""
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore", "The 'days_per_batch' argument of", FutureWarning
        )
        yield


class Site:
    """User-friendly wrapper around GnssResearchSite.

    Provides a clean, modern API for site management while using
    the proven GnssResearchSite implementation internally.

    Parameters
    ----------
    name : str
        Site name from configuration (e.g., "ExampleSite")

    Attributes
    ----------
    name : str
        Site name
    receivers : dict
        All configured receivers
    active_receivers : dict
        Only active receivers
    vod_analyses : dict
        Configured VOD analysis pairs
    gnss_store
        Access to RINEX data store
    vod_store
        Access to VOD results store

    Examples
    --------
    >>> site = Site("ExampleSite")
    >>> print(site.receivers)
    {'canopy_01': {...}, 'reference_01': {...}}

    >>> # Create pipeline
    >>> pipeline = site.pipeline()

    >>> # Access stores
    >>> site.gnss_store.list_groups()

    """

    def __init__(self, name: str) -> None:
        # Lazy import to avoid circular dependency
        from canvod.store import GnssResearchSite

        # Use proven implementation
        self._site = GnssResearchSite(name)
        self.name = name

    @property
    def receivers(self) -> dict:
        """Get all configured receivers."""
        return self._site.receivers

    @property
    def active_receivers(self) -> dict:
        """Get only active receivers."""
        return self._site.active_receivers

    @property
    def vod_analyses(self) -> dict:
        """Get configured VOD analysis pairs."""
        return self._site.active_vod_analyses

    @property
    def vod(self) -> VodComputer:
        """Lazy VOD computation helper."""
        if not hasattr(self, "_vod_computer"):
            from canvodpy.vod_computer import VodComputer

            self._vod_computer = VodComputer(self)
        return self._vod_computer

    @property
    def gnss_store(self) -> MyIcechunkStore:
        """Access RINEX data store."""
        return self._site.gnss_store

    @property
    def vod_store(self) -> MyIcechunkStore:
        """Access VOD results store."""
        return self._site.vod_store

    @property
    def gnss_store_path(self) -> Path | str:
        """Where the site's GNSS store is, from the settings; read-only.

        A local directory, or the ``s3://`` URL of a store on S3.
        """
        return self._site.gnss_store_path

    @property
    def vod_store_path(self) -> Path | str:
        """Where the site's VOD store is, from the settings; read-only.

        A local directory, or the ``s3://`` URL of a store on S3.
        """
        return self._site.vod_store_path

    @deprecate_no_effect_arguments
    @deprecated_argument(
        "days_per_batch",
        "The 'days_per_batch' argument of Site.pipeline() is left over from "
        "development and will be removed with the next major version. A run "
        "derives its days per unit from the memory budget; until then the "
        "argument caps them. Remove the argument.",
    )
    def pipeline(
        self,
        keep_vars: list[str] | None = None,
        aux_agency: str | None = None,
        n_workers: int | None = None,
        dry_run: bool = False,
        days_per_batch: int | None = None,
        max_memory_gb: float | None = None,
        cpu_affinity: list[int] | None = None,
        nice_priority: int | None = None,
        threads_per_worker: int | None = None,
        on_group_written: Callable[[str], None] | None = None,
        label: str | None = None,
        on_discovery_start: Callable[[str, Path], None] | None = None,
        on_discovery_end: Callable[[str, int, int, float], None] | None = None,
        on_new_files: Callable[[list[tuple[str, str]]], None] | None = None,
        on_incomplete_day: Callable[[str, str, int, int], None] | None = None,
        on_days_without_vod: Callable[[str, list[str]], None] | None = None,
    ) -> Pipeline:
        """Create a processing pipeline for this site.

        All parameters default to ``None``, which means "read from config".
        Explicit values override the config.

        Reader format is configured per-receiver via ``reader_format`` in
        the ``sites:`` section of ``config/canvod-settings.yaml`` (default:
        ``"auto"``).

        Parameters
        ----------
        keep_vars : list[str], optional
            RINEX variables to keep. Default: from config.
        aux_agency : str, optional
            Analysis center for auxiliary data (COD, ESA, GFZ, JPL).
            Default: from config.
        n_workers : int, optional
            Number of parallel workers. Default: from config.
        dry_run : bool, default False
            If True, simulate processing without execution.
        max_memory_gb : float, optional
            Memory budget of the run in GB: the workers and the days per
            unit are sized to fit it. Default: from config; without a value
            there, the memory available when the run starts.
        threads_per_worker : int, optional
            Threads per worker process. Default: from config.
        on_group_written : Callable[[str], None], optional
            Called with the receiver-group name each time a group's data for
            one day finishes writing to Icechunk. Lets a caller drive its own
            progress display (e.g. the CLI's per-site/receiver rows) without
            this class owning any display itself.
        label : str, optional
            Free-text label of the run, stored in the run history (for
            example to group the repetitions of a benchmark).
        on_discovery_start : Callable[[str, Path], None], optional
            Called with the receiver name and its data folder when the run
            starts finding that receiver's files.
        on_discovery_end : Callable[[str, int, int, float], None], optional
            Called with the receiver name, the number of files found, the
            number of days and the elapsed seconds when the run has found
            them.
        on_new_files : Callable[[list[tuple[str, str]]], None], optional
            With ``new_files_only``, called with the ``(YYYYDOY, receiver)``
            pairs that have a file the GNSS store doesn't hold, before they
            are processed.
        on_incomplete_day : Callable[[str, str, int, int], None], optional
            Called with ``(receiver, YYYYDOY, files_found, files_expected)``
            for each receiver-day to process that has fewer files than its
            file length gives for a whole day. Today is not checked.
        on_days_without_vod : Callable[[str, list[str]], None], optional
            Called with a receiver and the days in the range on which it has
            no files while its pair has: those days are not processed and
            get no VOD.

        Returns
        -------
        Pipeline
            Configured pipeline for this site

        Examples
        --------
        >>> site = Site("ExampleSite")
        >>> pipeline = site.pipeline(n_workers=8)
        >>> data = pipeline.process_date("2025001")

        """
        with _forwarded_days_per_batch():
            return Pipeline(
                site=self,
                keep_vars=keep_vars,
                aux_agency=aux_agency,
                n_workers=n_workers,
                dry_run=dry_run,
                max_memory_gb=max_memory_gb,
                threads_per_worker=threads_per_worker,
                on_group_written=on_group_written,
                label=label,
                **_passed(days_per_batch=days_per_batch),
                on_discovery_start=on_discovery_start,
                on_discovery_end=on_discovery_end,
                on_new_files=on_new_files,
                on_incomplete_day=on_incomplete_day,
                on_days_without_vod=on_days_without_vod,
            )

    def __repr__(self) -> str:
        n_receivers = len(self.active_receivers)
        n_analyses = len(self.vod_analyses)
        return f"Site('{self.name}', receivers={n_receivers}, analyses={n_analyses})"

    def __str__(self) -> str:
        return f"GNSS Site: {self.name}"


@dataclass
class RunUnit:
    """What :meth:`Pipeline.run` did with one unit of days.

    Attributes
    ----------
    days
        Each day (YYYYDOY) the GNSS phase stored, with the groups that
        stored it. A day that failed in every group is not here; it stays
        open for the next run.
    vod
        What the VOD phase did with the days: written, stored before, or
        missing (with the reason), per analysis. ``None`` when the run
        computes no VOD or the VOD phase failed.
    vod_error
        Why the VOD phase failed, if it did. The days then have their GNSS
        data but no VOD; ``canvodpy vod-reconcile`` finds them.
    gnss_seconds, vod_seconds
        Wall time of the unit's GNSS phase (as the caller waited for it)
        and of its VOD phase.
    """

    days: dict[str, tuple[str, ...]]
    vod: VodUnitReport | None = None
    vod_error: Exception | None = None
    gnss_seconds: float = 0.0
    vod_seconds: float = 0.0


class Pipeline:
    """User-friendly wrapper around PipelineOrchestrator.

    Provides a clean API for processing workflows while using
    proven orchestrator logic internally.

    All parameters default to ``None``, which means "read from the
    ``processing:`` section of ``config/canvod-settings.yaml``". Explicit
    values override the config.

    Reader format is configured per-receiver via ``reader_format`` in the
    ``sites:`` section (default: ``"auto"``).

    Parameters
    ----------
    site : Site or str
        Site object or site name
    keep_vars : list[str], optional
        RINEX variables to keep. Default: from config.
    aux_agency : str, optional
        Analysis center for auxiliary data. Default: from config.
    n_workers : int, optional
        Number of parallel loky worker processes. Default: from config
        (``processing.n_max_threads``).
    dry_run : bool, default False
        If True, simulate without execution.
    max_memory_gb : float, optional
        Memory budget of the run in GB: the workers and the days per unit
        are sized to fit it (ADR 0021). Default: from config; without a
        value there, the memory available when the run starts.
    threads_per_worker : int, optional
        Threads per loky worker process. Default: from config.
    on_group_written : Callable[[str], None], optional
        Called with the receiver-group name each time a group's data for one
        day finishes writing to Icechunk. Lets a caller drive its own
        progress display without this class owning any display itself.
    label : str, optional
        Free-text label of the run, stored in the run history.
    on_discovery_start : Callable[[str, Path], None], optional
        Called with the receiver name and its data folder when the run starts
        finding that receiver's files.
    on_discovery_end : Callable[[str, int, int, float], None], optional
        Called with the receiver name, the number of files found, the number
        of days and the elapsed seconds when the run has found them.
    on_new_files : Callable[[list[tuple[str, str]]], None], optional
        With ``new_files_only``, called with the ``(YYYYDOY, receiver)``
        pairs that have a file the GNSS store doesn't hold, before they are
        processed.
    on_incomplete_day : Callable[[str, str, int, int], None], optional
        Called with ``(receiver, YYYYDOY, files_found, files_expected)`` for
        each receiver-day to process that has fewer files than its file
        length gives for a whole day. Today is not checked.
    on_days_without_vod : Callable[[str, list[str]], None], optional
        Called with a receiver and the days in the range on which it has no
        files while its pair has: those days are not processed and get no
        VOD.

    A pipeline that is not a dry run is a run: it records itself in the run
    history of the log folder (ADR 0018) from its creation until
    :meth:`close` (or the end of its ``with`` block), and ends as failed
    with the error when processing raises.

    Examples
    --------
    >>> # From site object
    >>> site = Site("ExampleSite")
    >>> pipeline = Pipeline(site)

    >>> # Or directly from name
    >>> pipeline = Pipeline("ExampleSite")

    >>> # Process single date
    >>> data = pipeline.process_date("2025001")

    >>> # Process range
    >>> for date, datasets in pipeline.process_range("2025001", "2025007"):
    ...     print(f"Processed {date}")

    """

    @deprecate_no_effect_arguments
    @deprecated_argument(
        "days_per_batch",
        "The 'days_per_batch' argument of Pipeline() is left over from "
        "development and will be removed with the next major version. A run "
        "derives its days per unit from the memory budget; until then the "
        "argument caps them. Remove the argument.",
    )
    def __init__(
        self,
        site: Site | str,
        keep_vars: list[str] | None = None,
        aux_agency: str | None = None,
        n_workers: int | None = None,
        dry_run: bool = False,
        days_per_batch: int | None = None,
        max_memory_gb: float | None = None,
        cpu_affinity: list[int] | None = None,
        nice_priority: int | None = None,
        threads_per_worker: int | None = None,
        on_group_written: Callable[[str], None] | None = None,
        label: str | None = None,
        on_discovery_start: Callable[[str, Path], None] | None = None,
        on_discovery_end: Callable[[str, int, int, float], None] | None = None,
        on_new_files: Callable[[list[tuple[str, str]]], None] | None = None,
        on_incomplete_day: Callable[[str, str, int, int], None] | None = None,
        on_days_without_vod: Callable[[str, list[str]], None] | None = None,
    ) -> None:
        # Handle both Site object and string
        if isinstance(site, str):
            site = Site(site)

        self.site = site

        from canvod.config import load_config

        config = load_config()
        proc = config.processing.params

        # All params default to config values; explicit values override
        if keep_vars is None:
            keep_vars = proc.keep_gnss_observables
        if aux_agency is None:
            aux_agency = config.processing.aux_data.agency
        if max_memory_gb is None:
            max_memory_gb = proc.max_memory_gb

        # Resource resolution: explicit n_workers overrides everything,
        # otherwise use resolve_resources() which respects resource_mode.
        if n_workers is not None:
            # Caller explicitly set n_workers → manual-like behavior
            if threads_per_worker is None:
                threads_per_worker = proc.threads_per_worker
        else:
            # No explicit n_workers → use resource_mode from config
            resources = proc.resolve_resources()
            n_workers = resources["n_workers"]
            if threads_per_worker is None:
                threads_per_worker = resources["threads_per_worker"]

        self.keep_vars = keep_vars
        self.aux_agency = aux_agency
        self.n_workers = n_workers
        self.dry_run = dry_run
        # The deprecated cap on the days per unit, if any.
        self.days_per_batch = (
            days_per_batch if days_per_batch is not None else proc.days_per_batch
        )

        # Setup logging
        import structlog

        self.log = structlog.get_logger(__name__).bind(
            site=site.name,
            component="pipeline",
        )

        # Lazy import to avoid circular dependency
        from canvod.store_metadata import store_location
        from canvodpy.orchestrator import PipelineOrchestrator
        from canvodpy.run_history import recorded_run

        self._run = ExitStack()
        active_run = None
        if not dry_run:
            local_stores = {
                name: location.local_path
                for name, path in (
                    ("GNSS store", site.gnss_store_path),
                    ("VOD store", site.vod_store_path),
                )
                for location in [store_location(path)]
                if location.local_path is not None
            }
            active_run = self._run.enter_context(
                recorded_run(
                    site.name,
                    log_dir=config.processing.logging.get_log_dir(),
                    settings=config.model_dump(mode="json"),
                    workers=n_workers,
                    # Free disk of local stores only; S3 has no disk here.
                    disks=list(local_stores.values()),
                    # The on-disk size of each local store, measured in the
                    # background; a store on S3 has no local size to record.
                    stores=local_stores,
                    label=label,
                )
            )
        try:
            # Use proven orchestrator implementation
            with _forwarded_days_per_batch():
                self._orchestrator = PipelineOrchestrator(
                    site=site._site,
                    n_max_workers=n_workers,
                    dry_run=dry_run,
                    max_memory_gb=max_memory_gb,
                    threads_per_worker=threads_per_worker,
                    on_group_written=on_group_written,
                    on_discovery_start=on_discovery_start,
                    on_discovery_end=on_discovery_end,
                    on_new_files=on_new_files,
                    on_incomplete_day=on_incomplete_day,
                    on_days_without_vod=on_days_without_vod,
                    config=config,
                    run=active_run,
                    **_passed(days_per_batch=days_per_batch),
                )
        except Exception:
            self._run.__exit__(*sys.exc_info())
            raise

        self.log.info(
            "pipeline_initialized",
            aux_agency=aux_agency,
            n_workers=n_workers,
            keep_vars=len(self.keep_vars),
            dry_run=dry_run,
            threads_per_worker=threads_per_worker,
        )

    @property
    def failed_receiver_days(self) -> tuple[tuple[str, str], ...]:
        """Receiver-days of this run that failed.

        ``(receiver, YYYYDOY)`` pairs, empty while every receiver-day is
        written or skipped. ``canvodpy run`` exits with code 3 when a run
        has any; the log says why each one failed.
        """
        return self._orchestrator.failed_receiver_days

    def close(self) -> None:
        """End the run and release orchestrator resources.

        loky's reusable executor is shared and left running.
        """
        self._orchestrator.close()
        self._run.close()

    def __enter__(self) -> Pipeline:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._orchestrator.close()
        self._run.__exit__(exc_type, exc, tb)

    def _fail(self) -> None:
        """End the run as failed with the exception being handled."""
        self._run.__exit__(*sys.exc_info())

    def process_date(self, date: str) -> dict[str, xr.Dataset]:
        """Process RINEX data for one date.

        Parameters
        ----------
        date : str
            Date in YYYYDOY format (e.g., "2025001" for Jan 1, 2025)

        Returns
        -------
        dict[str, xr.Dataset]
            Processed datasets for each receiver

        Examples
        --------
        >>> pipeline = Pipeline("ExampleSite")
        >>> data = pipeline.process_date("2025001")
        >>> print(data.keys())
        dict_keys(['canopy_01', 'canopy_02', 'reference_01'])

        >>> # Access individual receiver
        >>> canopy_data = data['canopy_01']
        >>> print(canopy_data.dims)
        Dimensions: (epoch: 2880, sv: 32, ...)

        """
        log = self.log.bind(date=date)
        log.info("date_processing_started")

        # Use proven orchestrator logic
        try:
            for _date_key, datasets, _timing in self._orchestrator.process_by_date(
                keep_vars=self.keep_vars,
                start_from=date,
                end_at=date,
            ):
                log.info(
                    "date_processing_complete",
                    receivers=len(datasets),
                    receiver_names=list(datasets.keys()),
                )
                return datasets  # Return first (only) date
        except Exception:
            self._fail()
            raise

        log.warning("no_data_processed", date=date)
        return {}  # No data processed

    def process_range(
        self,
        start: str,
        end: str,
        *,
        new_files_only: bool = False,
    ) -> Generator[tuple[str, dict[str, xr.Dataset]]]:
        """Process RINEX data for a date range.

        Parameters
        ----------
        start : str
            Start date (YYYYDOY)
        end : str
            End date (YYYYDOY)
        new_files_only : bool, default False
            Process only the dates on which a receiver has a file the GNSS
            store doesn't hold (by canonical file name); a run without
            dates uses this (#386).

        Yields
        ------
        tuple[str, dict[str, xr.Dataset]]
            (date_key, datasets) for each processed date

        Examples
        --------
        >>> pipeline = Pipeline("ExampleSite")
        >>> for date, datasets in pipeline.process_range("2025001", "2025007"):
        ...     print(f"Processed {date}: {len(datasets)} receivers")
        Processed 2025001: 3 receivers
        Processed 2025002: 3 receivers
        ...

        """
        # Use proven orchestrator logic
        try:
            for date_key, datasets, _timing in self._orchestrator.process_by_date(
                keep_vars=self.keep_vars,
                start_from=start,
                end_at=end,
                new_files_only=new_files_only,
            ):
                yield date_key, datasets
        except Exception:
            self._fail()
            raise

    def run(
        self,
        start: str | None = None,
        end: str | None = None,
        *,
        new_files_only: bool = False,
        vod_analyses: Sequence[str] | None = None,
        calculator: str = "tau_omega",
    ) -> Generator[RunUnit]:
        """Store the days from ``start`` to ``end``, then compute their VOD.

        The run of ``canvodpy run`` (ADR 0021). The GNSS phase stores the
        days in units of days and reads nothing back; after each unit, the
        VOD phase computes the VOD of its days in the same worker pool,
        from the GNSS store, and commits once (``VodComputer.compute_days``).
        Meanwhile, the GNSS phase works on the next unit. A day that failed
        gets no VOD and stays open for the next run.

        Parameters
        ----------
        start, end : str, optional
            First and last day (YYYYDOY). ``None`` runs every day with files.
        new_files_only : bool, default False
            As :meth:`process_range`.
        vod_analyses : sequence of str, optional
            The VOD analyses to compute; all the site's by default. An
            empty sequence computes no VOD.
        calculator : str, default "tau_omega"
            The registered VOD calculator.

        Yields
        ------
        RunUnit
            Per unit, once its VOD is committed: the days stored and what
            the VOD phase did. A failing VOD phase is logged and reported
            in ``RunUnit.vod_error``; the run goes on.

        Examples
        --------
        >>> with Site("ExampleSite").pipeline() as pipeline:
        ...     for unit in pipeline.run("2025001", "2025007"):
        ...         print(sorted(unit.days), unit.vod.written)
        """
        from canvod.utils.tools import YYYYDOY
        from canvodpy.vod_computer import VodComputer

        analyses = list(
            self.site.vod_analyses if vod_analyses is None else vod_analyses
        )
        vod_computer = VodComputer(self.site, calculator=calculator)
        try:
            units = self._orchestrator.store_by_unit(
                start_from=start, end_at=end, new_files_only=new_files_only
            )
            while True:
                t_gnss = time.perf_counter()
                days = next(units, None)
                if days is None:
                    return
                unit = RunUnit(days=days, gnss_seconds=time.perf_counter() - t_gnss)
                if analyses:
                    t_vod = time.perf_counter()
                    try:
                        unit.vod = vod_computer.compute_days(
                            [YYYYDOY.from_str(day).date for day in days],
                            analyses,
                            unit_days=len(days),
                            executor=self._orchestrator.worker_pool(),
                        )
                    except Exception as exc:
                        # The days keep their GNSS data; the next run says
                        # which days have no VOD (vod-reconcile).
                        self.log.exception("vod_failed", days=sorted(days))
                        unit.vod_error = exc
                    unit.vod_seconds = time.perf_counter() - t_vod
                yield unit
        except Exception:
            self._fail()
            raise

    @deprecated(
        "Pipeline.calculate_vod() is left over from development and will be "
        "removed with the next major version. Use "
        "canvodpy.Site(<site>).vod.compute_bulk(<analysis>, start=..., end=...) "
        "instead."
    )
    def calculate_vod(
        self,
        canopy: str,
        reference: str,
        date: str,
        write_to_store: bool = True,
    ) -> xr.Dataset:
        """Calculate VOD for a receiver pair on one day.

        Delegates to ``Site.vod.compute_bulk()`` for the configured analysis
        of this canopy/reference pair, restricted to the given day.

        Parameters
        ----------
        canopy : str
            Canopy receiver name (e.g., "canopy_01")
        reference : str
            Reference receiver name (e.g., "reference_01")
        date : str
            Date in YYYYDOY format
        write_to_store : bool, default True
            If True, write the result to the VOD store.

        Returns
        -------
        xr.Dataset
            VOD analysis results

        """
        return _vod_for_day(self.site, canopy, reference, date, write_to_store)

    def preview(
        self,
        start: str | None = None,
        end: str | None = None,
        *,
        new_files_only: bool = False,
    ) -> dict:
        """Preview processing plan without execution.

        Parameters
        ----------
        start : str, optional
            YYYYDOY string to start from (inclusive). ``None`` previews
            every available date.
        end : str, optional
            YYYYDOY string to end at (inclusive). ``None`` previews every
            available date.
        new_files_only : bool, default False
            Preview only the dates on which a receiver has a file the GNSS
            store doesn't hold, as :meth:`process_range`.

        Returns
        -------
        dict
            Summary of dates, receivers, and files

        Examples
        --------
        >>> pipeline = Pipeline("ExampleSite")
        >>> plan = pipeline.preview(start="2025001", end="2025003")
        >>> print(f"Total files: {plan['total_files']}")

        """
        return self._orchestrator.preview_processing_plan(
            start, end, new_files_only=new_files_only
        )

    def __repr__(self) -> str:
        return (
            f"Pipeline(site='{self.site.name}', "
            f"keep_vars={len(self.keep_vars)} vars, "
            f"workers={self.n_workers}, "
            f"days_per_batch={self.days_per_batch})"
        )


def _vod_for_day(
    site: Site,
    canopy: str,
    reference: str,
    date: str,
    write: bool,
) -> xr.Dataset:
    """Compute one day of VOD for a canopy/reference pair via ``site.vod``.

    Backs the deprecated ``Pipeline.calculate_vod()`` and
    ``canvodpy.calculate_vod()``.
    """
    import datetime

    from canvod.utils.tools.date_utils import YYYYDOY

    analysis_name = next(
        (
            name
            for name, cfg in site.vod_analyses.items()
            if cfg.canopy_receiver == canopy and cfg.reference_receiver == reference
        ),
        None,
    )
    if analysis_name is None:
        raise ValueError(
            f"No VOD analysis configured for canopy {canopy!r} and reference "
            f"{reference!r}. Configured analyses: {list(site.vod_analyses)}"
        )

    day = YYYYDOY.from_str(date).date
    if day is None:
        raise ValueError(f"Could not parse date from {date!r}")
    start = datetime.datetime.combine(day, datetime.time())
    end = start + datetime.timedelta(days=1) - datetime.timedelta(microseconds=1)

    return site.vod.compute_bulk(analysis_name, start=start, end=end, write=write)


# ============================================================================
# Deprecated convenience functions — use Site.pipeline() instead
# ============================================================================


@deprecated(
    "canvodpy.process_date() is left over from development and will be removed with the next major version. "
    "Use canvodpy.Site(<site>).pipeline().process_date(<date>) or the "
    "terminal command `canvodpy run` instead."
)
def process_date(
    site: str,
    date: str,
    keep_vars: list[str] | None = None,
    aux_agency: str | None = None,
    n_workers: int | None = None,
) -> dict[str, xr.Dataset]:
    """Process RINEX data for one date (convenience function).

    This is the simplest way to process GNSS data - just provide
    the site name and date. All optional parameters default to
    values from the ``processing:`` section of
    ``config/canvod-settings.yaml``.

    Parameters
    ----------
    site : str
        Site name (e.g., "ExampleSite")
    date : str
        Date in YYYYDOY format (e.g., "2025001")
    keep_vars : list[str], optional
        RINEX variables to keep. Default: from config.
    aux_agency : str, optional
        Analysis center for auxiliary data. Default: from config.
    n_workers : int, optional
        Number of parallel workers. Default: from config.

    Returns
    -------
    dict[str, xr.Dataset]
        Processed datasets for each receiver

    Examples
    --------
    >>> from canvodpy import process_date
    >>> data = process_date("ExampleSite", "2025001")
    >>> print(data.keys())
    dict_keys(['canopy_01', 'canopy_02', 'reference_01'])

    >>> # With custom settings
    >>> data = process_date(
    ...     "ExampleSite",
    ...     "2025001",
    ...     keep_vars=["C1C", "L1C"],
    ...     aux_agency="ESA"
    ... )

    """
    with Pipeline(
        site=site,
        keep_vars=keep_vars,
        aux_agency=aux_agency,
        n_workers=n_workers,
    ) as pipeline:
        return pipeline.process_date(date)


@deprecated(
    "canvodpy.calculate_vod() is left over from development and will be removed with the next major version. "
    "Use the terminal command `canvodpy run` instead, or process the day "
    "with canvodpy.Site(<site>).pipeline().process_date(<date>) and compute "
    "VOD with canvodpy.Site(<site>).vod.compute_bulk(<analysis>, "
    "start=..., end=...)."
)
def calculate_vod(
    site: str,
    canopy: str,
    reference: str,
    date: str,
    keep_vars: list[str] | None = None,
    aux_agency: str | None = None,
    write_to_store: bool = True,
) -> xr.Dataset:
    """Calculate VOD for a receiver pair on one day (convenience function).

    Computes VOD from the site's GNSS store via ``Site.vod.compute_bulk()``
    for the configured analysis of this canopy/reference pair. The day must
    already be processed into the GNSS store.

    Parameters
    ----------
    site : str
        Site name
    canopy : str
        Canopy receiver name
    reference : str
        Reference receiver name
    date : str
        Date in YYYYDOY format
    keep_vars : list[str], optional
        Unused. VOD is computed from the stored data.
    aux_agency : str, optional
        Unused. VOD is computed from the stored data.
    write_to_store : bool, default True
        If True, write the result to the VOD store.

    Returns
    -------
    xr.Dataset
        VOD analysis results

    Examples
    --------
    >>> from canvodpy import calculate_vod
    >>> vod = calculate_vod(
    ...     site="ExampleSite",
    ...     canopy="canopy_01",
    ...     reference="reference_01",
    ...     date="2025001"
    ... )
    >>> print(vod.vod.mean().values)
    0.42

    """
    return _vod_for_day(Site(site), canopy, reference, date, write_to_store)


@deprecated(
    "canvodpy.preview_processing() is left over from development and will be removed with the next major version. "
    "Use canvodpy.Site(<site>).pipeline(dry_run=True).preview() instead."
)
def preview_processing(site: str) -> dict:
    """Preview processing plan for a site (convenience function).

    Parameters
    ----------
    site : str
        Site name

    Returns
    -------
    dict
        Processing plan summary

    Examples
    --------
    >>> from canvodpy import preview_processing
    >>> plan = preview_processing("ExampleSite")
    >>> print(f"Total files: {plan['total_files']}")
    Total files: 8640

    """
    with Pipeline(site, dry_run=True) as pipeline:
        return pipeline.preview()
