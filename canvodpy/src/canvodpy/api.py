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

from typing import TYPE_CHECKING

from canvod.utils.tools import deprecated
from canvodpy.orchestrator.resources import deprecate_no_effect_arguments

# Lazy imports to avoid circular dependencies

if TYPE_CHECKING:
    from collections.abc import Callable, Generator
    from pathlib import Path

    import xarray as xr

    from canvod.store import MyIcechunkStore
    from canvodpy.vod_computer import VodComputer


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
    def gnss_store_path(self) -> Path:
        """Where the site's GNSS store is, from the settings; read-only."""
        return self._site.gnss_store_path

    @property
    def vod_store_path(self) -> Path:
        """Where the site's VOD store is, from the settings; read-only."""
        return self._site.vod_store_path

    @deprecate_no_effect_arguments
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
        days_per_batch : int, optional
            Number of DOYs per loky wave. Default: from config.
        threads_per_worker : int, optional
            Threads per worker process. Default: from config.
        on_group_written : Callable[[str], None], optional
            Called with the receiver-group name each time a group's data for
            one day finishes writing to Icechunk. Lets a caller drive its own
            progress display (e.g. the CLI's per-site/receiver rows) without
            this class owning any display itself.

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
        return Pipeline(
            site=self,
            keep_vars=keep_vars,
            aux_agency=aux_agency,
            n_workers=n_workers,
            dry_run=dry_run,
            days_per_batch=days_per_batch,
            threads_per_worker=threads_per_worker,
            on_group_written=on_group_written,
        )

    def __repr__(self) -> str:
        n_receivers = len(self.active_receivers)
        n_analyses = len(self.vod_analyses)
        return f"Site('{self.name}', receivers={n_receivers}, analyses={n_analyses})"

    def __str__(self) -> str:
        return f"GNSS Site: {self.name}"


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
    days_per_batch : int, optional
        Calendar days to pool per processing wave. Default: from config.
    threads_per_worker : int, optional
        Threads per loky worker process. Default: from config.
    on_group_written : Callable[[str], None], optional
        Called with the receiver-group name each time a group's data for one
        day finishes writing to Icechunk. Lets a caller drive its own
        progress display without this class owning any display itself.

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
        if days_per_batch is None:
            days_per_batch = proc.days_per_batch

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
        self.days_per_batch = days_per_batch

        # Setup logging
        import structlog

        self.log = structlog.get_logger(__name__).bind(
            site=site.name,
            component="pipeline",
        )

        # Lazy import to avoid circular dependency
        from canvodpy.orchestrator import PipelineOrchestrator

        # Use proven orchestrator implementation
        self._orchestrator = PipelineOrchestrator(
            site=site._site,
            n_max_workers=n_workers,
            dry_run=dry_run,
            days_per_batch=days_per_batch,
            threads_per_worker=threads_per_worker,
            on_group_written=on_group_written,
            config=config,
        )

        self.log.info(
            "pipeline_initialized",
            aux_agency=aux_agency,
            n_workers=n_workers,
            keep_vars=len(self.keep_vars),
            dry_run=dry_run,
            days_per_batch=days_per_batch,
            threads_per_worker=threads_per_worker,
        )

    def close(self) -> None:
        """Release orchestrator resources (loky's reusable executor is shared and left running)."""
        self._orchestrator.close()

    def __enter__(self) -> Pipeline:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

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

        log.warning("no_data_processed", date=date)
        return {}  # No data processed

    def process_range(
        self,
        start: str,
        end: str,
    ) -> Generator[tuple[str, dict[str, xr.Dataset]]]:
        """Process RINEX data for a date range.

        Parameters
        ----------
        start : str
            Start date (YYYYDOY)
        end : str
            End date (YYYYDOY)

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
        for date_key, datasets, _timing in self._orchestrator.process_by_date(
            keep_vars=self.keep_vars,
            start_from=start,
            end_at=end,
        ):
            yield date_key, datasets

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
        return self._orchestrator.preview_processing_plan(start, end)

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
