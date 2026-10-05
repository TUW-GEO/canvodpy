"""
Auxiliary Data Pipeline for GNSS Processing

Manages downloading, reading, preprocessing, and caching of auxiliary files
(ephemerides, clock, atmospheric corrections, etc.) for RINEX processing.
"""

import datetime
import threading
from pathlib import Path

import numpy as np
import structlog
import xarray as xr
from canvod.readers.matching import MatchedDirs
from canvod.utils.tools import YYYYDOY

from canvod.auxiliary.core.base import AuxFile
from canvod.auxiliary.preprocessing import prep_aux_ds

_SP3_SUBDIR = Path("01_SP3")
_CLK_SUBDIR = Path("02_CLK")


class AuxDataPipeline:
    """Pipeline for managing auxiliary data files in GNSS processing.

    Handles the complete lifecycle of auxiliary files:
    1. Registration of aux file handlers (Sp3File, ClkFile, etc.)
    2. Downloading/loading files
    3. Preprocessing (sv → sid mapping)
    4. Thread-safe caching for parallel RINEX processing

    Parameters
    ----------
    matched_dirs : MatchedDirs
        Matched directories containing date information (YYYYDOY).

    Attributes
    ----------
    matched_dirs : MatchedDirs
        Matched directories for this processing day.
    _registry : dict[str, dict]
        Registered auxiliary file handlers with metadata.
    _cache : dict[str, xr.Dataset]
        Cache for preprocessed (sid-mapped) datasets.
    _lock : threading.Lock
        Thread lock for concurrent access during parallel processing.
    _logger : Logger
        Logger instance for this pipeline.
    """

    def __init__(
        self,
        matched_dirs: MatchedDirs,
        keep_sids: list[str] | None = None,
        aggregate_glonass_fdma: bool = True,
    ):
        """Initialize the auxiliary data pipeline.

        Parameters
        ----------
        matched_dirs : MatchedDirs
            Matched directories for this processing day.
        keep_sids : list[str] | None
            Optional list of specific SIDs to keep. If None, keeps all possible SIDs.
        aggregate_glonass_fdma : bool, default True
            Map GLONASS FDMA satellites to aggregated G1/G2 signal IDs. Must
            match the GNSS reader's setting, or the GLONASS IDs differ.
        """
        self.matched_dirs = matched_dirs
        self.keep_sids = keep_sids
        self.aggregate_glonass_fdma = aggregate_glonass_fdma
        self._registry: dict[str, dict] = {}
        self._cache: dict[str, xr.Dataset] = {}
        self._lock = threading.Lock()
        self._logger = structlog.get_logger(__name__).bind(
            date=self.matched_dirs.yyyydoy.to_str(),
            sid_filtering=len(keep_sids) if keep_sids else "all",
        )

        self._logger.info(
            "aux_pipeline_initialized",
            keep_sids_count=len(keep_sids) if keep_sids else None,
        )

    def register(
        self,
        name: str,
        aux_file: AuxFile,
        required: bool = False,
        neighbors: tuple[AuxFile, AuxFile] | None = None,
    ) -> None:
        """Register an auxiliary file handler.

        Parameters
        ----------
        name : str
            Identifier for this aux file (e.g., "ephemerides", "clock").
        aux_file : AuxFile
            Instance of AuxFile subclass (Sp3File, ClkFile, etc.).
        required : bool, default False
            If True, pipeline will fail if this file cannot be loaded.
        neighbors : tuple[AuxFile, AuxFile] | None
            The same product for the previous and the next day. If given,
            the file is loaded joined with them
            (:meth:`~canvod.auxiliary.core.base.AuxFile.join_days`), so the
            whole day lies inside the data.

        Examples
        --------
        >>> pipeline = AuxDataPipeline(matched_dirs=md)
        >>> pipeline.register('ephemerides', Sp3File(...), required=True)
        >>> pipeline.register('clock', ClkFile(...), required=True)
        >>> pipeline.register('ionex', IonexFile(...), required=False)
        """
        if name in self._registry:
            self._logger.warning(
                "aux_file_overwrite",
                name=name,
                old_handler=self._registry[name]["handler"].__class__.__name__,
                new_handler=aux_file.__class__.__name__,
            )

        self._registry[name] = {
            "handler": aux_file,
            "required": required,
            "loaded": False,
            "neighbors": neighbors,
        }

        self._logger.info(
            "aux_file_registered",
            name=name,
            handler=aux_file.__class__.__name__,
            required=required,
            file_path=str(aux_file.fpath),
        )

    def load_all(self) -> None:
        """Load all registered auxiliary files.

        Performs two-stage loading:
        1. Download & read → raw xr.Dataset with 'sv' dimension
        2. Preprocess → sid-mapped xr.Dataset (cached)

        Raises
        ------
        RuntimeError
            If a required aux file fails to load.
        """
        import time

        start_time = time.time()
        self._logger.info(
            "aux_load_all_started",
            registered_files=len(self._registry),
            file_names=list(self._registry.keys()),
        )

        loaded_count = 0
        failed_count = 0

        for name, entry in self._registry.items():
            handler = entry["handler"]
            required = entry["required"]

            file_start = time.time()

            try:
                self._logger.info(
                    "aux_file_load_started",
                    name=name,
                    file_path=str(handler.fpath),
                )

                # Stage 1: Download & read raw dataset (joined with the
                # neighboring days if registered with them)
                neighbors = entry.get("neighbors")
                raw_ds = handler.join_days(*neighbors) if neighbors else handler.data

                # Stage 2: Preprocess (sv → sid mapping) with keep_sids filter
                preprocessed_ds = prep_aux_ds(
                    raw_ds,
                    keep_sids=self.keep_sids,
                    aggregate_glonass_fdma=self.aggregate_glonass_fdma,
                )

                # Cache the preprocessed version
                with self._lock:
                    self._cache[name] = preprocessed_ds

                entry["loaded"] = True
                file_duration = time.time() - file_start

                self._logger.info(
                    "aux_file_load_complete",
                    name=name,
                    duration_seconds=round(file_duration, 2),
                    dataset_size=dict(preprocessed_ds.sizes),
                )
                loaded_count += 1

            except Exception as e:
                file_duration = time.time() - file_start
                self._logger.error(
                    "aux_file_load_failed",
                    name=name,
                    duration_seconds=round(file_duration, 2),
                    error=str(e),
                    exception=type(e).__name__,
                    required=required,
                )
                failed_count += 1

                if required:
                    raise RuntimeError(
                        f"Required auxiliary file '{name}' failed to load: {e}"
                    ) from e
                else:
                    self._logger.warning(
                        "aux_file_optional_skip",
                        name=name,
                        reason="load_failed",
                    )

        duration = time.time() - start_time
        self._logger.info(
            "aux_load_all_complete",
            duration_seconds=round(duration, 2),
            loaded=loaded_count,
            failed=failed_count,
            total=len(self._registry),
        )

    def get(self, name: str) -> xr.Dataset:
        """Get a preprocessed (sid-mapped) auxiliary dataset.

        Thread-safe method for concurrent access during parallel RINEX processing.

        Parameters
        ----------
        name : str
            Name of the registered aux file.

        Returns
        -------
        xr.Dataset
            Preprocessed dataset with 'sid' dimension.

        Raises
        ------
        KeyError
            If aux file not registered.
        ValueError
            If aux file registered but not loaded.

        Examples
        --------
        >>> ephem_ds = pipeline.get('ephemerides')
        >>> clk_ds = pipeline.get('clock')
        """
        if name not in self._registry:
            raise KeyError(
                f"Aux file '{name}' not registered. "
                f"Available: {list(self._registry.keys())}"
            )

        if not self._registry[name]["loaded"]:
            raise ValueError(
                f"Aux file '{name}' registered but not loaded. Call load_all() first."
            )

        with self._lock:
            return self._cache[name]

    def get_ephemerides(self) -> xr.Dataset:
        """Convenience method to get ephemerides dataset."""
        return self.get("ephemerides")

    def get_clock(self) -> xr.Dataset:
        """Convenience method to get clock dataset."""
        return self.get("clock")

    def source_file_paths(self) -> dict[str, Path | None]:
        """On-disk source path for every registered aux file handler.

        ``{name: handler.fpath}``, plus ``{name}_previous_day`` and
        ``{name}_next_day`` for a file registered with neighbors -- lets
        callers (e.g. a cache fingerprint) key off which raw SP3/CLK files
        fed this pipeline without reaching into the private ``_registry``.
        """
        paths: dict[str, Path | None] = {}
        for name, entry in self._registry.items():
            paths[name] = entry["handler"].fpath
            neighbors = entry.get("neighbors")
            if neighbors:
                paths[f"{name}_previous_day"] = neighbors[0].fpath
                paths[f"{name}_next_day"] = neighbors[1].fpath
        return paths

    def get_for_time_range(
        self,
        name: str,
        start_time: np.datetime64,
        end_time: np.datetime64,
        buffer_minutes: int = 5,
    ) -> xr.Dataset:
        """Get aux data sliced for a specific time range with buffer.

        This is useful when processing individual RINEX files that cover
        only a portion of the day (e.g., 15 minutes). The buffer ensures
        we have enough data for interpolation at the boundaries.

        Parameters
        ----------
        name : str
            Name of the registered aux file.
        start_time : np.datetime64
            Start of the time range.
        end_time : np.datetime64
            End of the time range.
        buffer_minutes : int, default 5
            Minutes to add before/after the range for interpolation buffer.

        Returns
        -------
        xr.Dataset
            Aux dataset sliced to the time range (with buffer).

        Examples
        --------
        >>> # Get ephemerides for a 15-minute RINEX file
        >>> rinex_start = np.datetime64('2024-10-29T00:00:00')
        >>> rinex_end = np.datetime64('2024-10-29T00:15:00')
        >>> ephem_slice = pipeline.get_for_time_range(
        ...     'ephemerides', rinex_start, rinex_end, buffer_minutes=5
        ... )
        """
        import numpy as np

        # Get full day's dataset
        full_ds = self.get(name)

        # Add buffer
        buffer = np.timedelta64(buffer_minutes, "m")
        buffered_start = start_time - buffer
        buffered_end = end_time + buffer

        # Slice the dataset
        if "epoch" in full_ds.sizes:
            sliced_ds = full_ds.sel(epoch=slice(buffered_start, buffered_end))
        else:
            # Fallback if epoch dimension has different name
            time_dim = [
                d
                for d in full_ds.sizes
                if "time" in str(d).lower() or "epoch" in str(d).lower()
            ]
            if time_dim:
                sliced_ds = full_ds.sel(
                    {time_dim[0]: slice(buffered_start, buffered_end)}
                )
            else:
                self._logger.warning(
                    f"Could not find time dimension in '{name}', returning full dataset"
                )
                sliced_ds = full_ds

        self._logger.debug(
            f"Sliced '{name}' from {buffered_start} to {buffered_end}: "
            f"{dict(sliced_ds.sizes)}"
        )

        return sliced_ds

    def is_loaded(self, name: str) -> bool:
        """Check if an aux file has been loaded."""
        return name in self._registry and self._registry[name]["loaded"]

    def list_registered(self) -> dict[str, dict]:
        """Get information about all registered aux files.

        Returns
        -------
        dict[str, dict]
            Dictionary with aux file names as keys and metadata as values.
        """
        return {
            name: {
                "required": entry["required"],
                "loaded": entry["loaded"],
                "handler_type": type(entry["handler"]).__name__,
            }
            for name, entry in self._registry.items()
        }

    @classmethod
    def create_standard(
        cls,
        matched_dirs: MatchedDirs,
        aux_file_path: Path,
        agency: str | None = None,
        product_type: str | None = None,
        ftp_server: str | None = None,
        user_email: str | None = None,
        keep_sids: list[str] | None = None,
        fetch_clock: bool | None = None,
        aggregate_glonass_fdma: bool | None = None,
    ) -> AuxDataPipeline:
        """Factory method to create a standard pipeline with ephemerides and
        clock.

        This is a convenience method that creates a pipeline and registers
        ephemerides (always) and clock (unless disabled via ``fetch_clock``
        or ``config.processing.aux_data.fetch_clock``) with standard
        configuration.

        Parameters
        ----------
        matched_dirs : MatchedDirs
            Matched directories containing date information.
        aux_file_path : Path
            Root path for auxiliary files (site's gnss_site_data_root).
        agency : str, optional
            Analysis center code (e.g., "COD"). If None, uses config value.
        product_type : str, optional
            Product type ("final", "rapid"). If None, uses config value.
        ftp_server : str, optional
            FTP server URL. If None, uses config value.
        user_email : str, optional
            Email for authenticated FTP (nasa_earthdata_acc_mail from config).
        keep_sids : list[str] | None, optional
            List of specific SIDs to keep. If None, keeps all possible SIDs.
        fetch_clock : bool, optional
            Whether to also register CLK clock-correction files. If None,
            uses ``config.processing.aux_data.fetch_clock``.
        aggregate_glonass_fdma : bool, optional
            GLONASS FDMA signal IDs as aggregated G1/G2 bands, as the GNSS
            reader produces them. If None, uses
            ``config.processing.params.aggregate_glonass_fdma``.

        Returns
        -------
        AuxDataPipeline
            Configured pipeline with ephemerides (and, unless disabled,
            clock) registered.

        Examples
        --------
        >>> pipeline = AuxDataPipeline.create_standard(matched_dirs, site_root)
        >>> pipeline.load_all()
        >>> ephem_ds = pipeline.get_ephemerides()
        """
        from canvod.config import load_config

        from canvod.auxiliary.clock import ClkFile
        from canvod.auxiliary.ephemeris import Sp3File

        cfg = load_config()
        aux_cfg = cfg.processing.aux_data

        # Use defaults from config if not provided
        agency = agency or aux_cfg.agency
        product_type = product_type or aux_cfg.product_type
        ftp_timeout_s = aux_cfg.ftp_timeout_s
        fetch_clock = aux_cfg.fetch_clock if fetch_clock is None else fetch_clock
        if aggregate_glonass_fdma is None:
            aggregate_glonass_fdma = cfg.processing.params.aggregate_glonass_fdma
        user_email = user_email or cfg.nasa_earthdata_acc_mail
        if ftp_server is None:
            servers = aux_cfg.get_ftp_servers(user_email)
            ftp_server = servers[0][0]

        # Determine aux file paths
        sp3_dir = aux_file_path / _SP3_SUBDIR
        clk_dir = aux_file_path / _CLK_SUBDIR

        # Initialize pipeline
        pipeline = cls(
            matched_dirs=matched_dirs,
            keep_sids=keep_sids,
            aggregate_glonass_fdma=aggregate_glonass_fdma,
        )

        date_obj = matched_dirs.yyyydoy.date
        if date_obj is None:
            raise ValueError("MatchedDirs.yyyydoy must include a valid date")

        def three_days(
            file_cls: type[AuxFile], local_dir: Path
        ) -> tuple[AuxFile, tuple[AuxFile, AuxFile]]:
            """The day's file and those of the previous and the next day."""
            day_str = matched_dirs.yyyydoy.to_str()
            files = {}
            for offset in (0, -1, 1):
                when = date_obj + datetime.timedelta(days=offset)
                try:
                    files[offset] = file_cls.from_datetime_date(
                        date=when,
                        agency=agency,
                        product_type=product_type,
                        ftp_server=ftp_server,
                        local_dir=local_dir,
                        user_email=user_email,
                        ftp_timeout_s=ftp_timeout_s,
                    )
                except RuntimeError as e:
                    if offset == 0:
                        raise
                    which = "previous" if offset < 0 else "next"
                    edge = "first" if offset < 0 else "last"
                    msg = (
                        f"{agency}/{product_type} {file_cls.__name__} of the "
                        f"{which} day ({YYYYDOY.from_date(when).to_str()}) is "
                        f"needed for the {edge} epochs of {day_str}, so that "
                        "they are interpolated, not extrapolated, but it could "
                        "not be obtained. Products are published per GPS week: "
                        "the first day of the next week comes out with that "
                        f"week. Process {day_str} once it is published.\n\n{e}"
                    )
                    raise RuntimeError(msg) from e
            return files[0], (files[-1], files[1])

        # Register ephemerides (REQUIRED), joined with the neighboring days
        sp3_file, sp3_neighbors = three_days(Sp3File, sp3_dir)
        pipeline.register(
            "ephemerides", sp3_file, required=True, neighbors=sp3_neighbors
        )

        # Register clock, unless disabled via config/fetch_clock
        if fetch_clock:
            clk_file, clk_neighbors = three_days(ClkFile, clk_dir)
            pipeline.register("clock", clk_file, required=True, neighbors=clk_neighbors)
            clock_msg = "ephemerides and clock"
        else:
            clock_msg = "ephemerides only (clock fetching disabled)"

        pipeline._logger.info(
            f"Created standard pipeline with {clock_msg} "
            f"for {matched_dirs.yyyydoy.to_str()}"
        )

        return pipeline

    def __repr__(self) -> str:
        """String representation showing registered files."""
        loaded_count = sum(1 for e in self._registry.values() if e["loaded"])
        return (
            f"AuxDataPipeline(date={self.matched_dirs.yyyydoy.to_str()}, "
            f"registered={len(self._registry)}, loaded={loaded_count})"
        )
