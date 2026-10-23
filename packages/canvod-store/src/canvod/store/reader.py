"""Icechunk-backed readers for RINEX datasets."""

import gc
import time
from collections.abc import Generator
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import numpy as np
import structlog
import xarray as xr
from canvod.config import load_config
from canvod.readers import MatchedDirs, Rnxv3Obs
from canvod.utils.tools import _worker_init, deprecated, get_version_from_pyproject
from natsort import natsorted
from tqdm import tqdm

from canvod.store.manager import GnssResearchSite

_REPLACEMENT = (
    "Use `canvodpy run` or `canvodpy.Site(<site>).pipeline().process_date(<date>)` "
    "instead."
)


# Module-level function for ProcessPoolExecutor (must be pickleable).
def _process_single_rinex(
    rnx_file: Path,
    keep_vars: list[str] | None = None,
) -> tuple[Path, xr.Dataset]:
    """
    Process a single RINEX file with a file-scoped logging context.

    Parameters
    ----------
    rnx_file : Path
        RINEX file to process.
    keep_vars : list[str] | None, optional
        Variables to retain in the dataset.

    Returns
    -------
    tuple[Path, xr.Dataset]
        The input file path and the processed dataset.
    """

    log = structlog.get_logger(__name__).bind(file=str(rnx_file))
    log.info("rinex_processing_started")

    try:
        rnx = Rnxv3Obs(fpath=rnx_file)
        ds = rnx.to_ds(write_global_attrs=True)

        # Filter variables if specified
        if keep_vars:
            available_vars = [var for var in keep_vars if var in ds.data_vars]
            if available_vars:
                ds_subset = ds[available_vars]
                if isinstance(ds_subset, xr.DataArray):
                    ds = ds_subset.to_dataset(name=ds_subset.name or "value")
                else:
                    ds = ds_subset

        log.info("rinex_processing_complete")
        return rnx_file, ds

    except Exception as e:
        log.exception("rinex_processing_failed", error=str(e))
        raise


# Module-level function for ProcessPoolExecutor (must be pickleable).
def preprocess_rnx(
    rnx_file: Path,
    keep_vars: list[str] | None = None,
) -> tuple[Path, xr.Dataset]:
    """
    Preprocess a single RINEX file and attach file hash metadata.

    Parameters
    ----------
    rnx_file : Path
        RINEX file to preprocess.
    keep_vars : list[str] | None, optional
        Variables to retain in the dataset.

    Returns
    -------
    tuple[Path, xr.Dataset]
        The input file path and the processed dataset.
    """
    log = structlog.get_logger(__name__).bind(file=str(rnx_file))
    log.info("preprocessing_started")

    try:
        rnx = Rnxv3Obs(fpath=rnx_file)
        ds = rnx.to_ds(write_global_attrs=True)

        # Attach cached file hash
        ds.attrs["File Hash"] = rnx.file_hash

        # Filter variables if specified
        if keep_vars:
            available_vars = [var for var in keep_vars if var in ds.data_vars]
            if available_vars:
                ds_subset = ds[available_vars]
                if isinstance(ds_subset, xr.DataArray):
                    ds = ds_subset.to_dataset(name=ds_subset.name or "value")
                else:
                    ds = ds_subset

        log.info("preprocessing_complete")
        return rnx_file, ds
    except Exception as e:
        log.exception("preprocessing_failed", error=str(e))
        raise


@deprecated(
    "`IcechunkDataReader` is left over from development and will be removed "
    f"with the next major version. {_REPLACEMENT}"
)
class IcechunkDataReader:
    """
    Read RINEX v3 files of one day and append them to the site's GNSS store.

    .. deprecated::
        Left over from development, removed with the next major version.
        Use ``canvodpy run`` or
        ``canvodpy.Site(<site>).pipeline().process_date(<date>)``, which
        read all supported formats and add the satellite geometry.

    Parameters
    ----------
    matched_dirs : MatchedDirs
        Directory information for date/location matching
    site_name : str, optional
        Name of research site (defaults to DEFAULT_RESEARCH_SITE)
    n_max_workers : int, optional
        Maximum number of workers for parallel operations (defaults to N_MAX_THREADS)
    enable_gc : bool, optional
        Whether to enable garbage collection between operations (default True)
    gc_delay : float, optional
        Delay in seconds after garbage collection (default 1.0)
    """

    def __init__(
        self,
        matched_dirs: MatchedDirs,
        site_name: str | None = None,
        n_max_workers: int | None = None,
        enable_gc: bool = True,
        gc_delay: float = 1.0,
    ) -> None:
        """Initialize the Icechunk data reader.

        Parameters
        ----------
        matched_dirs : MatchedDirs
            Directory information for date/location matching.
        site_name : str | None, optional
            Name of research site. If ``None``, uses the first site from config.
        n_max_workers : int | None, optional
            Maximum number of workers for parallel operations. Defaults to config.
        enable_gc : bool, optional
            Whether to enable garbage collection between operations.
        gc_delay : float, optional
            Delay in seconds after garbage collection.
        """
        config = load_config()
        if site_name is None:
            _sites = config.sites.sites
            if not _sites:
                raise ValueError(
                    "No sites configured: create canvod-settings.yaml "
                    "or pass site_name explicitly."
                )
            site_name = next(iter(_sites))
        if n_max_workers is None:
            resources = config.processing.processing.resolve_resources()
            n_max_workers = resources["n_workers"]

        self.matched_dirs = matched_dirs
        self.site_name = site_name
        self.n_max_workers = n_max_workers
        self.enable_gc = enable_gc
        self.gc_delay = gc_delay

        self._logger = structlog.get_logger(__name__).bind(
            site=site_name,
            date=matched_dirs.yyyydoy.to_str(),
        )
        self._site = GnssResearchSite(site_name)

        date_obj = self.matched_dirs.yyyydoy.date
        if date_obj is None:
            msg = (
                f"Matched date is missing for {self.matched_dirs.yyyydoy.to_str()} "
                f"at site {site_name}"
            )
            raise ValueError(msg)
        self._start_time = datetime.combine(date_obj, datetime.min.time())
        self._end_time = datetime.combine(date_obj, datetime.max.time())
        self._time_range = (self._start_time, self._end_time)

        # ✅ single persistent pool
        _res = load_config().processing.params.resolve_resources()
        self._pool = ProcessPoolExecutor(
            max_workers=min(self.n_max_workers, 16),
            initializer=_worker_init,
            initargs=(_res["nice_priority"], _res["cpu_affinity"]),
        )

        self._logger.info(
            f"Initialized Icechunk data reader for {matched_dirs.yyyydoy.to_str()}"
        )

    def __del__(self) -> None:
        """Ensure the pool is shut down when the reader is deleted."""
        try:
            self._pool.shutdown(wait=True)
        except Exception:
            pass

    def _memory_cleanup(self) -> None:
        """Perform memory cleanup if enabled."""
        if self.enable_gc:
            gc.collect()
            if self.gc_delay > 0:
                time.sleep(self.gc_delay)

    def get_receiver_by_type(self, receiver_type: str) -> list[str]:
        """
        Get list of receiver names by type.

        Parameters
        ----------
        receiver_type : str
            Type of receiver ('canopy', 'reference')

        Returns
        -------
        list[str]
            List of receiver names of the specified type
        """
        return [
            name
            for name, config in self._site.active_receivers.items()
            if config["type"] == receiver_type
        ]

    def _get_receiver_name_for_type(self, receiver_type: str) -> str | None:
        """Get the first configured receiver name for a given type."""
        for name, config in self._site.active_receivers.items():
            if config["type"] == receiver_type:
                return name
        return None

    def _memory_cleanup(self) -> None:
        """Perform memory cleanup if enabled."""
        if self.enable_gc:
            gc.collect()
            if self.gc_delay > 0:
                time.sleep(self.gc_delay)

    @deprecated(
        "`IcechunkDataReader.parsed_rinex_data_gen_v2()` is left over from "
        "development, does not run with the current `RinexDataProcessor` and "
        f"will be removed with the next major version. {_REPLACEMENT}"
    )
    def parsed_rinex_data_gen_v2(
        self,
        keep_vars: list[str] | None = None,
        receiver_types: list[str] | None = None,
    ) -> Generator[xr.Dataset]:
        """Raise an error: this generator does not run any more.

        It was written for an earlier ``RinexDataProcessor``, whose
        constructor and methods it calls no longer exist.

        Raises
        ------
        RuntimeError
            Always, naming the replacement.
        """
        msg = (
            "`IcechunkDataReader.parsed_rinex_data_gen_v2()` does not run with "
            f"the current `RinexDataProcessor`. {_REPLACEMENT}"
        )
        raise RuntimeError(msg)

    @deprecated(
        "`IcechunkDataReader.parsed_rinex_data_gen()` is left over from "
        "development and will be removed with the next major version. "
        f"{_REPLACEMENT}"
    )
    def parsed_rinex_data_gen(
        self,
        keep_vars: list[str] | None = None,
        receiver_types: list[str] | None = None,
    ) -> Generator[xr.Dataset]:
        """
        Generator that processes RINEX files and appends to Icechunk stores on-the-fly.

        Parameters
        ----------
        keep_vars : list[str], optional
            List of variables to keep in datasets
        receiver_types : list[str], optional
            List of receiver types to process ('canopy', 'reference').
            If None, defaults to ['canopy', 'reference']

        Yields
        ------
        xr.Dataset
            Processed and ingested datasets for each receiver type, in order
        """

        if receiver_types is None:
            receiver_types = ["canopy", "reference"]

        self._logger.info(
            f"Starting RINEX processing and ingestion for types: {receiver_types}"
        )

        for receiver_type in receiver_types:
            # --- resolve dirs and names ---
            if receiver_type == "canopy":
                rinex_dir = self.matched_dirs.canopy_data_dir
                receiver_name = self._get_receiver_name_for_type("canopy")
                store_group = "canopy"
            elif receiver_type == "reference":
                rinex_dir = self.matched_dirs.reference_data_dir
                receiver_name = self._get_receiver_name_for_type("reference")
                store_group = "reference"
            else:
                self._logger.warning(f"Unknown receiver type: {receiver_type}")
                continue

            if not receiver_name:
                self._logger.warning(f"No configured receiver for type {receiver_type}")
                continue

            rinex_files = self._get_rinex_files(rinex_dir)
            if not rinex_files:
                self._logger.warning(f"No RINEX files found in {rinex_dir}")
                continue
            self._site.ensure_store_metadata("gnss_store", [store_group], "rinex3")

            self._logger.info(
                f"Processing {len(rinex_files)} RINEX files for {receiver_type}"
            )

            groups = self._site.gnss_store.list_groups() or []

            # --- one pool per receiver type ---
            futures = {
                self._pool.submit(preprocess_rnx, f, keep_vars): f for f in rinex_files
            }
            results: list[tuple[Path, xr.Dataset]] = []

            # ✅ progressbar over all files, not per batch
            for fut in tqdm(
                as_completed(futures),
                total=len(futures),
                desc=f"Processing {receiver_type}",
            ):
                try:
                    fname, ds = fut.result()
                    results.append((fname, ds))
                except Exception as e:
                    self._logger.error(f"Failed preprocessing: {e}")

            # --- sort all results once (chronological order) ---
            results.sort(key=lambda x: x[0].name)

            # --- sequential append to Icechunk ---
            for idx, (fname, ds) in enumerate(results):
                log = self._logger.bind(file=str(fname))
                try:
                    rel_path = self._site.gnss_store.rel_path_for_commit(fname)
                    version = get_version_from_pyproject()

                    rinex_hash = ds.attrs.get("File Hash")
                    if not rinex_hash:
                        log.warning(
                            f"No file hash found in dataset from {fname}. "
                            "Skipping duplicate detection for this file."
                        )
                        continue

                    start_epoch = np.datetime64(ds.epoch.min().values)
                    end_epoch = np.datetime64(ds.epoch.max().values)

                    exists, matches = self._site.gnss_store.metadata_row_exists(
                        store_group, rinex_hash, start_epoch, end_epoch
                    )

                    ds = self._site.gnss_store._cleanse_dataset_attrs(ds)

                    # --- Initial commit ---
                    if not exists and store_group not in groups and idx == 0:
                        msg = (
                            f"[v{version}] Initial commit with {rel_path} "
                            f"(hash={rinex_hash}, epoch={start_epoch}→{end_epoch}) "
                            f"to group '{store_group}'"
                        )
                        self._site.gnss_store.write_initial_group(
                            dataset=ds,
                            group_name=store_group,
                            commit_message=msg,
                        )
                        groups.append(store_group)
                        log.info(msg)
                        continue

                    # --- Handle strategies with match ---
                    match (exists, self._site.gnss_store._gnss_store_strategy):
                        case (True, "skip"):
                            msg = (
                                f"[v{version}] Skipped {rel_path} "
                                f"(hash={rinex_hash}, epoch={start_epoch}→{end_epoch}) "
                                f"in group '{store_group}'"
                            )
                            log.info(msg)
                            self._site.gnss_store.append_metadata(
                                group_name=store_group,
                                rinex_hash=rinex_hash,
                                start=start_epoch,
                                end=end_epoch,
                                snapshot_id="none",
                                action="skip",
                                commit_msg=msg,
                                dataset_attrs=ds.attrs,
                            )

                        case (True, "overwrite"):
                            msg = (
                                f"[v{version}] Overwrote {rel_path} "
                                f"(hash={rinex_hash}, epoch={start_epoch}→{end_epoch}) "
                                f"in group '{store_group}'"
                            )
                            log.info(msg)
                            self._site.gnss_store.overwrite_file_in_group(
                                dataset=ds,
                                group_name=store_group,
                                rinex_hash=rinex_hash,
                                start=start_epoch,
                                end=end_epoch,
                                commit_message=msg,
                            )

                        case (True, "unsafe_append"):
                            msg = (
                                f"[v{version}] Appended {rel_path} "
                                f"(hash={rinex_hash}, epoch={start_epoch}→{end_epoch}) "
                                f"to group '{store_group}'"
                            )
                            self._site.gnss_store.append_to_group(
                                dataset=ds,
                                group_name=store_group,
                                append_dim="epoch",
                                action="append",
                                commit_message=msg,
                            )
                            log.info(msg)

                        case (False, _):
                            msg = (
                                f"[v{version}] Wrote {rel_path} "
                                f"(hash={rinex_hash}, epoch={start_epoch}→{end_epoch}) "
                                f"to group '{store_group}'"
                            )
                            self._site.gnss_store.append_to_group(
                                dataset=ds,
                                group_name=store_group,
                                append_dim="epoch",
                                action="write",
                                commit_message=msg,
                            )
                            log.info(msg)

                except Exception as e:
                    log.exception("file_commit_failed", error=str(e))
                    raise

                self._memory_cleanup()

            # --- read back final dataset ---
            final_ds = self._site.read_receiver_data(store_group, self._time_range)
            self._logger.info(
                f"Yielding {receiver_type} dataset: {dict(final_ds.sizes)}"
            )
            yield final_ds

            self._memory_cleanup()

        self._logger.info("RINEX processing and ingestion completed")

    def _get_receiver_name_for_type(self, receiver_type: str) -> str | None:
        """Get the first configured receiver name for a given type."""
        for name, config in self._site.active_receivers.items():
            if config["type"] == receiver_type:
                return name
        return None

    def _get_rinex_files(self, rinex_dir: Path) -> list[Path]:
        """Get sorted list of RINEX files from directory."""

        if not rinex_dir.exists():
            self._logger.warning(f"Directory does not exist: {rinex_dir}")
            return []

        # Look for common RINEX file patterns
        patterns = ["*.??o", "*.??O", "*.rnx", "*.RNX"]
        rinex_files = []

        for pattern in patterns:
            files = list(rinex_dir.glob(pattern))
            rinex_files.extend(files)

        return natsorted(rinex_files)

    def _append_to_icechunk_store(
        self,
        dataset: xr.Dataset,
        receiver_name: str,
        receiver_type: str,
    ) -> None:
        """Append dataset to the appropriate Icechunk store."""
        try:
            version = get_version_from_pyproject()
            date_str = self.matched_dirs.yyyydoy.to_str()

            commit_message = (
                f"[v{version}] Processed and ingested {receiver_type} data "
                f"for {date_str}"
            )

            # Use site's ingestion method
            self._site.ingest_receiver_data(dataset, receiver_name, commit_message)

            self._logger.info(
                f"Successfully appended {receiver_type} data to store as "
                f"'{receiver_name}'"
            )

        except Exception as e:
            self._logger.exception(
                f"Failed to append {receiver_type} data to store", error=str(e)
            )
            raise

    def get_available_receivers(self) -> dict[str, list[str]]:
        """
        Get available receivers grouped by type.

        Returns
        -------
        dict[str, list[str]]
            Dictionary mapping receiver types to lists of receiver names.
        """
        available = {}
        for receiver_type in ["canopy", "reference"]:
            receivers = self.get_receiver_by_type(receiver_type)
            # Filter to only receivers that have data
            with_data = [r for r in receivers if self._site.gnss_store.group_exists(r)]
            available[receiver_type] = with_data

        return available

    def __str__(self) -> str:
        """Return a human-readable summary.

        Returns
        -------
        str
            Summary string.
        """
        available = self.get_available_receivers()
        return (
            f"IcechunkDataReader for {self.matched_dirs.yyyydoy.to_str()}\n"
            f"  Site: {self.site_name}\n"
            f"  Available receivers: {dict(available)}\n"
            f"  Workers: {self.n_max_workers}, GC enabled: {self.enable_gc}"
        )
