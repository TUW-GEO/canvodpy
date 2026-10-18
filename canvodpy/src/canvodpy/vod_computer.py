"""VOD computation and storage for a site: the single VOD implementation.

Every entry point computes and stores VOD through this class: the Python
``site.vod`` object, ``canvodpy run`` (per day, during processing),
``canvodpy vod`` and ``canvodpy vod-reconcile`` (from the GNSS store).

- ``compute_day()`` / ``compute_day_all()`` — from the per-day datasets
  yielded by ``Pipeline.process_range()``. Loads them into memory, then
  computes.
- ``compute_days()``: from the site's GNSS Icechunk store, the VOD phase
  (ADR 0021): one task per analysis pair and day in the worker pool, one
  commit per unit of days (:mod:`canvodpy.orchestrator.vod_phase`).
  ``canvodpy vod`` and ``canvodpy vod-reconcile`` use it.
- ``compute_bulk()`` / ``compute_bulk_all()``: from the site's GNSS
  Icechunk store, returning the VOD. They write with ``compute_days()`` and
  read the VOD back; without writing, they read the full (or filtered) time
  range into memory, drop duplicate epochs, sort, then compute.

All of them compute with :func:`compute_vod` (the calculator, which aligns
canopy and reference on their shared epochs and signals). ``compute_day()``
and ``compute_day_all()`` write with ``_write()`` (one commit per day for all
analyses written together, after the VOD store metadata).
``canvodpy run`` adds only terminal conveniences: it skips a failing
analysis instead of raising, and retries the store write on transient
errors.

Examples
--------
Per day (inside a processing loop)::

    vod = VodComputer(site)

    with site.pipeline() as pipeline:
        for date_key, datasets in pipeline.process_range(...):
            vod.compute_day_all(datasets)

Days from the GNSS store, in the worker pool::

    vod = VodComputer(site)
    report = vod.compute_days(days, ["canopy_01_vs_reference_01"])

Custom calculator::

    vod = VodComputer(site, calculator="dual_freq_vod")
    vod.compute_day(datasets, "canopy_01_vs_reference_01")
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from concurrent.futures import Executor
from datetime import datetime
from typing import TYPE_CHECKING, Any

import structlog

from canvod.config.models import (
    PREPROCESSING_ATTR,
    vod_preprocessing_record,
)
from canvod.utils.tools import deprecated

if TYPE_CHECKING:
    import xarray as xr

    from canvod.config.models import ProcessingParams
    from canvodpy.api import Site
    from canvodpy.orchestrator.vod_phase import VodUnitReport


def ensure_vod_store_metadata(
    site: Site, calculator_name: str, analyses: list[str]
) -> None:
    """Give a new VOD store its metadata; refuse unlisted VOD analyses.

    Call it before the VOD write, so the VOD store never holds data
    without its repository metadata (ADR 0014). Every commit then writes
    the store's root copy and snapshot summary itself. A VOD store records
    the content-settings hash of the GNSS store it is computed from
    (ADR 0019, D1).

    Raises
    ------
    ValueError
        If the site is not in the settings, the store predates repository
        metadata (names the migrate command), or a VOD analysis is not
        listed in it (names the amend command).
    """
    from canvod.config import load_config
    from canvod.store_metadata import (
        ensure_store_metadata,
        read_repository_metadata,
    )

    ensure_store_metadata(
        site.vod_store_path,
        config=load_config(),
        site_name=site.name,
        store_type="vod_store",
        source_format=calculator_name,
        names=analyses,
        gnss_repository=read_repository_metadata(site._site.gnss_store.store_path),
    )


def _vod_pool(params: ProcessingParams) -> Executor:
    """The worker pool of the VOD phase run alone, with the run's settings."""
    from loky import get_reusable_executor

    from canvod.utils.logging import get_run_id
    from canvodpy.logging.logging_config import active_log_dir
    from canvodpy.orchestrator.processor import _worker_init_with_run_id

    resources = params.resolve_resources()
    return get_reusable_executor(
        max_workers=resources["n_workers"],
        timeout=900,
        initializer=_worker_init_with_run_id,
        initargs=(
            resources["nice_priority"],
            resources["cpu_affinity"],
            get_run_id(),
            active_log_dir(),
        ),
    )


def compute_vod(
    canopy_ds: xr.Dataset,
    sky_ds: xr.Dataset,
    *,
    analysis_name: str,
    canopy_receiver: str,
    reference_receiver: str,
    calculator: str,
    calculator_params: Mapping[str, Any],
    store_delta_snr: bool,
    store_radial_diff: bool,
) -> xr.Dataset:
    """The VOD of one analysis pair, with the optional outputs.

    The calculator aligns both datasets on their shared epochs and
    signals. ``store_delta_snr`` keeps ``delta_snr`` (dropped otherwise);
    ``store_radial_diff`` adds ``radial_diff`` (canopy minus reference
    slant range, needs ``r`` from ``store_radial_distance`` at ingest).
    Runs in the main process (:class:`VodComputer`) and in the workers of
    the VOD phase (:mod:`canvodpy.orchestrator.vod_phase`).
    """
    from canvodpy.factories import VODFactory

    vod_calculator = VODFactory.create(
        calculator, canopy_ds=canopy_ds, sky_ds=sky_ds, **calculator_params
    )
    vod_ds = vod_calculator.calculate_vod()
    if not store_delta_snr:
        vod_ds = vod_ds.drop_vars("delta_snr", errors="ignore")
    if store_radial_diff:
        aligned_canopy, aligned_sky = vod_calculator.canopy_ds, vod_calculator.sky_ds
        if "r" in aligned_canopy and "r" in aligned_sky:
            radial_diff = aligned_canopy["r"] - aligned_sky["r"]
            radial_diff.attrs["units"] = "m"
            radial_diff.attrs["long_name"] = (
                "radial distance difference (canopy − reference)"
            )
            vod_ds["radial_diff"] = radial_diff
        else:
            structlog.get_logger(__name__).warning(
                "radial_diff_unavailable",
                reason=(
                    "store_radial_diff=true but 'r' not present in receiver "
                    "data; set store_radial_distance=true at ingest time"
                ),
            )
    vod_ds.attrs["analysis_name"] = analysis_name
    vod_ds.attrs["canopy_receiver"] = canopy_receiver
    vod_ds.attrs["reference_receiver"] = reference_receiver
    vod_ds.attrs["calculator"] = calculator
    return vod_ds


class VodComputer:
    """Compute VOD for a site's configured analyses and write it to the VOD store.

    Parameters
    ----------
    site : Site
        Site object providing access to stores and configuration.
    calculator : str
        Registered VOD calculator name (default ``"tau_omega"``).
        Future calculators register via ``VODFactory.register()``.
    rechunk : dict, optional
        Chunk specification for VOD output before writing.
        Default: ``{"epoch": 17280, "sid": -1}``.
    """

    def __init__(
        self,
        site: Site,
        calculator: str = "tau_omega",
        calculator_params: dict | None = None,
        rechunk: dict[str, int] | None = None,
    ) -> None:
        self._site = site
        self._calculator_name = calculator
        self._calculator_params = calculator_params
        self._rechunk = rechunk or {"epoch": 17280, "sid": -1}
        self.log = structlog.get_logger(__name__).bind(
            site=site.name, calculator=calculator
        )

    @property
    def calculator_name(self) -> str:
        """Registered name of the VOD calculator in use."""
        return self._calculator_name

    @property
    def calculator_params(self) -> dict:
        """The calculator parameters in effect, as the store records them."""
        return self._effective_calculator_params()

    def _effective_calculator_params(self) -> dict[str, Any]:
        """The calculator parameters in effect, defaults written out.

        The parameters are the calculator model's fields other than
        ``canopy_ds`` and ``sky_ds``, with their defaults written out
        (``{}`` for ``tau_omega`` today). Passed parameters are merged
        over the defaults, so ``{\"a\": 1}`` and ``{\"a\": 1, \"b\": 2}``
        (with ``b`` defaulting to 2) compute and record the same thing.

        Raises
        ------
        ValueError
            If a parameter field has no default (``PydanticUndefined``):
            it must be given in the configuration.
        """
        from pydantic_core import PydanticUndefined

        from canvodpy.factories import VODFactory

        cls = VODFactory.component_class(self._calculator_name)
        base = {"canopy_ds", "sky_ds"}
        defaults: dict[str, Any] = {}
        for name, field in cls.model_fields.items():
            if name in base:
                continue
            if field.default is PydanticUndefined:
                msg = (
                    f"The VOD calculator {self._calculator_name!r} has a "
                    f"required parameter {name!r} without a default. Give "
                    "it in the configuration (vod.calculators)."
                )
                raise ValueError(msg)
            defaults[name] = field.default
        if self._calculator_params is None:
            return defaults
        return {**defaults, **self._calculator_params}

    @deprecated(
        "`check_preprocessing` is left over from development: the VOD write now "
        "checks the content-settings hash of the GNSS store the VOD is computed "
        "from (check_gnss_hash), and each group's preprocessing is compared at "
        "write time. It will be removed with the next major version. Use "
        "check_gnss_hash instead."
    )
    def check_preprocessing(self, analysis_names: list[str]) -> None:
        """Refuse a run before processing if a VOD group holds other preprocessing.

        Compares ``processing.preprocessing`` with the GNSS preprocessing
        behind the results in each analysis's VOD store group
        (``{calculator}/{analysis}``). :meth:`write_day` compares again at
        write time; this check stops a run before it processes any data,
        e.g. when a new GNSS store with other settings would feed an
        existing VOD store.

        Raises
        ------
        PreprocessingMismatchError
            If a group holds results of data preprocessed differently.
        """
        from canvod.config import load_config
        from canvod.ops import planned_settings
        from canvod.store_metadata import store_exists

        if not store_exists(self._site.vod_store_path):
            return  # a first run: no results yet to compare with
        settings = planned_settings(load_config().processing.preprocessing)
        vod_store = self._site._site.vod_store
        for analysis_name in analysis_names:
            vod_store.check_settings_match(
                f"{self._calculator_name}/{analysis_name}", settings
            )

    def check_gnss_hash(self) -> None:
        """Refuse a VOD write from a GNSS store with other content settings.

        A VOD store records the content-settings hash of the GNSS store it
        was computed from (``gnss_content_hash``, ADR 0019 D1/D3). A run
        whose GNSS store has a different content-settings hash would compute
        VOD from data this VOD store does not describe, so it stops before
        anything is written.

        Raises
        ------
        MissingContentSettingsError
            If the GNSS store has no content settings, or the VOD store
            records no ``gnss_content_hash``.
        ContentSettingsError
            If the GNSS store's content-settings hash differs from the VOD
            store's (the error names both hashes and both stores).
        """
        from canvod.store_metadata import (
            check_gnss_hash,
            read_repository_metadata,
            store_exists,
        )

        if not store_exists(self._site.vod_store_path):
            return  # a first run: the store is created with this GNSS store
        check_gnss_hash(
            read_repository_metadata(self._site.vod_store_path),
            read_repository_metadata(self._site._site.gnss_store.store_path),
            self._site.vod_store_path,
        )

    def compute_day(
        self,
        datasets: dict[str, xr.Dataset],
        analysis_name: str,
        *,
        write: bool = True,
    ) -> xr.Dataset:
        """Compute VOD for one analysis from per-day datasets.

        Materializes Dask-backed datasets into memory via ``.load()``,
        then computes VOD single-threaded.

        Parameters
        ----------
        datasets : dict[str, xr.Dataset]
            Per-receiver datasets keyed by store group name (e.g. from
            ``process_range()``).  May be Dask-backed.
        analysis_name : str
            Configured VOD analysis name (e.g. ``"canopy_01_vs_reference_01"``).
        write : bool
            If ``True`` (default), write result to the VOD store.

        Returns
        -------
        xr.Dataset
            Computed VOD dataset.

        Raises
        ------
        KeyError
            If the required receiver groups are not in ``datasets``.
        ValueError
            If ``analysis_name`` is not configured.
        """
        vod_ds = self._compute_from_datasets(datasets, analysis_name)
        if write:
            self.write_day(datasets, {analysis_name: vod_ds})
        return vod_ds

    def compute_day_all(
        self,
        datasets: dict[str, xr.Dataset],
        *,
        write: bool = True,
    ) -> dict[str, xr.Dataset]:
        """Compute VOD for every configured analysis from per-day datasets.

        All results are written together, in one commit.

        Parameters
        ----------
        datasets : dict[str, xr.Dataset]
            Per-receiver datasets keyed by store group name (e.g. from
            ``process_range()``).  May be Dask-backed.
        write : bool
            If ``True`` (default), write the results to the VOD store.

        Returns
        -------
        dict[str, xr.Dataset]
            VOD dataset per analysis name.

        Raises
        ------
        KeyError
            If a required receiver group is not in ``datasets``.
        """
        results = {
            name: self._compute_from_datasets(datasets, name)
            for name in self._site.vod_analyses
        }
        if write and results:
            self.write_day(datasets, results)
        return results

    def write_day(
        self,
        datasets: dict[str, xr.Dataset],
        results: dict[str, xr.Dataset],
    ) -> dict[str, Any]:
        """Write VOD results computed from ``datasets`` in one commit.

        Parameters
        ----------
        datasets : dict[str, xr.Dataset]
            The per-day datasets the results were computed from; their
            epochs select the GNSS files recorded as the VOD's sources.
        results : dict[str, xr.Dataset]
            VOD dataset per analysis name, e.g. from
            ``compute_day(..., write=False)``.

        Returns
        -------
        dict[str, VodWriteResult]
            Store write result per ``{calculator}/{analysis}`` group.
        """
        entries = []
        for name, vod_ds in results.items():
            canopy_ds, sky_ds = self._aligned_pair(datasets, name)
            entries.append((name, vod_ds, canopy_ds, sky_ds))
        return self._write(entries)

    def compute_bulk(
        self,
        analysis_name: str,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        write: bool = True,
    ) -> xr.Dataset:
        """Compute VOD from the GNSS Icechunk store.

        With ``write`` (the default), the days from ``start`` to ``end``
        go through :meth:`compute_days`: the worker pool, one commit per
        unit of days, and no new computation for a day the VOD store holds
        from the same GNSS files. Whole days are written; the VOD from
        ``start`` to ``end`` is then read back from the VOD store. Without
        ``write``, the canopy and reference groups are read into memory
        from ``start`` to ``end`` and the VOD is computed there; nothing is
        written.

        Parameters
        ----------
        analysis_name : str
            Configured VOD analysis name.
        start : datetime, optional
            Start of time range filter.
        end : datetime, optional
            End of time range filter.
        write : bool
            If ``True`` (default), write result to the VOD store.

        Returns
        -------
        xr.Dataset
            Computed VOD dataset.

        Raises
        ------
        ValueError
            With ``write``, if the GNSS store has no day of the analysis
            from ``start`` to ``end``.
        """
        if write:
            return self._compute_and_read_back([analysis_name], start, end)[
                analysis_name
            ]
        vod_ds, _, _ = self._compute_bulk_entry(analysis_name, start, end)
        return vod_ds

    def compute_days(
        self,
        days: Sequence[Any],
        analyses: Sequence[str] | None = None,
        *,
        unit_days: int | None = None,
        executor: Executor | None = None,
    ) -> VodUnitReport:
        """Compute the VOD of ``days`` in the worker pool and write it (ADR 0021).

        One task per analysis pair and day reads the day from the GNSS
        store's committed snapshot and writes its VOD into a fork of the VOD
        store; the forks of a unit of days are committed once
        (:mod:`canvodpy.orchestrator.vod_phase`). A day whose VOD the store
        holds from the same GNSS files is not computed again; a day without
        data in a group of its pair is skipped and reported.

        Parameters
        ----------
        days : sequence of date-like
            The days to compute, in any order.
        analyses : sequence of str, optional
            Configured VOD analyses; all of the site's by default.
        unit_days : int, optional
            Most days committed together; ``VOD_UNIT_DAYS`` by default.
        executor : concurrent.futures.Executor, optional
            The worker pool; by default one with the run's worker settings
            (``processing.params``).

        Returns
        -------
        VodUnitReport
            The days written, stored before, and missing, per analysis.
        """
        import numpy as np

        from canvod.config import load_config
        from canvodpy.orchestrator.vod_phase import (
            VOD_UNIT_DAYS,
            VodPair,
            VodPhase,
            VodUnitReport,
            units,
        )

        names = list(analyses or self._site.vod_analyses)
        pairs = []
        for name in names:
            cfg = self._get_analysis_config(name)
            pairs.append(
                VodPair(
                    analysis=name,
                    canopy_receiver=cfg.canopy_receiver,
                    reference_receiver=cfg.reference_receiver,
                    canopy_group=cfg.canopy_receiver,
                    reference_group=cfg.reference_store_group,
                )
            )
        self.check_gnss_hash()
        ensure_vod_store_metadata(self._site, self._calculator_name, names)
        params = load_config().processing.params
        research_site = self._site._site
        pool = executor if executor is not None else _vod_pool(params)
        phase = VodPhase(
            gnss_store=research_site.gnss_store,
            vod_store=research_site.vod_store,
            pairs=pairs,
            calculator=self._calculator_name,
            calculator_params=self._effective_calculator_params(),
            store_delta_snr=params.store_delta_snr,
            store_radial_diff=params.store_radial_diff,
            submit=pool.submit,
            log=self.log,
        )
        report = VodUnitReport()
        for unit in units(
            [np.datetime64(day, "D") for day in days], unit_days or VOD_UNIT_DAYS
        ):
            report.extend(phase.run_unit(unit))
        return report

    def gnss_days(
        self,
        analysis_name: str,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[Any]:
        """The days that have a block in a GNSS group of the analysis pair.

        In time order, from ``start`` to ``end`` (both days included) when
        given. Days of one group only are listed too: :meth:`compute_days`
        reports them as missing.
        """
        import numpy as np

        from canvod.store.day_blocks import day_blocks, holds_day_blocks

        analysis_cfg = self._get_analysis_config(analysis_name)
        days: set[Any] = set()
        with self._site._site.gnss_store.readonly_session() as session:
            for group in (
                analysis_cfg.canopy_receiver,
                analysis_cfg.reference_store_group,
            ):
                if holds_day_blocks(session.store, group):
                    days |= set(day_blocks(session.store, group))
        first = None if start is None else np.datetime64(start.date(), "D")
        last = None if end is None else np.datetime64(end.date(), "D")
        return sorted(
            day
            for day in days
            if (first is None or day >= first) and (last is None or day <= last)
        )

    def compute_bulk_all(
        self,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        write: bool = True,
    ) -> dict[str, xr.Dataset]:
        """Compute VOD for every configured analysis from the GNSS store.

        Same as ``compute_bulk()`` per analysis; with ``write``, the
        analyses' days go through one :meth:`compute_days` call, so the
        analyses of a unit of days share a commit.

        Parameters
        ----------
        start : datetime, optional
            Start of time range filter.
        end : datetime, optional
            End of time range filter.
        write : bool
            If ``True`` (default), write the results to the VOD store.

        Returns
        -------
        dict[str, xr.Dataset]
            VOD dataset per analysis name.

        Raises
        ------
        ValueError
            With ``write``, if the GNSS store has no day of an analysis
            from ``start`` to ``end``.
        """
        names = list(self._site.vod_analyses)
        if write:
            return self._compute_and_read_back(names, start, end) if names else {}
        return {name: self._compute_bulk_entry(name, start, end)[0] for name in names}

    def _compute_and_read_back(
        self,
        names: list[str],
        start: datetime | None,
        end: datetime | None,
    ) -> dict[str, xr.Dataset]:
        """Write the analyses' days with :meth:`compute_days`; read the VOD back.

        The days are those of the analyses' GNSS groups from ``start`` to
        ``end``; the VOD read back is that from ``start`` to ``end``.
        """
        import numpy as np

        from canvod.store.day_blocks import load_group

        days: set[Any] = set()
        for name in names:
            name_days = self.gnss_days(name, start, end)
            if not name_days:
                msg = (
                    f"The GNSS store of {self._site.name} has no day of "
                    f"analysis {name!r} from {start or 'its first day'} to "
                    f"{end or 'its last day'}."
                )
                raise ValueError(msg)
            days.update(name_days)
        self.compute_days(sorted(days), names)
        window = slice(
            None if start is None else np.datetime64(start, "ns"),
            None if end is None else np.datetime64(end, "ns"),
        )
        with self._site._site.vod_store.readonly_session() as session:
            return {
                name: load_group(
                    session.store,
                    f"{self._calculator_name}/{name}",
                    time_slice=window,
                    drop_empty=True,
                ).load()
                for name in names
            }

    # ------------------------------------------------------------------
    # Shared core
    # ------------------------------------------------------------------

    def _compute_bulk_entry(
        self,
        analysis_name: str,
        start: datetime | None,
        end: datetime | None,
    ) -> tuple[xr.Dataset, xr.Dataset, xr.Dataset]:
        """Read one analysis pair from the GNSS store and compute VOD.

        Returns the VOD dataset and the aligned canopy and reference inputs.
        """
        import xarray as xr

        log = self.log.bind(analysis=analysis_name)
        log.info("compute_bulk_started", start=str(start), end=str(end))

        analysis_cfg = self._get_analysis_config(analysis_name)
        canopy_name = analysis_cfg.canopy_receiver
        ref_group = analysis_cfg.reference_store_group

        store = self._site.gnss_store

        from canvod.store.day_blocks import load_group

        # load_group, not xr.open_zarr: it drops the padding of day blocks,
        # whose times canopy and reference groups share.
        with store.readonly_session() as session:
            canopy_ds = load_group(session.store, canopy_name)
            sky_ds = load_group(session.store, ref_group)

        # Time-range filter
        if start or end:
            canopy_ds = self._filter_time(canopy_ds, start, end)
            sky_ds = self._filter_time(sky_ds, start, end)

        # Deduplicate and sort by epoch
        canopy_ds = self._dedup_sort(canopy_ds)
        sky_ds = self._dedup_sort(sky_ds)

        canopy_ds, sky_ds = xr.align(canopy_ds.load(), sky_ds.load(), join="inner")

        log.info(
            "bulk_data_loaded",
            canopy_epochs=canopy_ds.sizes.get("epoch", 0),
            sky_epochs=sky_ds.sizes.get("epoch", 0),
        )

        vod_ds = self._compute(canopy_ds, sky_ds, analysis_name)
        return vod_ds, canopy_ds, sky_ds

    def _compute_from_datasets(
        self,
        datasets: dict[str, xr.Dataset],
        analysis_name: str,
    ) -> xr.Dataset:
        """Load one analysis pair from per-day datasets and compute VOD."""
        log = self.log.bind(analysis=analysis_name)
        canopy_ds, sky_ds = self._aligned_pair(datasets, analysis_name)

        # Materialize into memory (safe for single-day data ~1.5GB)
        canopy_ds = canopy_ds.load()
        sky_ds = sky_ds.load()

        log.info(
            "datasets_loaded",
            canopy_epochs=canopy_ds.sizes.get("epoch", 0),
            sky_epochs=sky_ds.sizes.get("epoch", 0),
        )
        return self._compute(canopy_ds, sky_ds, analysis_name)

    def _compute(
        self,
        canopy_ds: xr.Dataset,
        sky_ds: xr.Dataset,
        analysis_name: str,
    ) -> xr.Dataset:
        """Compute VOD with the configured calculator (:func:`compute_vod`)."""
        from canvod.config import load_config

        params = load_config().processing.params
        analysis_cfg = self._get_analysis_config(analysis_name)
        vod_ds = compute_vod(
            canopy_ds,
            sky_ds,
            analysis_name=analysis_name,
            canopy_receiver=analysis_cfg.canopy_receiver,
            reference_receiver=analysis_cfg.reference_receiver,
            calculator=self._calculator_name,
            calculator_params=self._effective_calculator_params(),
            store_delta_snr=params.store_delta_snr,
            store_radial_diff=params.store_radial_diff,
        )
        self.log.info(
            "vod_computed",
            analysis=analysis_name,
            variables=list(vod_ds.data_vars),
        )
        return vod_ds

    def _write(
        self,
        entries: list[tuple[str, xr.Dataset, xr.Dataset, xr.Dataset]],
    ) -> dict[str, Any]:
        """Write VOD results, one commit per day, after checking the store metadata.

        The results of all analyses for one day share a commit. When the
        GNSS groups of an analysis are day blocks, its VOD store group is
        too (ADR 0016), each day at the cadence of its GNSS data
        (:meth:`_gnss_cadences`); writing a day again replaces it.

        Parameters
        ----------
        entries : list of tuple
            ``(analysis_name, vod_ds, canopy_ds, sky_ds)`` per analysis;
            ``canopy_ds``/``sky_ds`` are the aligned inputs, whose epoch
            range selects the GNSS files recorded as sources.

        Returns
        -------
        dict[str, VodWriteResult]
            Store write result per ``{calculator}/{analysis}`` group, of
            the group's last day.
        """
        import numpy as np

        days = np.unique(
            np.concatenate(
                [vod_ds.epoch.values.astype("M8[D]") for _, vod_ds, *_ in entries]
            )
        )
        # Build every item first: that refuses receivers preprocessed
        # differently before anything touches the store.
        day_items = []
        for day in days:
            day_entries = []
            for name, vod_ds, canopy_ds, sky_ds in entries:
                vod_day = self._day_of(vod_ds, day)
                if vod_day.sizes["epoch"]:
                    day_entries.append(
                        (
                            name,
                            vod_day,
                            self._day_of(canopy_ds, day),
                            self._day_of(sky_ds, day),
                        )
                    )
            day_items.append(self._day_items(day, day_entries))

        ensure_vod_store_metadata(
            self._site, self._calculator_name, [name for name, *_ in entries]
        )
        results: dict[str, Any] = {}
        for items in day_items:
            results.update(self._site._site.store_vod_analyses_batch(items=items))
        for analysis_name, *_ in entries:
            self.log.info(
                "vod_written_to_store",
                analysis=analysis_name,
                model=self._calculator_name,
                days=len(day_items),
            )
        return results

    @staticmethod
    def _day_of(ds: xr.Dataset, day: Any) -> xr.Dataset:
        """The epochs of ``ds`` on ``day``, in the order they are stored."""
        import numpy as np

        return ds.isel(epoch=np.flatnonzero(ds.epoch.values.astype("M8[D]") == day))

    def _gnss_cadences(self, analysis_name: str, day: Any) -> dict[Any, float] | None:
        """Cadence of the VOD of ``day``: that of its GNSS day blocks.

        A VOD epoch is an epoch of both the canopy and the reference group,
        so each group's cadence gives every VOD epoch of the day its own
        slot; the coarser of the two gives the fewer slots. ``None`` when
        neither group exists.

        Raises
        ------
        LayoutError
            If a group of the analysis was written by appending (the GNSS
            store needs ``canvodpy store migrate-layout`` first), or has no
            block for ``day``.
        """
        from canvod.store.day_blocks import day_blocks, holds_day_blocks
        from canvod.store_metadata.io import store_command
        from canvod.store_metadata.layout import LayoutError

        analysis_cfg = self._get_analysis_config(analysis_name)
        groups = (analysis_cfg.canopy_receiver, analysis_cfg.reference_store_group)
        cadences = []
        gnss_store = self._site._site.gnss_store
        with gnss_store.readonly_session() as session:
            for group in groups:
                if not holds_day_blocks(session.store, group):
                    if not gnss_store.group_exists(group):
                        continue
                    command = store_command(
                        "migrate-layout", self._site.name, "gnss_store"
                    )
                    msg = (
                        f"GNSS group '{group}' was written by appending, so "
                        f"the VOD of {analysis_name} has no day blocks to "
                        f"follow. Move the GNSS store to day blocks first:\n"
                        f"  {command}"
                    )
                    raise LayoutError(msg)
                blocks = day_blocks(session.store, group)
                if day not in blocks:
                    msg = (
                        f"GNSS group '{group}' has no block for {day}, so the "
                        f"VOD of {analysis_name} on {day} has no cadence."
                    )
                    raise LayoutError(msg)
                cadences.append(blocks[day].cadence_s)
        return {day: max(cadences)} if cadences else None

    def _day_items(
        self,
        day: Any,
        entries: list[tuple[str, xr.Dataset, xr.Dataset, xr.Dataset]],
    ) -> list[dict[str, Any]]:
        """Store items of one day's VOD results, one per analysis.

        Raises
        ------
        PreprocessingMismatchError
            If canopy and reference were preprocessed differently.
        """
        research_site = self._site._site
        gnss_store_path = str(research_site.gnss_store.store_path)
        self.check_gnss_hash()

        items = []
        for analysis_name, vod_ds, canopy_ds, sky_ds in entries:
            analysis_cfg = self._get_analysis_config(analysis_name)
            canopy_name = analysis_cfg.canopy_receiver
            ref_name = analysis_cfg.reference_receiver
            # Raises PreprocessingMismatchError if canopy and reference were
            # preprocessed differently.
            record = vod_preprocessing_record(
                {
                    canopy_name: research_site.preprocessing_records_for(
                        canopy_name, canopy_ds
                    ),
                    ref_name: research_site.preprocessing_records_for(
                        analysis_cfg.reference_store_group, sky_ds
                    ),
                }
            )
            items.append(
                {
                    "vod_dataset": self._prepare_for_store(vod_ds).assign_attrs(
                        {PREPROCESSING_ATTR: record}
                    ),
                    "analysis_name": analysis_name,
                    "calculator_name": self._calculator_name,
                    "calculator_params": self._effective_calculator_params(),
                    "source_file_hashes": {
                        canopy_name: research_site.source_file_hashes_for(
                            canopy_name, canopy_ds
                        ),
                        ref_name: research_site.source_file_hashes_for(
                            analysis_cfg.reference_store_group, sky_ds
                        ),
                    },
                    "source_gnss_stores": {
                        canopy_name: gnss_store_path,
                        ref_name: gnss_store_path,
                    },
                    "commit_message": (
                        f"VOD {analysis_name} {self._date_label(vod_ds)}"
                    ),
                    "cadences": self._gnss_cadences(analysis_name, day),
                }
            )
        return items

    def _prepare_for_store(self, vod_ds: xr.Dataset) -> xr.Dataset:
        """Drop encodings inherited from the inputs and rechunk.

        String coordinates are converted by the store itself
        (``MyIcechunkStore._normalize_encodings``).
        """
        vod_ds = vod_ds.copy(deep=False)
        for name in vod_ds.variables:
            vod_ds[name].encoding = {}
        return vod_ds.chunk(self._rechunk)

    @staticmethod
    def _date_label(vod_ds: xr.Dataset) -> str:
        """``YYYYDOY`` of the first epoch, or ``YYYYDOY-YYYYDOY`` for a range."""
        import pandas as pd

        if not vod_ds.sizes.get("epoch", 0):
            return "empty"
        first = pd.Timestamp(vod_ds.epoch.values.min())
        last = pd.Timestamp(vod_ds.epoch.values.max())
        start = f"{first.year}{first.dayofyear:03d}"
        end = f"{last.year}{last.dayofyear:03d}"
        return start if start == end else f"{start}-{end}"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _aligned_pair(
        self,
        datasets: dict[str, xr.Dataset],
        analysis_name: str,
    ) -> tuple[xr.Dataset, xr.Dataset]:
        """Canopy and reference datasets of one analysis, aligned."""
        import xarray as xr

        analysis_cfg = self._get_analysis_config(analysis_name)
        canopy_name = analysis_cfg.canopy_receiver
        ref_group = analysis_cfg.reference_store_group

        if canopy_name not in datasets:
            raise KeyError(
                f"Canopy receiver '{canopy_name}' not in datasets. "
                f"Available: {list(datasets.keys())}"
            )
        if ref_group not in datasets:
            raise KeyError(
                f"Reference group '{ref_group}' not in datasets. "
                f"Available: {list(datasets.keys())}"
            )

        canopy_ds, sky_ds = xr.align(
            datasets[canopy_name], datasets[ref_group], join="inner"
        )
        return canopy_ds, sky_ds

    def _get_analysis_config(self, analysis_name: str) -> Any:
        """Get the VodAnalysisConfig for the given analysis name."""
        analyses = self._site.vod_analyses
        if analysis_name not in analyses:
            raise ValueError(
                f"VOD analysis '{analysis_name}' not configured. "
                f"Available: {list(analyses.keys())}"
            )
        return analyses[analysis_name]

    @staticmethod
    def _filter_time(
        ds: xr.Dataset,
        start: datetime | None,
        end: datetime | None,
    ) -> xr.Dataset:
        """Filter dataset by epoch time range."""
        import numpy as np
        import pandas as pd

        # Convert bounds to match the epoch dtype.
        # Newer NumPy (2.x / Python 3.14) no longer auto-coerces datetime.datetime
        # to datetime64 in comparisons, so we must convert explicitly.
        if np.issubdtype(ds.epoch.dtype, np.integer):
            # Icechunk epoch stored as int64 nanoseconds
            start = pd.Timestamp(start).value if start is not None else None  # ty: ignore[invalid-assignment]
            end = pd.Timestamp(end).value if end is not None else None  # ty: ignore[invalid-assignment]
        else:
            # datetime64[ns] — plain datetime.datetime is not comparable on NumPy 2.x
            start = np.datetime64(start, "ns") if start is not None else None  # ty: ignore[invalid-assignment]
            end = np.datetime64(end, "ns") if end is not None else None  # ty: ignore[invalid-assignment]

        if start is not None:
            ds = ds.sel(epoch=ds.epoch >= start)
        if end is not None:
            ds = ds.sel(epoch=ds.epoch <= end)
        return ds

    @staticmethod
    def _dedup_sort(ds: xr.Dataset) -> xr.Dataset:
        """Deduplicate and sort dataset by epoch."""
        import numpy as np

        _, unique_idx = np.unique(ds.epoch.values, return_index=True)
        ds = ds.isel(epoch=np.sort(unique_idx))
        return ds.sortby("epoch")

    def __repr__(self) -> str:
        return (
            f"VodComputer(site={self._site.name!r}, "
            f"calculator={self._calculator_name!r})"
        )
