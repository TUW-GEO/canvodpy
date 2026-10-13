"""
Research site manager that coordinates RINEX and VOD Icechunk stores.

This module provides the GnssResearchSite class that manages both stores
for a research site and provides high-level operations across them.
"""

from __future__ import annotations

import functools
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import xarray as xr
import zarr

if TYPE_CHECKING:
    from canvod.vod import VODCalculator

import structlog
from canvod.config.models import VodAnalysisConfig
from canvod.store_metadata.io import commit_with_rebase
from canvod.utils.tools import deprecated

from canvod.store.prepare import prepare_write
from canvod.store.store import (
    MyIcechunkStore,
    VodWriteItem,
    VodWriteResult,
    open_gnss_store,
    open_vod_store,
)


class GnssResearchSite:
    """
    High-level manager for a GNSS research site with dual Icechunk stores.

    This class coordinates between RINEX data storage (Level 1) and
    VOD analysis storage (Level 2), providing a unified interface
    for site-wide operations.

    Architecture:
    - GNSS Store: Raw/standardized observations per receiver
    - VOD Store: Analysis products comparing receiver pairs

    Features:
    - Automatic store initialization from config
    - Receiver management and validation
    - Analysis workflow coordination
    - Unified logging and error handling

    Parameters
    ----------
    site_name : str
        Name of the research site (must exist in config).

    Raises
    ------
    KeyError
        If ``site_name`` is not found in the RESEARCH_SITES config.
    """

    def __init__(self, site_name: str) -> None:
        """Initialize the site manager.

        Parameters
        ----------
        site_name : str
            Name of the research site.
        """
        from canvod.config import load_config

        config = load_config()
        sites = config.sites.sites

        if site_name not in sites:
            available_sites = list(sites.keys())
            raise KeyError(
                f"Site '{site_name}' not found in config. "
                f"Available sites: {available_sites}"
            )

        self.site_name = site_name
        self._config = config
        self._site_config = sites[site_name]
        self._logger = structlog.get_logger(__name__).bind(site=site_name)

        # The stores open on first use: a run creates them first
        # (ensure_store_metadata), so a new site has none yet.
        self.gnss_store_path = config.processing.storage.get_gnss_store_path(site_name)
        self.vod_store_path = config.processing.storage.get_vod_store_path(site_name)

        self._logger.info(
            f"Initialized GNSS research site: {site_name}",
            gnss_store=str(self.gnss_store_path),
            vod_store=str(self.vod_store_path),
        )

    @functools.cached_property
    def gnss_store(self) -> MyIcechunkStore:
        """The site's GNSS store, opened on first use.

        Raises
        ------
        FileNotFoundError
            If the store doesn't exist yet; a run creates it.
        """
        return open_gnss_store(self.gnss_store_path)

    @functools.cached_property
    def vod_store(self) -> MyIcechunkStore:
        """The site's VOD store, opened on first use.

        Raises
        ------
        FileNotFoundError
            If the store doesn't exist yet; a run creates it.
        """
        return open_vod_store(self.vod_store_path)

    @property
    def site_config(self) -> dict[str, Any]:
        """Get the site configuration as a dictionary."""
        return self._site_config.model_dump()

    @property
    def receivers(self) -> dict[str, dict[str, Any]]:
        """Get all configured receivers for this site."""
        return {
            name: cfg.model_dump() for name, cfg in self._site_config.receivers.items()
        }

    @property
    def active_receivers(self) -> dict[str, dict[str, Any]]:
        """Get only active receivers for this site."""
        return {
            name: config
            for name, config in self.receivers.items()
            if config.get("active", True)
        }

    @property
    def vod_analyses(self) -> dict[str, VodAnalysisConfig]:
        """Get all configured VOD analyses for this site.

        Returns auto-derived analyses from scs_from if no explicit
        vod_analyses are configured.
        """
        if self._site_config.vod_analyses is not None:
            return dict(self._site_config.vod_analyses)
        return self.get_auto_vod_analyses()

    @property
    def active_vod_analyses(self) -> dict[str, VodAnalysisConfig]:
        """Get only active VOD analyses for this site."""
        return {
            name: config
            for name, config in self.vod_analyses.items()
            if getattr(config, "active", True)
        }

    def get_receiver_metadata(
        self, receiver_name: str
    ) -> dict[str, str | int | float | bool] | None:
        """Get freeform metadata for a receiver.

        Returns the ``metadata`` dict of the receiver in the ``sites:``
        section of ``canvod-settings.yaml``, or ``None`` if not configured.

        Parameters
        ----------
        receiver_name : str
            Name of the receiver.

        Returns
        -------
        dict or None
            Receiver metadata dict, or None.
        """
        cfg = self._site_config.receivers.get(receiver_name)
        if cfg is None:
            return None
        return cfg.metadata

    @classmethod
    def from_gnss_store_path(
        cls,
        gnss_store_path: Path,
    ) -> GnssResearchSite:
        """
        Create a GnssResearchSite instance from a GNSS store path.

        Parameters
        ----------
        gnss_store_path : Path
            Path to the RINEX Icechunk store.

        Returns
        -------
        GnssResearchSite
            Initialized research site manager.

        Raises
        ------
        ValueError
            If no matching site is found for the given path.
        """
        # Load config to get store paths
        from canvod.config import load_config

        config = load_config()

        # Try to match against each site's expected GNSS store path
        for site_name in config.sites.sites.keys():
            expected_path = config.processing.storage.get_gnss_store_path(site_name)
            if expected_path == gnss_store_path:
                return cls(site_name)

        raise ValueError(
            f"No research site found for GNSS store path: {gnss_store_path}"
        )

    def get_reference_canopy_pairs(self) -> list[tuple[str, str]]:
        """Expand scs_from into (reference_name, canopy_name) pairs.

        Returns
        -------
        list[tuple[str, str]]
            List of (reference_name, canopy_name) pairs.
        """
        return self._site_config.get_reference_canopy_pairs()

    def get_auto_vod_analyses(self) -> dict[str, VodAnalysisConfig]:
        """Derive VOD analysis pairs from scs_from configuration.

        Creates one VOD pair per (canopy, reference_for_that_canopy) combination.

        Returns
        -------
        dict[str, VodAnalysisConfig]
            Auto-derived VOD analyses keyed by analysis name.
        """
        analyses: dict[str, VodAnalysisConfig] = {}
        for ref_name, canopy_name in self.get_reference_canopy_pairs():
            analysis_name = f"{canopy_name}_vs_{ref_name}"
            analyses[analysis_name] = VodAnalysisConfig(
                canopy_receiver=canopy_name,
                reference_receiver=ref_name,
                description=f"VOD analysis {canopy_name} vs {ref_name}",
            )
        return analyses

    def validate_site_config(self) -> bool:
        """
        Validate that the site configuration is consistent.

        Returns
        -------
        bool
            True if configuration is valid.

        Raises
        ------
        ValueError
            If configuration is invalid.
        """
        # Check that all VOD analyses reference valid receivers.
        # reference_receiver is always a bare receiver name (never a store
        # group name) -- see VodAnalysisConfig.reference_store_group for the
        # derived paired name used to look up data in the store.
        for analysis_name, analysis_config in self.vod_analyses.items():
            canopy_rx = analysis_config.canopy_receiver
            ref_rx = analysis_config.reference_receiver

            if canopy_rx not in self.receivers:
                raise ValueError(
                    f"VOD analysis '{analysis_name}' references "
                    f"unknown canopy receiver: {canopy_rx}"
                )
            if ref_rx not in self.receivers:
                raise ValueError(
                    f"VOD analysis '{analysis_name}' references "
                    f"unknown reference receiver: {ref_rx}"
                )

            # Check canopy type
            canopy_type = self.receivers[canopy_rx]["type"]
            if canopy_type != "canopy":
                raise ValueError(
                    f"Receiver '{canopy_rx}' used as canopy but type is '{canopy_type}'"
                )
            # Check reference type
            ref_type = self.receivers[ref_rx]["type"]
            if ref_type != "reference":
                raise ValueError(
                    f"Receiver '{ref_rx}' used as reference but type is '{ref_type}'"
                )

        self._logger.debug("Site configuration validation passed")
        return True

    def get_receiver_groups(self) -> list[str]:
        """
        Get list of receiver groups that exist in the GNSS store.

        Returns
        -------
        list[str]
            Existing receiver group names.
        """
        return self.gnss_store.list_groups()

    def get_vod_analysis_groups(self) -> list[str]:
        """
        Get list of VOD result groups in the VOD store.

        The VOD store nests results as ``{model}/{analysis_name}`` (one
        model per registered ``VODFactory`` calculator, disambiguating
        results from different calculators over the same analysis pair).
        Top-level ``list_groups()`` only
        returns model names, so this walks one level deeper.

        Returns
        -------
        list[str]
            ``"{model}/{analysis_name}"`` strings for every existing result.
        """
        models = self.vod_store.list_groups()
        if not models:
            return []

        try:
            with self.vod_store.readonly_session() as session:
                root = zarr.open_group(session.store, mode="r")
                return [
                    f"{model}/{analysis}"
                    for model in models
                    if model in root
                    for analysis in root[model].group_keys()  # ty: ignore[unresolved-attribute]
                ]
        except Exception:
            return []

    def ensure_store_metadata(
        self, store_type: str, names: Sequence[str], source_format: str
    ) -> dict[str, Any]:
        """Make a store of the site ready for data: the step every run takes first.

        Gives a new store its repository metadata from the settings and
        refuses groups the metadata doesn't list (ADR 0014).

        Parameters
        ----------
        store_type : str
            ``"gnss_store"`` or ``"vod_store"``.
        names : Sequence[str]
            The groups about to be written: receivers and their pair groups,
            or VOD analyses.
        source_format : str
            The reader format (GNSS store) or VOD calculator (VOD store) a
            new store records.

        Returns
        -------
        dict
            The store's repository metadata.

        Raises
        ------
        ValueError
            If the store predates repository metadata (names the migrate
            command), or a group is not listed in it (names the amend
            command).
        """
        from canvod.store_metadata import ensure_store_metadata

        store_path = (
            self.vod_store_path if store_type == "vod_store" else self.gnss_store_path
        )
        return ensure_store_metadata(
            store_path,
            config=self._config,
            site_name=self.site_name,
            store_type=store_type,
            source_format=source_format,
            names=names,
        )

    def ingest_receiver_data(
        self, dataset: xr.Dataset, receiver_name: str, commit_message: str | None = None
    ) -> None:
        """
        Ingest RINEX data for a specific receiver.

        Parameters
        ----------
        dataset : xr.Dataset
            Processed RINEX dataset to store.
        receiver_name : str
            Name of the receiver (must be configured).
        commit_message : str, optional
            Commit message to store with the data.

        Raises
        ------
        ValueError
            If ``receiver_name`` is not configured.
        """
        if receiver_name not in self.receivers:
            available_receivers = list(self.receivers.keys())
            raise ValueError(
                f"Receiver '{receiver_name}' not configured. "
                f"Available: {available_receivers}"
            )

        # Merge receiver metadata into dataset attrs (never overwrite existing)
        receiver_meta = self.get_receiver_metadata(receiver_name)
        if receiver_meta:
            skipped = {k for k in receiver_meta if k in dataset.attrs}
            if skipped:
                self._logger.warning(
                    f"Receiver metadata keys {skipped} already exist in "
                    f"dataset attrs; skipping (existing attrs take precedence)"
                )
            new_attrs = {
                k: v for k, v in receiver_meta.items() if k not in dataset.attrs
            }
            dataset.attrs.update(new_attrs)

        self._logger.info(f"Ingesting RINEX data for receiver '{receiver_name}'")

        self.ensure_store_metadata(
            "gnss_store",
            [receiver_name],
            self._site_config.receivers[receiver_name].reader_format,
        )
        self.gnss_store.write_or_append_group(
            dataset=dataset, group_name=receiver_name, commit_message=commit_message
        )

        self._logger.info(f"Successfully ingested data for receiver '{receiver_name}'")

    def source_file_hashes_for(self, group_name: str, ds: xr.Dataset) -> str:
        """Comma-joined hashes of the GNSS files behind ``ds``.

        ``ds`` is data read from GNSS store group ``group_name``. The hashes
        come from that group's log book, for every ingested file overlapping
        ``ds``'s epoch range (see ``MyIcechunkStore.source_file_hashes``), so a
        daily dataset built from many files lists all of them. Falls back to
        ``ds.attrs["File Hash"]`` when the log book has no matching rows.
        """
        if ds.sizes.get("epoch", 0):
            hashes = self.gnss_store.source_file_hashes(
                group_name, ds.epoch.min().values, ds.epoch.max().values
            )
            if hashes:
                return ",".join(hashes)
        return str(ds.attrs.get("File Hash", "unknown"))

    def preprocessing_records_for(self, group_name: str, ds: xr.Dataset) -> list[str]:
        """Preprocessing records of the GNSS data behind ``ds``.

        ``ds`` is data read from GNSS store group ``group_name``; the records
        come from that group's log book, for the files overlapping ``ds``'s
        epoch range (as :meth:`source_file_hashes_for`).
        """
        if not ds.sizes.get("epoch", 0):
            return []
        return self.gnss_store.preprocessing_records(
            group_name, ds.epoch.min().values, ds.epoch.max().values
        )

    def read_receiver_data(
        self, receiver_name: str, time_range: tuple[datetime, datetime] | None = None
    ) -> xr.Dataset:
        """
        Read data from a specific receiver.

        Parameters
        ----------
        receiver_name : str
            Name of the receiver.
        time_range : tuple of datetime, optional
            (start_time, end_time) for filtering the data.

        Returns
        -------
        xr.Dataset
            Dataset containing receiver observations.

        Raises
        ------
        ValueError
            If the receiver group does not exist.
        """
        if not self.gnss_store.group_exists(receiver_name):
            available_groups = self.get_receiver_groups()
            raise ValueError(
                f"No data found for receiver '{receiver_name}'. "
                f"Available: {available_groups}"
            )

        self._logger.info(f"Reading data for receiver '{receiver_name}'")

        if self.gnss_store._gnss_store_strategy == "unsafe_append":
            ds = self.gnss_store.read_group_deduplicated(receiver_name, keep="last")
        else:
            ds = self.gnss_store.read_group(receiver_name)

        # Apply time filtering if specified
        if time_range is not None:
            start_time, end_time = time_range
            ds = ds.where(
                (ds.epoch >= np.datetime64(start_time, "ns"))
                & (ds.epoch <= np.datetime64(end_time, "ns")),
                drop=True,
            )

            self._logger.debug(f"Applied time filter: {start_time} to {end_time}")

        return ds

    def store_vod_analysis(
        self,
        vod_dataset: xr.Dataset,
        analysis_name: str,
        calculator_name: str,
        source_file_hashes: dict[str, str],
        source_gnss_stores: dict[str, str],
        commit_message: str | None = None,
        dedup: bool = True,
    ) -> bool:
        """
        Store VOD analysis results under ``{calculator_name}/{analysis_name}``.

        The model layer disambiguates results from different VOD
        calculators computed over the same analysis pair.

        Parameters
        ----------
        vod_dataset : xr.Dataset
            Dataset containing VOD analysis results.
        analysis_name : str
            Name of the analysis (must be configured).
        calculator_name : str
            Registered ``VODFactory`` name that produced ``vod_dataset``
            (e.g. ``"tau_omega"``).
        source_file_hashes : dict[str, str]
            ``{receiver_name: "File Hash"}`` for every receiver the
            computation read from — used as the dedup key (no single hash
            exists for a two-receiver computation).
        source_gnss_stores : dict[str, str]
            ``{receiver_name: gnss_store_path}`` — provenance back to the
            GNSS store(s) the inputs came from.
        commit_message : str, optional
            Commit message to store with the results.
        dedup : bool, default True
            Skip the write if this exact source-hash combination was
            already written, or the epoch range overlaps an existing row.

        Returns
        -------
        bool
            ``True`` if written, ``False`` if skipped as a duplicate.

        Raises
        ------
        ValueError
            If ``analysis_name`` is not configured.
        """
        if analysis_name not in self.vod_analyses:
            available_analyses = list(self.vod_analyses.keys())
            raise ValueError(
                f"VOD analysis '{analysis_name}' not configured. "
                f"Available: {available_analyses}"
            )

        group_name = f"{calculator_name}/{analysis_name}"
        self._logger.info(f"Storing VOD analysis results: '{group_name}'")

        self.ensure_store_metadata("vod_store", [analysis_name], calculator_name)
        written = self.vod_store.write_or_append_vod_group(
            dataset=vod_dataset,
            group_name=group_name,
            source_file_hashes=source_file_hashes,
            source_gnss_stores=source_gnss_stores,
            calculator_name=calculator_name,
            commit_message=commit_message,
            dedup=dedup,
        )

        if written:
            self._logger.info(f"Successfully stored VOD analysis: '{group_name}'")
        return written

    def store_vod_analyses_batch(
        self,
        items: Sequence[dict[str, Any]],
    ) -> dict[str, VodWriteResult]:
        """Store multiple VOD analysis results in one fork/merge batch write.

        Same cross-group parallelization `RinexDataProcessor` uses for GNSS
        receiver groups, applied to VOD analysis pairs: each pair writes
        into its own fork concurrently, then one shared commit lands them
        all at once, instead of one full session-open/write/commit cycle
        per analysis pair in sequence.

        Parameters
        ----------
        items : Sequence[dict]
            Each dict needs: ``vod_dataset``, ``analysis_name``,
            ``calculator_name``, ``source_file_hashes``,
            ``source_gnss_stores``, and optionally ``commit_message``.

        Returns
        -------
        dict[str, VodWriteResult]
            Keyed by ``{calculator_name}/{analysis_name}`` group name.

        Raises
        ------
        ValueError
            If any ``analysis_name`` is not configured.
        """
        write_items: list[VodWriteItem] = []
        for entry in items:
            analysis_name = entry["analysis_name"]
            if analysis_name not in self.vod_analyses:
                available_analyses = list(self.vod_analyses.keys())
                raise ValueError(
                    f"VOD analysis '{analysis_name}' not configured. "
                    f"Available: {available_analyses}"
                )
            calculator_name = entry["calculator_name"]
            group_name = f"{calculator_name}/{analysis_name}"
            self._logger.info(f"Storing VOD analysis results: '{group_name}'")
            write_items.append(
                VodWriteItem(
                    group_name=group_name,
                    dataset=entry["vod_dataset"],
                    source_file_hashes=entry["source_file_hashes"],
                    source_gnss_stores=entry["source_gnss_stores"],
                    calculator_name=calculator_name,
                    commit_message=entry.get("commit_message"),
                )
            )

        if items:
            self.ensure_store_metadata(
                "vod_store",
                [entry["analysis_name"] for entry in items],
                items[0]["calculator_name"],
            )
        results = self.vod_store.write_or_append_vod_groups_batch(write_items)

        for group_name, result in results.items():
            if result.written:
                self._logger.info(f"Successfully stored VOD analysis: '{group_name}'")
        return results

    def read_vod_analysis(
        self,
        analysis_name: str,
        calculator_name: str,
        time_range: tuple[datetime, datetime] | None = None,
    ) -> xr.Dataset:
        """
        Read VOD analysis results for one calculator model.

        Parameters
        ----------
        analysis_name : str
            Name of the analysis.
        calculator_name : str
            Registered ``VODFactory`` name the results were computed with.
        time_range : tuple of datetime, optional
            (start_time, end_time) for filtering the results.

        Returns
        -------
        xr.Dataset
            Dataset containing VOD analysis results.

        Raises
        ------
        ValueError
            If the analysis group does not exist.
        """
        group_name = f"{calculator_name}/{analysis_name}"
        if not self.vod_store.group_exists(group_name):
            available_groups = self.get_vod_analysis_groups()
            raise ValueError(
                f"No VOD results found for '{group_name}'. "
                f"Available: {available_groups}"
            )

        self._logger.info(f"Reading VOD analysis: '{group_name}'")

        ds = self.vod_store.read_group(group_name)

        # Apply time filtering if specified
        if time_range is not None:
            start_time, end_time = time_range
            ds = ds.sel(epoch=slice(start_time, end_time))
            self._logger.debug(f"Applied time filter: {start_time} to {end_time}")

        return ds

    def prepare_vod_input_data(
        self, analysis_name: str, time_range: tuple[datetime, datetime] | None = None
    ) -> tuple[xr.Dataset, xr.Dataset]:
        """
        Prepare aligned input data for VOD analysis.

        Reads data from both receivers specified in the analysis configuration
        and returns them aligned for VOD processing.

        Parameters
        ----------
        analysis_name : str
            Name of the VOD analysis configuration.
        time_range : tuple of datetime, optional
            (start_time, end_time) for filtering the data.

        Returns
        -------
        tuple of (xr.Dataset, xr.Dataset)
            Tuple of (canopy_dataset, reference_dataset).

        Raises
        ------
        ValueError
            If the analysis is not configured or data is missing.
        """
        if analysis_name not in self.vod_analyses:
            available_analyses = list(self.vod_analyses.keys())
            raise ValueError(
                f"VOD analysis '{analysis_name}' not configured. "
                f"Available: {available_analyses}"
            )

        analysis_config = self.vod_analyses[analysis_name]
        canopy_receiver = analysis_config.canopy_receiver
        reference_group = analysis_config.reference_store_group

        self._logger.info(
            f"Preparing VOD input data: {canopy_receiver} vs {reference_group}"
        )

        # Read data from both receivers. Reference data is always stored
        # under the paired group name, never the bare receiver name.
        canopy_data = self.read_receiver_data(canopy_receiver, time_range)
        reference_data = self.read_receiver_data(reference_group, time_range)

        self._logger.info(
            f"Loaded data - Canopy: {dict(canopy_data.dims)}, "
            f"Reference: {dict(reference_data.dims)}"
        )

        return canopy_data, reference_data

    @deprecated(
        "GnssResearchSite.calculate_vod() is left over from development and "
        "will be removed with the next major version. Use "
        "canvodpy.Site(<site>).vod.compute_bulk(<analysis>, start=..., "
        "end=..., write=False) instead."
    )
    def calculate_vod(
        self,
        analysis_name: str,
        calculator_class: type[VODCalculator] | None = None,
        time_range: tuple[datetime, datetime] | None = None,
        processing_params=None,
    ) -> xr.Dataset:
        """
        Calculate VOD for a configured analysis pair.

        Parameters
        ----------
        analysis_name : str
            Analysis name from config (e.g., 'canopy_01_vs_reference_01')
        calculator_class : type[VODCalculator], optional
            VOD calculator class to use. If None, uses TauOmegaZerothOrder.
        time_range : tuple of datetime, optional
            (start_time, end_time) for filtering the data
        processing_params : ProcessingParams, optional
            Processing parameters controlling derived quantities. If None,
            falls back to loading from the global config (deprecated path).

        Returns
        -------
        xr.Dataset
            VOD dataset

        Note
        ----
        Requires canvod-vod to be installed.
        """
        if calculator_class is None:
            try:
                from canvod.vod import TauOmegaZerothOrder

                calculator_class = TauOmegaZerothOrder
            except ImportError as e:
                raise ImportError(
                    "canvod-vod package required for VOD calculation. "
                    "Install with: uv add canvod-vod"
                ) from e

        canopy_ds, reference_ds = self.prepare_vod_input_data(analysis_name, time_range)

        # Align once so we can access both r arrays for radial_diff before
        # passing to the calculator (which would otherwise re-align internally).
        canopy_aligned, reference_aligned = xr.align(
            canopy_ds, reference_ds, join="inner"
        )

        # Use the calculator's class method for calculation (alignment already done)
        vod_ds = calculator_class.from_datasets(canopy_aligned, reference_aligned)

        # Apply config-gated derived quantities
        if processing_params is None:
            from canvod.config import load_config as _load_config

            processing_params = _load_config().processing.params

        _params = processing_params

        if not _params.store_delta_snr:
            vod_ds = vod_ds.drop_vars("delta_snr", errors="ignore")

        if _params.store_radial_diff:
            if "r" in canopy_aligned and "r" in reference_aligned:
                radial_diff = canopy_aligned["r"] - reference_aligned["r"]
                radial_diff.attrs["units"] = "m"
                radial_diff.attrs["long_name"] = (
                    "radial distance difference (canopy − reference)"
                )
                vod_ds["radial_diff"] = radial_diff
            else:
                self._logger.warning(
                    "store_radial_diff=true but 'r' not present in receiver data; "
                    "set store_radial_distance=true at ingest time to enable this"
                )

        # Add metadata
        analysis_config = self.vod_analyses[analysis_name]
        vod_ds.attrs["analysis_name"] = analysis_name
        vod_ds.attrs["canopy_receiver"] = analysis_config.canopy_receiver
        vod_ds.attrs["reference_receiver"] = analysis_config.reference_receiver
        vod_ds.attrs["calculator"] = calculator_class.__name__
        vod_ds.attrs["canopy_hash"] = self.source_file_hashes_for(
            analysis_config.canopy_receiver, canopy_ds
        )
        vod_ds.attrs["reference_hash"] = self.source_file_hashes_for(
            analysis_config.reference_store_group, reference_ds
        )

        self._logger.info(
            f"VOD calculated for {analysis_name} using {calculator_class.__name__}"
        )
        return vod_ds

    @deprecated(
        "GnssResearchSite.store_vod() is left over from development and will "
        "be removed with the next major version. Use "
        "canvodpy.Site(<site>).vod.compute_bulk(<analysis>) or "
        "GnssResearchSite.store_vod_analysis() instead, which deduplicate and "
        "record the source files in the VOD log book."
    )
    def store_vod(
        self,
        vod_ds: xr.Dataset,
        analysis_name: str,
    ) -> str:
        """
        Store VOD dataset in VOD store.

        Parameters
        ----------
        vod_ds : xr.Dataset
            VOD dataset to store
        analysis_name : str
            Analysis name (group name in store)

        Returns
        -------
        str
            Snapshot ID
        """
        import importlib.metadata

        from icechunk.xarray import to_icechunk

        canopy_hash = vod_ds.attrs.get("canopy_hash", "unknown")
        reference_hash = vod_ds.attrs.get("reference_hash", "unknown")
        combined_hash = f"{canopy_hash}_{reference_hash}"

        with self.vod_store.writable_session() as session:
            groups = self.vod_store.list_groups() or []

            if analysis_name not in groups:
                to_icechunk(
                    prepare_write(
                        vod_ds, session.store, analysis_name, append_dim=None
                    ),
                    session,
                    group=analysis_name,
                    mode="w",
                )
                action = "write"
            else:
                to_icechunk(
                    prepare_write(
                        vod_ds, session.store, analysis_name, append_dim="epoch"
                    ),
                    session,
                    group=analysis_name,
                    append_dim="epoch",
                )
                action = "append"

            version = importlib.metadata.version("canvod-store")
            commit_msg = f"[v{version}] VOD for {analysis_name}"
            snapshot_id = commit_with_rebase(
                session, commit_msg, store_path=self.vod_store.store_path
            )

        self.vod_store.append_metadata(
            group_name=analysis_name,
            rinex_hash=combined_hash,
            start=vod_ds["epoch"].values[0],
            end=vod_ds["epoch"].values[-1],
            snapshot_id=snapshot_id,
            action=action,
            commit_msg=commit_msg,
            dataset_attrs=dict(vod_ds.attrs),
        )

        self._logger.info(
            f"VOD stored for {analysis_name}, snapshot={snapshot_id[:8]}..."
        )
        return snapshot_id

    def get_site_summary(self) -> dict[str, Any]:
        """
        Get a comprehensive summary of the research site.

        Returns
        -------
        dict
            Dictionary with site statistics, data availability, and store paths.
        """
        rinex_groups = self.get_receiver_groups()
        vod_groups = self.get_vod_analysis_groups()

        summary: dict[str, Any] = {
            "site_name": self.site_name,
            "site_config": {
                "total_receivers": len(self.receivers),
                "active_receivers": len(self.active_receivers),
                "total_vod_analyses": len(self.vod_analyses),
                "active_vod_analyses": len(self.active_vod_analyses),
            },
            "data_status": {
                "rinex_groups_exist": len(rinex_groups),
                "rinex_groups": rinex_groups,
                "vod_groups_exist": len(vod_groups),
                "vod_groups": vod_groups,
            },
            "stores": {
                "gnss_store_path": str(self.gnss_store_path),
                "vod_store_path": str(self.vod_store_path),
            },
        }

        # Add receiver details
        summary["receivers"] = {}
        for receiver_name, receiver_config in self.active_receivers.items():
            has_data = receiver_name in rinex_groups
            summary["receivers"][receiver_name] = {
                "type": receiver_config["type"],
                "description": receiver_config["description"],
                "has_data": has_data,
            }

            if has_data:
                try:
                    info = self.gnss_store.get_group_info(receiver_name)
                    summary["receivers"][receiver_name]["data_info"] = {
                        "dimensions": info["dimensions"],
                        "variables": len(info["variables"]),
                        "temporal_info": info.get("temporal_info", {}),
                    }
                except Exception as e:
                    self._logger.warning(f"Failed to get info for {receiver_name}: {e}")

        # Add VOD analysis details. vod_groups holds "{model}/{analysis_name}"
        # strings — one analysis can have results from multiple calculator
        # models, so this reports per-model info rather than a single flag.
        summary["vod_analyses"] = {}
        for analysis_name, analysis_config in self.active_vod_analyses.items():
            models_with_results = [
                group.split("/", 1)[0]
                for group in vod_groups
                if group.endswith(f"/{analysis_name}")
            ]
            summary["vod_analyses"][analysis_name] = {
                "canopy_receiver": analysis_config.canopy_receiver,
                "reference_receiver": analysis_config.reference_receiver,
                "description": analysis_config.description,
                "has_results": bool(models_with_results),
                "models_with_results": models_with_results,
            }

            if models_with_results:
                results_info: dict[str, Any] = {}
                for model in models_with_results:
                    try:
                        info = self.vod_store.get_group_info(f"{model}/{analysis_name}")
                        results_info[model] = {
                            "dimensions": info["dimensions"],
                            "variables": len(info["variables"]),
                            "temporal_info": info.get("temporal_info", {}),
                        }
                    except Exception as e:
                        self._logger.warning(
                            f"Failed to get VOD info for {model}/{analysis_name}: {e}"
                        )
                summary["vod_analyses"][analysis_name]["results_info"] = results_info

        return summary

    def is_day_complete(
        self,
        yyyydoy: str,
        receiver_types: list[str] | None = None,
        completeness_threshold: float = 0.95,
    ) -> bool:
        """
        Check if a day has complete data coverage for all receiver types.

        Parameters
        ----------
        yyyydoy : str
            Date in YYYYDOY format (e.g., "2024256")
        receiver_types : List[str], optional
            Receiver types to check. Defaults to ['canopy', 'reference']
        completeness_threshold : float
            Fraction of expected epochs that must exist (default 0.95 = 95%)
            Allows for small gaps due to receiver issues

        Returns
        -------
        bool
            True if all receiver types have complete data for this day
        """
        if receiver_types is None:
            receiver_types = ["canopy", "reference"]

        from canvod.utils.tools import YYYYDOY

        yyyydoy_obj = YYYYDOY.from_str(yyyydoy)

        # Expected epochs for 24h at 30s sampling
        expected_epochs = int(24 * 3600 / 30)  # 2880 epochs
        required_epochs = int(expected_epochs * completeness_threshold)

        for receiver_type in receiver_types:
            # Get receiver name for this type
            receiver_name = None
            for name, config in self.active_receivers.items():
                if config.get("type") == receiver_type:
                    receiver_name = name
                    break

            if not receiver_name:
                self._logger.warning(f"No receiver configured for type {receiver_type}")
                return False

            try:
                # Try to read data for this day
                import datetime as _dt

                assert yyyydoy_obj.date is not None
                _day_start = datetime.combine(yyyydoy_obj.date, _dt.time.min)
                time_range = (_day_start, _day_start + _dt.timedelta(days=1))

                ds = self.read_receiver_data(
                    receiver_name=receiver_name, time_range=time_range
                )

                # Check epoch count
                n_epochs = ds.sizes.get("epoch", 0)

                if n_epochs < required_epochs:
                    self._logger.info(
                        f"{receiver_name} {yyyydoy}: Only "
                        f"{n_epochs}/{expected_epochs} epochs "
                        f"({n_epochs / expected_epochs * 100:.1f}%) - incomplete"
                    )
                    return False

                self._logger.debug(
                    f"{receiver_name} {yyyydoy}: "
                    f"{n_epochs}/{expected_epochs} epochs - complete"
                )

            except (ValueError, KeyError, Exception) as e:
                # No data exists or error reading
                self._logger.debug(f"{receiver_name} {yyyydoy}: No data found - {e}")
                return False

        # All receiver types have complete data
        return True

    def __repr__(self) -> str:
        """Return the developer-facing representation.

        Returns
        -------
        str
            Representation string.
        """
        return f"GnssResearchSite(site_name='{self.site_name}')"

    def __str__(self) -> str:
        """Return a human-readable summary.

        Returns
        -------
        str
            Summary string.
        """
        rinex_groups = len(self.get_receiver_groups())
        vod_groups = len(self.get_vod_analysis_groups())
        return (
            f"GNSS Research Site: {self.site_name}\n"
            f"  Receivers: {len(self.active_receivers)} configured, "
            f"{rinex_groups} with data\n"
            f"  VOD Analyses: {len(self.active_vod_analyses)} configured, "
            f"{vod_groups} with results"
        )


# Convenience function for default site
def create_default_site() -> GnssResearchSite:
    """
    Create a `GnssResearchSite` instance for the default site.

    Returns
    -------
    GnssResearchSite
        Instance for the ``DEFAULT_RESEARCH_SITE``.
    """
    from canvod.config import load_config

    _sites = load_config().sites.sites
    if not _sites:
        raise ValueError(
            "No sites configured: create canvod-settings.yaml "
            "or pass site_name explicitly."
        )
    return GnssResearchSite(next(iter(_sites)))
