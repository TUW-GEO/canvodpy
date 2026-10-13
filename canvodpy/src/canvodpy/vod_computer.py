"""VOD computation and storage for a site: the single VOD implementation.

Every entry point computes and stores VOD through this class: the Python
``site.vod`` object, ``canvodpy run`` (per day, during processing),
``canvodpy vod`` and ``canvodpy vod-reconcile`` (from the GNSS store).

- ``compute_day()`` / ``compute_day_all()`` — from the per-day datasets
  yielded by ``Pipeline.process_range()``. Loads them into memory, then
  computes.
- ``compute_bulk()``: from the site's GNSS Icechunk store. Reads the full
  (or filtered) time range, drops duplicate epochs, sorts, then computes.

All three share ``_compute()`` (the calculator, which aligns canopy and
reference on their shared epochs and signals) and ``_write()`` (one commit
for all analyses written together, then the VOD store metadata).
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

Bulk reprocessing::

    vod = VodComputer(site)
    vod.compute_bulk("canopy_01_vs_reference_01")

Custom calculator::

    vod = VodComputer(site, calculator="dual_freq_vod")
    vod.compute_day(datasets, "canopy_01_vs_reference_01")
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

import structlog

from canvod.config.models import (
    PREPROCESSING_ATTR,
    vod_preprocessing_record,
)

if TYPE_CHECKING:
    import xarray as xr

    from canvodpy.api import Site


def ensure_vod_store_metadata(
    site: Site, calculator_name: str, analyses: list[str]
) -> None:
    """Give a new VOD store its metadata; refuse unlisted VOD analyses.

    Call it before the VOD write, so the VOD store never holds data
    without its repository metadata (ADR 0014). Every commit then writes
    the store's root copy and snapshot summary itself.

    Raises
    ------
    ValueError
        If the site is not in the settings, the store predates repository
        metadata (names the migrate command), or a VOD analysis is not
        listed in it (names the amend command).
    """
    from canvod.config import load_config
    from canvod.store_metadata import ensure_store_metadata

    ensure_store_metadata(
        site.vod_store_path,
        config=load_config(),
        site_name=site.name,
        store_type="vod_store",
        source_format=calculator_name,
        names=analyses,
    )


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
        rechunk: dict[str, int] | None = None,
    ) -> None:
        self._site = site
        self._calculator_name = calculator
        self._rechunk = rechunk or {"epoch": 17280, "sid": -1}
        self.log = structlog.get_logger(__name__).bind(
            site=site.name, calculator=calculator
        )

    @property
    def calculator_name(self) -> str:
        """Registered name of the VOD calculator in use."""
        return self._calculator_name

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

        Opens canopy and reference groups directly from the store,
        reads the full (or filtered) time range, then computes VOD.

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
        """
        vod_ds, canopy_ds, sky_ds = self._compute_bulk_entry(analysis_name, start, end)
        if write:
            self._write([(analysis_name, vod_ds, canopy_ds, sky_ds)])
        return vod_ds

    def compute_bulk_all(
        self,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        write: bool = True,
    ) -> dict[str, xr.Dataset]:
        """Compute VOD for every configured analysis from the GNSS store.

        Same as ``compute_bulk()`` per analysis; all results are written
        together, in one commit.

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
        """
        entries = [
            (name, *self._compute_bulk_entry(name, start, end))
            for name in self._site.vod_analyses
        ]
        if write and entries:
            self._write(entries)
        return {name: vod_ds for name, vod_ds, _, _ in entries}

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

        with store.readonly_session() as session:
            canopy_ds = xr.open_zarr(
                store=session.store, group=canopy_name, consolidated=False
            )
            sky_ds = xr.open_zarr(
                store=session.store, group=ref_group, consolidated=False
            )

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
        """Compute VOD with the configured calculator.

        The calculator itself aligns both datasets on their shared epochs
        and signals.
        """
        from canvodpy.factories import VODFactory

        calculator = VODFactory.create(
            self._calculator_name,
            canopy_ds=canopy_ds,
            sky_ds=sky_ds,
        )

        vod_ds = calculator.calculate_vod()
        vod_ds = self._apply_output_options(
            vod_ds, calculator.canopy_ds, calculator.sky_ds
        )

        analysis_cfg = self._get_analysis_config(analysis_name)
        vod_ds.attrs["analysis_name"] = analysis_name
        vod_ds.attrs["canopy_receiver"] = analysis_cfg.canopy_receiver
        vod_ds.attrs["reference_receiver"] = analysis_cfg.reference_receiver
        vod_ds.attrs["calculator"] = self._calculator_name

        self.log.info(
            "vod_computed",
            analysis=analysis_name,
            variables=list(vod_ds.data_vars),
        )
        return vod_ds

    def _apply_output_options(
        self,
        vod_ds: xr.Dataset,
        canopy_ds: xr.Dataset,
        sky_ds: xr.Dataset,
    ) -> xr.Dataset:
        """Apply the configured optional VOD outputs.

        ``store_delta_snr`` keeps ``delta_snr`` (dropped by default);
        ``store_radial_diff`` adds ``radial_diff`` (canopy minus reference
        slant range, needs ``r`` from ``store_radial_distance`` at ingest).
        """
        from canvod.config import load_config

        params = load_config().processing.params

        if not params.store_delta_snr:
            vod_ds = vod_ds.drop_vars("delta_snr", errors="ignore")

        if params.store_radial_diff:
            if "r" in canopy_ds and "r" in sky_ds:
                radial_diff = canopy_ds["r"] - sky_ds["r"]
                radial_diff.attrs["units"] = "m"
                radial_diff.attrs["long_name"] = (
                    "radial distance difference (canopy − reference)"
                )
                vod_ds["radial_diff"] = radial_diff
            else:
                self.log.warning(
                    "radial_diff_unavailable",
                    reason=(
                        "store_radial_diff=true but 'r' not present in receiver "
                        "data; set store_radial_distance=true at ingest time"
                    ),
                )
        return vod_ds

    def _write(
        self,
        entries: list[tuple[str, xr.Dataset, xr.Dataset, xr.Dataset]],
    ) -> dict[str, Any]:
        """Write VOD results in one commit, after checking the store metadata.

        Parameters
        ----------
        entries : list of tuple
            ``(analysis_name, vod_ds, canopy_ds, sky_ds)`` per analysis;
            ``canopy_ds``/``sky_ds`` are the aligned inputs, whose epoch
            range selects the GNSS files recorded as sources.

        Returns
        -------
        dict[str, VodWriteResult]
            Store write result per ``{calculator}/{analysis}`` group.
        """
        research_site = self._site._site
        gnss_store_path = str(research_site.gnss_store.store_path)

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
                }
            )

        ensure_vod_store_metadata(
            self._site, self._calculator_name, [name for name, *_ in entries]
        )
        results = research_site.store_vod_analyses_batch(items=items)

        for analysis_name, *_ in entries:
            self.log.info(
                "vod_written_to_store",
                analysis=analysis_name,
                model=self._calculator_name,
            )
        return results

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
