"""RINEX processing orchestration and Icechunk writing helpers."""

from __future__ import annotations

import json
import os
import time
import warnings
from collections.abc import Generator, Sequence
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass, field
from datetime import UTC, datetime
from datetime import time as dt_time
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
import pydantic_core
import structlog
import xarray as xr
import zarr
import zarr.errors
from icechunk.session import ForkSession, Session
from icechunk.xarray import to_icechunk
from pydantic import ValidationError
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)

from canvod.auxiliary.cache_fingerprint import (
    CANONICAL_AUX_GRID_SECONDS,
    compute_aux_cache_fingerprint,
)
from canvod.auxiliary.interpolation import (
    aux_epoch_grid,
    interpolate_aux_day,
    sampling_interval_from_epochs,
)
from canvod.auxiliary.pipeline import AuxDataPipeline
from canvod.auxiliary.position import (
    ECEFPosition,
    add_spherical_coords_to_dataset,
    compute_spherical_coordinates,
)
from canvod.auxiliary.products import check_product
from canvod.config import CanvodConfig, load_config
from canvod.config.models import (
    PREPROCESSING_ATTR,
    reference_store_group,
)
from canvod.ops import preprocess_files
from canvod.readers import DataDirMatcher, MatchedDirs
from canvod.readers.gnss_specs.exceptions import NmeaError, RinexError
from canvod.store import GnssResearchSite, scoped_zarr_concurrency
from canvod.store.prepare import prepare_write
from canvod.store.store import _with_run_id
from canvod.store.time_encoding import with_time_units
from canvod.store_metadata.io import commit_with_rebase
from canvod.utils.logging import (
    get_run_id,
    record_stage_timing,
    set_run_id,
    stage_timer,
)
from canvod.utils.tools import (
    _worker_init,
    deprecated,
    get_version_from_pyproject,
    sanitize_directory,
)
from canvodpy.logging.logging_config import active_log_dir, configure_logging
from canvodpy.orchestrator.discovery import (
    ReceiverDay,
    canonical_name_for,
    discover_files,
    parse_sampling_interval_from_filename,
    recipe_file,
)

# ============================================================================
# MODULE-LEVEL FUNCTIONS (Required for loky / ProcessPoolExecutor serialization)
# ============================================================================


def _worker_init_with_run_id(
    nice: int,
    affinity: list[int] | None,
    run_id: str | None,
    log_dir: Path | None,
) -> None:
    """Initialize a worker process, then bind the current run_id.

    Wraps ``canvod.utils.tools``'s ``_worker_init`` (which must stay free of
    any canvodpy dependency) rather than modifying it directly. Contextvars
    don't cross process boundaries, so a worker started under a
    ``ProcessPoolExecutor``/loky pool needs ``run_id`` set explicitly at
    startup for its log records to be correlated with the run that spawned
    it -- see ``logging/run_context.py``.

    Parameters
    ----------
    log_dir : Path | None
        Log folder of the parent process (``active_log_dir()``); the worker
        writes its own per-PID files there. ``None``: the parent logs to the
        console only, and so does the worker.
    """
    _worker_init(nice, affinity)
    if log_dir is not None:
        configure_logging(log_dir=log_dir)
    if run_id is not None:
        set_run_id(run_id)


def _processing_progress(disable: bool = False) -> Progress:
    """Create a Rich progress bar for RINEX processing tasks."""
    return Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        TextColumn("eta"),
        TimeRemainingColumn(),
        disable=disable,
    )


def _warn_if_name_disagrees_with_data(
    log: Any, fname: Path, canonical_name: str, ds: xr.Dataset
) -> None:
    """Warn if a file's first epoch lies outside the time span of its name.

    The day a file is processed for comes from its (canonical) name, so a
    wrong name puts the file on the wrong day. A first epoch up to 60 s
    before the named start is accepted, because some receivers sample on a
    grid offset by a few seconds from the start of the file.
    """
    from canvod.preflight.convention import CanVODFilename

    if not canonical_name or ds.sizes.get("epoch", 0) == 0:
        return
    try:
        named = CanVODFilename.from_filename(canonical_name)
    except ValueError:
        return
    start = (
        np.datetime64(f"{named.year:04d}-01-01T00:00", "s")
        + np.timedelta64(named.doy - 1, "D")
        + np.timedelta64(named.hour, "h")
        + np.timedelta64(named.minute, "m")
    )
    end = start + np.timedelta64(int(named.batch_duration.total_seconds()), "s")
    first = np.datetime64(ds.epoch.min().values, "s")
    if not start - np.timedelta64(60, "s") <= first < end:
        log.warning(
            "file_time_differs_from_name",
            file=str(Path(fname).name),
            canonical_name=canonical_name,
            named_start=str(start),
            first_epoch=str(first),
            hint=(
                "The file is processed for the day in its name. Check the "
                "filename or the naming recipe."
            ),
        )


def run_reader_options(reader_name: str) -> dict[str, Any]:
    """Options a run passes to a reader besides the file path.

    The RINEX v3 readers check their number of epochs on construction, but
    only know the intended file length when told. A run checks every file
    against the period and sampling interval of its canonical name instead
    (:func:`_warn_if_epoch_count_differs_from_name`), for all formats, and
    keeps the epochs a file has, so the readers' own check is off.
    """
    if reader_name in ("rinex3", "rinex3_stripped"):
        return {"completeness_mode": "off"}
    return {}


def _warn_if_epoch_count_differs_from_name(
    log: Any, fname: Path, canonical_name: str, ds: xr.Dataset
) -> None:
    """Warn if a file holds fewer or more epochs than its name implies.

    The canonical name gives the file's period and sampling interval
    (``15M_05S``: 180 epochs). Fewer epochs mean the receiver stopped
    logging (e.g. a power loss) or epochs were dropped as invalid while
    reading; the epochs the file has are kept. Call it on the dataset as
    read, before any temporal aggregation.
    """
    from canvod.preflight.convention import CanVODFilename

    if not canonical_name:
        return
    try:
        named = CanVODFilename.from_filename(canonical_name)
    except ValueError:
        return
    n_expected = round(named.batch_duration / named.sampling_interval)
    n_found = int(np.unique(ds.epoch.values).size) if "epoch" in ds.dims else 0
    if n_found != n_expected:
        log.warning(
            "epoch_count_differs_from_name",
            file=str(Path(fname).name),
            canonical_name=canonical_name,
            expected_epochs=n_expected,
            found_epochs=n_found,
            missing_epochs=max(0, n_expected - n_found),
            hint=(
                "Fewer epochs: the receiver stopped logging or epochs were "
                "dropped as invalid; the file's other epochs are kept. More "
                "epochs: check the sampling field of the filename or recipe."
            ),
        )


def _warn_if_aux_grid_coarser(
    log: Any, rnx_file: Path, ds: xr.Dataset, aux_store: xr.Dataset
) -> None:
    """Warn if the ephemeris grid is coarser than the file's sampling.

    The grid interval comes from the sampling field of the filename when it
    can be parsed. If that field is wrong, each observation epoch is matched
    to the nearest grid epoch instead of its own, without an error.
    """
    if ds.sizes.get("epoch", 0) < 2 or aux_store.sizes.get("epoch", 0) < 2:
        return
    data_step = float(np.median(np.diff(ds.epoch.values)) / np.timedelta64(1, "s"))
    aux_epochs = aux_store.epoch.values[:2]
    grid_step = float((aux_epochs[1] - aux_epochs[0]) / np.timedelta64(1, "s"))
    if data_step < grid_step:
        log.warning(
            "sampling_mismatch",
            file=str(rnx_file.name),
            data_sampling_s=data_step,
            ephemeris_grid_s=grid_step,
            hint=(
                "The file is sampled more finely than the ephemeris grid, so "
                "satellite positions are taken from the nearest grid epoch. "
                "Check the sampling field of the filename or naming recipe."
            ),
        )


def _preprocess_file(
    rnx_file: Path,
    keep_vars: list[str] | None,
    aux_zarr_path: Path,
    receiver_positions: dict[str, ECEFPosition],
    receiver_type: str,
    keep_sids: list[str] | None,
    reader_name: str,
    store_radial_distance: bool,
    store_sbf_raw_observables: bool,
    pad_global_sid: bool,
    aux_group: str | None,
    rinex_v3_parser: str,
    aggregate_glonass_fdma: bool,
    use_sbf_geometry: bool = False,
    broadcast_canopy_file: Path | None = None,
    broadcast_canopy_fmt: str | None = None,
    date_key: str | None = None,
) -> tuple[Path, dict[str, xr.Dataset], dict[str, xr.Dataset], dict[str, list[str]]]:
    """Read one GNSS file once and add the geometry for each receiver position.

    The single implementation behind ``preprocess_with_hermite_aux`` (one
    position) and ``preprocess_reference_with_hermite_aux_fanout`` (one
    position per canopy pairing). Reading, the ephemeris join and the SID
    filter run once; only the geometry step depends on the position.

    Parameters
    ----------
    receiver_positions : dict[str, ECEFPosition]
        ``{name: position}``; one augmented dataset is returned per entry.
    use_sbf_geometry : bool, default False
        SBF files only, and only with a single position: take θ/φ from the
        SBF SatVisibility blocks via ``SbfBroadcastProvider`` instead of the
        aux data.

    Other parameters are those of ``preprocess_with_hermite_aux``.

    Returns
    -------
    tuple[Path, dict[str, xr.Dataset], dict[str, xr.Dataset], dict[str, list[str]]]
        File path, ``{name: augmented dataset}``, auxiliary datasets dict,
        and SID issue dict with keys ``not_in_global_space``,
        ``dropped_by_filter``, ``dropped_no_ephemeris``.

    """
    from canvod.readers.preprocessing import (
        flush_sid_accumulators,
        reset_sid_accumulators,
    )

    sbf_geometry = reader_name == "sbf" and use_sbf_geometry
    if sbf_geometry and len(receiver_positions) != 1:
        msg = "SBF geometry supports exactly one receiver position per file"
        raise ValueError(msg)

    # Clear any SID-issue accumulation left over from earlier work in this
    # process (e.g. aux/ephemeris padding during Phase 1 never flushes) so
    # this call's sid_issues reflects only its own pad_to_global_sid() calls.
    reset_sid_accumulators()

    log = structlog.get_logger(__name__).bind(
        file=str(rnx_file.name), receiver_type=receiver_type
    )
    # A shared reference file (fan-out) is timed under the names of all
    # its pairings; receiver_type is then only a scheduling key.
    timed_receiver = (
        receiver_type
        if receiver_type in receiver_positions
        else "+".join(sorted(receiver_positions))
    )

    with stage_timer(
        "rinex.process_file", file=str(rnx_file.name), receiver=timed_receiver
    ):
        try:
            t0 = time.perf_counter()
            log.info("rinex_preprocessing_started", pairings=len(receiver_positions))

            # 1. Read GNSS file (reader selected via factory)
            log.debug("reading_gnss_file", file=str(rnx_file.name), reader=reader_name)
            from canvodpy.factories import ReaderFactory

            rnx = ReaderFactory.create(
                reader_name,
                fpath=rnx_file,
                aggregate_glonass_fdma=aggregate_glonass_fdma,
                **run_reader_options(reader_name),
            )
            ds, aux_datasets = rnx.to_ds_and_auxiliary(
                keep_data_vars=keep_vars,
                write_global_attrs=True,
                keep_sids=keep_sids,
                store_raw_observables=store_sbf_raw_observables,
                pad_global_sid=pad_global_sid,
                parser=rinex_v3_parser,
            )
            ds.attrs["File Hash"] = rnx.file_hash
            t_rinex = time.perf_counter()

            # SBF-geometry fast path: use receiver-reported theta/phi, skip ephemeris
            if sbf_geometry:
                from canvod.auxiliary.ephemeris.provider import SbfBroadcastProvider

                # Reference receiver in shared position mode: the canopy
                # file's geometry, else this file's own sbf_obs.
                provider = SbfBroadcastProvider(
                    canopy_file=broadcast_canopy_file,
                    canopy_reader_format=broadcast_canopy_fmt or "sbf",
                    keep_sids=keep_sids,
                )
                ((name, receiver_position),) = receiver_positions.items()
                ds = provider.augment_dataset(
                    ds, receiver_position, aux_datasets=aux_datasets
                )
                sid_issues = flush_sid_accumulators()
                sid_issues["dropped_no_ephemeris"] = []
                return rnx_file, {name: ds}, aux_datasets, sid_issues
            log.debug(
                "rinex_loaded",
                dims=dict(ds.sizes),
                data_vars=list(ds.data_vars.keys()),
                coords=list(ds.coords.keys()),
                epochs=len(ds.epoch),
                sids=len(ds.sid),
            )

            # Filter variables
            if keep_vars:
                available_vars = [var for var in keep_vars if var in ds.data_vars]
                if available_vars:
                    ds = ds[available_vars]

            # 2. Open preprocessed aux data and select matching epochs
            aux_store = xr.open_zarr(
                aux_zarr_path,
                group=aux_group,
                decode_timedelta=True,
                consolidated=False,
            )
            _warn_if_aux_grid_coarser(log, rnx_file, ds, aux_store)
            aux_slice = aux_store.sel(epoch=ds.epoch, method="nearest")

            # Eagerly load aux slice — batches all Zarr reads (X, Y, Z, clock)
            # in one pass instead of 3-4 separate lazy loads later
            aux_slice = aux_slice.load()
            t_aux = time.perf_counter()

            # 3. Find common SIDs between RINEX and aux data (inner join)
            rinex_sids = set(ds.sid.values)
            aux_sids = set(aux_slice.sid.values)
            common_sids = sorted(rinex_sids.intersection(aux_sids))

            if not common_sids:
                log.error(
                    "sid_intersection_empty",
                    rinex_sids=len(rinex_sids),
                    aux_sids=len(aux_sids),
                )
                raise ValueError(
                    f"No common SIDs found between RINEX ({len(rinex_sids)} sids) "
                    f"and aux data ({len(aux_sids)} sids)"
                )

            # Filter both datasets to common SIDs
            rinex_only = rinex_sids - aux_sids
            aux_only = aux_sids - rinex_sids
            ds = ds.sel(sid=common_sids)
            aux_slice = aux_slice.sel(sid=common_sids)
            t_sid = time.perf_counter()

            log.debug(
                "sid_filtering_complete",
                rinex_sids=len(rinex_sids),
                aux_sids=len(aux_sids),
                common_sids=len(common_sids),
                rinex_only=len(rinex_only),
                aux_only=len(aux_only),
            )
            if rinex_only:
                log.warning(
                    "sids_dropped_no_ephemeris",
                    file=str(rnx_file.name),
                    count=len(rinex_only),
                    sids=sorted(rinex_only),
                    hint=(
                        "These SIDs were observed in the file but have no matching "
                        "entry in the ephemeris/clock aux data and will be absent "
                        "from the stored dataset."
                    ),
                )

            # 4. Compute spherical coordinates (phi, theta, r) from
            # ephemerides, once per receiver position: the only step that
            # depends on the position.
            log.debug("computing_spherical_coordinates")
            ds_augmented: dict[str, xr.Dataset] = {}
            for name, receiver_position in receiver_positions.items():
                ds_name = _compute_spherical_coords_fast(
                    ds,
                    aux_slice,
                    receiver_position,
                )
                if not store_radial_distance and "r" in ds_name:
                    ds_name = ds_name.drop_vars("r")
                ds_augmented[name] = ds_name
            t_coords = time.perf_counter()

            log.info(
                "rinex_preprocessing_complete",
                total_seconds=round(t_coords - t0, 2),
                rinex_read_seconds=round(t_rinex - t0, 2),
                aux_load_seconds=round(t_aux - t_rinex, 2),
                sid_filter_seconds=round(t_sid - t_aux, 4),
                coords_seconds=round(t_coords - t_sid, 2),
                pairings=len(receiver_positions),
            )

            # The performance dashboard's per-day breakdown
            # (reading/validating/augmenting/writing), from the checkpoints
            # above rather than nested stage_timer() blocks.
            for _stage, _seconds in (
                ("reading", t_rinex - t0),
                ("validating", t_sid - t_aux),
                ("augmenting", (t_aux - t_rinex) + (t_coords - t_sid)),
            ):
                record_stage_timing(
                    _stage, _seconds, receiver=timed_receiver, date_key=date_key
                )
        except (
            OSError,
            RuntimeError,
            ValueError,
            ValidationError,
            RinexError,
            NmeaError,
        ) as e:
            log.error(
                "rinex_preprocessing_failed",
                error=str(e),
                exception=type(e).__name__,
                file=str(rnx_file.name),
                traceback_available=True,
            )
            raise

    sid_issues = flush_sid_accumulators()
    sid_issues["dropped_no_ephemeris"] = sorted(rinex_only)
    return rnx_file, ds_augmented, aux_datasets, sid_issues


def preprocess_with_hermite_aux(
    rnx_file: Path,
    keep_vars: list[str] | None,
    aux_zarr_path: Path,
    receiver_position: ECEFPosition,
    receiver_type: str,
    keep_sids: list[str] | None = None,
    reader_name: str = "rinex3",
    use_sbf_geometry: bool = False,
    store_radial_distance: bool = False,
    store_sbf_raw_observables: bool = True,
    broadcast_canopy_file: Path | None = None,
    broadcast_canopy_fmt: str | None = None,
    pad_global_sid: bool = True,
    aux_group: str | None = None,
    rinex_v3_parser: str = "validated",
    aggregate_glonass_fdma: bool = True,
    date_key: str | None = None,
) -> tuple[Path, xr.Dataset, dict[str, xr.Dataset], dict[str, list[str]]]:
    """Read RINEX and compute coordinates using Hermite-interpolated aux data from Zarr.

    This function runs in separate processes, so it must be at module level.
    The aux data has already been interpolated using proper Hermite splines.

    Parameters
    ----------
    rnx_file : Path
        RINEX file path
    keep_vars : List[str]
        Variables to keep
    aux_zarr_path : Path
        Path to preprocessed aux data Zarr store (with Hermite interpolation)
    receiver_position : ECEFPosition
        Receiver position (computed once)
    receiver_type : str
        Receiver type
    keep_sids : list[str] | None, default None
        List of specific SIDs to keep. If None, keeps all possible SIDs.
    use_sbf_geometry : bool, default False
        If True and reader_name is "sbf", skip external orbit/clock downloads
        and transfer theta/phi directly from SBF SatVisibility blocks via
        ``SbfBroadcastProvider`` (ephemeris-based angles only; raises if the
        file has none).
    store_radial_distance : bool, default False
        If True, keep the radial distance variable ``r`` in the output.
    broadcast_canopy_file : Path | None, default None
        Path to the matching canopy SBF file. When provided (for reference
        receivers in shared position mode), its sbf_obs theta/phi override
        the reference file's own geometry.
    broadcast_canopy_fmt : str | None, default None
        Reader format for the canopy file (e.g. "sbf").
    aux_group : str | None, default None
        Zarr group within ``aux_zarr_path`` to read this day's aux data
        from (shared-cache mode). ``None`` reads the store root,
        matching legacy per-site aux Zarr layout.
    rinex_v3_parser : {"validated", "unvalidated_fast"}, default "validated"
        Parser of RINEX v3 files (``processing.params.rinex_v3_parser``);
        ignored by the other readers.
    aggregate_glonass_fdma : bool, default True
        Aggregate the GLONASS FDMA channels into one G1 and one G2 band
        (``processing.params.aggregate_glonass_fdma``). Passed to the reader;
        the aux data at ``aux_zarr_path`` must use the same setting.
    date_key : str | None, default None
        Processing day (``YYYYDOY``) the file belongs to, added to the
        ``stage_timing`` events. ``None`` leaves the day out.

    Returns
    -------
    tuple[Path, xr.Dataset, dict[str, xr.Dataset], dict[str, list[str]]]
        File path, augmented dataset with phi/theta/r, auxiliary datasets dict,
        and SID issue dict with keys ``not_in_global_space``, ``dropped_by_filter``,
        ``dropped_no_ephemeris``.

    """
    path, by_position, aux_datasets, sid_issues = _preprocess_file(
        rnx_file,
        keep_vars,
        aux_zarr_path,
        {receiver_type: receiver_position},
        receiver_type,
        keep_sids,
        reader_name,
        store_radial_distance,
        store_sbf_raw_observables,
        pad_global_sid,
        aux_group,
        rinex_v3_parser,
        aggregate_glonass_fdma,
        use_sbf_geometry=use_sbf_geometry,
        broadcast_canopy_file=broadcast_canopy_file,
        broadcast_canopy_fmt=broadcast_canopy_fmt,
        date_key=date_key,
    )
    return path, by_position[receiver_type], aux_datasets, sid_issues


def _task_args(func: Any, is_reference_fanout: bool, **kwargs: Any) -> tuple:
    """Build a positional task tuple for *func* from keyword arguments.

    ``pipeline.py`` splats the tuple (minus the trailing fan-out marker)
    positionally into *func*. Binding by name against *func*'s signature
    puts every value in its own parameter slot, so adding or reordering a
    parameter cannot silently shift the others.
    """
    import inspect

    bound = inspect.signature(func).bind(**kwargs)
    bound.apply_defaults()
    return (*bound.arguments.values(), is_reference_fanout)


def preprocess_reference_with_hermite_aux_fanout(
    rnx_file: Path,
    keep_vars: list[str] | None,
    aux_zarr_path: Path,
    canopy_positions: dict[str, ECEFPosition],
    receiver_type: str,
    keep_sids: list[str] | None = None,
    reader_name: str = "rinex3",
    store_radial_distance: bool = False,
    store_sbf_raw_observables: bool = True,
    pad_global_sid: bool = True,
    aux_group: str | None = None,
    rinex_v3_parser: str = "validated",
    aggregate_glonass_fdma: bool = True,
    date_key: str | None = None,
) -> tuple[Path, dict[str, xr.Dataset], dict[str, xr.Dataset], dict[str, list[str]]]:
    """Read a shared reference file once, then compute geometry per canopy pairing.

    A reference receiver paired with N canopies gets read, SID-filtered, and
    ephemeris-joined identically for every pairing; only the geometry step
    (``_compute_spherical_coords_fast``, which substitutes in the paired
    canopy's position) differs per pairing. Doing the shared steps once,
    inside a single worker call, avoids re-parsing the same file N times
    without serializing the parsed intermediate across a process-pool
    boundary. Each pairing's dataset is identical to what
    ``preprocess_with_hermite_aux`` returns for that canopy's position.

    The ``use_sbf_geometry`` path of ``preprocess_with_hermite_aux`` is not
    available here: it takes θ/φ from one SBF file, not per position.

    Parameters
    ----------
    canopy_positions : dict[str, ECEFPosition]
        ``{pairing_name: canopy_receiver_position}`` for every canopy this
        reference file is paired against (e.g. ``{"reference_01_canopy_01":
        ECEFPosition(...), "reference_01_canopy_02": ECEFPosition(...)}``).
    aux_group : str | None, default None
        Zarr group within ``aux_zarr_path`` to read this day's aux data
        from (shared-cache mode). ``None`` reads the store root.

    Other parameters are those of ``preprocess_with_hermite_aux``.

    Returns
    -------
    tuple[Path, dict[str, xr.Dataset], dict[str, xr.Dataset], dict[str, list[str]]]
        File path, ``{pairing_name: ds_augmented}`` for every pairing in
        ``canopy_positions``, auxiliary datasets dict, and SID issue dict.

    """
    return _preprocess_file(
        rnx_file,
        keep_vars,
        aux_zarr_path,
        canopy_positions,
        receiver_type,
        keep_sids,
        reader_name,
        store_radial_distance,
        store_sbf_raw_observables,
        pad_global_sid,
        aux_group,
        rinex_v3_parser,
        aggregate_glonass_fdma,
        date_key=date_key,
    )


def _compute_spherical_coords_fast(
    rinex_ds: xr.Dataset,
    aux_ds: xr.Dataset,
    rx_pos: ECEFPosition,
) -> xr.Dataset:
    """Compute spherical coordinates using shared utility function.

    This function is used by the parallel processor and must remain
    at module level for loky / ProcessPoolExecutor serialization.
    """
    # Get satellite positions (already interpolated with Hermite splines)
    sat_x = aux_ds["X"].values
    sat_y = aux_ds["Y"].values
    sat_z = aux_ds["Z"].values

    # Compute using shared function
    r, theta, phi = compute_spherical_coordinates(sat_x, sat_y, sat_z, rx_pos)

    # Add to dataset using shared function
    rinex_ds = add_spherical_coords_to_dataset(rinex_ds, r, theta, phi)

    # Optionally add clock corrections if available
    if "clock" in aux_ds.data_vars:
        rinex_ds = rinex_ds.assign({"clock": aux_ds["clock"]})

    return rinex_ds


# ============================================================================
# Coordinated Parallel Writing to Icechunk
# ============================================================================


def _sanitize_ds_for_write(ds: xr.Dataset) -> xr.Dataset:
    # Make a shallow copy and strip obviously non-serializable attrs
    ds = ds.copy()
    # Keep only simple types in .attrs
    clean_attrs = {}
    for k, v in list(ds.attrs.items()):
        if isinstance(v, (str, int, float, bool, type(None), np.generic)):
            clean_attrs[k] = v
        # allow numpy scalars
        elif isinstance(v, (np.integer, np.floating, np.bool_)):
            clean_attrs[k] = v.item()
        # else drop it silently
    ds.attrs = clean_attrs

    # Normalize encodings to be conservative (avoid dtype surprises)
    for vname in ds.data_vars:
        var = ds[vname]
        enc = var.encoding or {}
        # ensure dtype is a concrete numpy dtype if present
        if "dtype" in enc:
            enc["dtype"] = np.dtype(var.dtype)
        # drop object encodings we don't control
        for bad in ("compressor", "filters", "chunks", "preferred_chunks"):
            enc.pop(bad, None)
        var.encoding = enc
    return ds


def write_initial_rinex_ds_to_store(
    *,
    ds: xr.Dataset,
    fork: ForkSession,
    group: str,
) -> ForkSession:
    """Write a new receiver group to the store."""
    ds = prepare_write(_sanitize_ds_for_write(ds), fork.store, group, append_dim=None)
    ds.to_zarr(
        fork.store,
        group=group,
        consolidated=False,
        mode="w",  # create group
    )
    return fork


def append_rinex_ds_to_store(
    *,
    ds: xr.Dataset,
    fork: ForkSession,
    group: str,
) -> ForkSession:
    """Append to an existing receiver group in the store."""
    ds = prepare_write(_sanitize_ds_for_write(ds), fork.store, group, append_dim=None)
    ds.to_zarr(
        fork.store,
        region="auto",
        group=group,
        consolidated=False,
        mode="a",
    )
    return fork


@deprecated(
    "worker_task() is left over from development and will be removed with the next major version. "
    "Use preprocess_with_hermite_aux() instead."
)
def worker_task(
    rinex_file: Path,
    keep_vars: list[str],
    aux_zarr_path: Path,
    receiver_position: ECEFPosition,
    receiver_type: str,
    receiver_name: str,
    fork: ForkSession,
    is_first: bool,
    keep_sids: list[str] | None = None,
    reader_name: str = "rinex3",
) -> tuple[Path, ForkSession]:
    """Build an augmented dataset and write it to the given fork."""
    # 1) build augmented dataset
    fname, ds_augmented, _aux, _sids = preprocess_with_hermite_aux(
        rinex_file,
        keep_vars,
        aux_zarr_path,
        receiver_position,
        receiver_type,
        keep_sids,
        reader_name,
    )

    # 2) write to this fork (initial or append)
    if is_first:
        write_initial_rinex_ds_to_store(
            ds=ds_augmented,
            fork=fork,
            group=receiver_name,
        )
    else:
        append_rinex_ds_to_store(
            ds=ds_augmented,
            fork=fork,
            group=receiver_name,
        )

    # 3) return ONLY pickleable things (Path + ForkSession)
    return fname, fork


@deprecated(
    "worker_task_append_only() is left over from development and will be removed with the next major version. "
    "Use preprocess_with_hermite_aux() instead."
)
def worker_task_append_only(
    rinex_file: Path,
    keep_vars: list[str],
    aux_zarr_path: Path,
    receiver_position: ECEFPosition,
    receiver_type: str,
    receiver_name: str,
    fork: ForkSession,
    keep_sids: list[str] | None = None,
    reader_name: str = "rinex3",
) -> tuple[Path, ForkSession]:
    """Worker that only appends (group already exists)."""
    fname, ds_augmented, _aux, _sids = preprocess_with_hermite_aux(
        rinex_file,
        keep_vars,
        aux_zarr_path,
        receiver_position,
        receiver_type,
        keep_sids,
        reader_name,
    )

    ds_clean = prepare_write(
        _sanitize_ds_for_write(ds_augmented),
        fork.store,
        receiver_name,
        append_dim="epoch",
    )
    ds_clean.to_zarr(
        fork.store,
        group=receiver_name,
        mode="a",
        append_dim="epoch",
        consolidated=False,
    )

    return fname, fork


def worker_task_with_region_auto(
    rinex_file: Path,
    keep_vars: list[str],
    aux_zarr_path: Path,
    receiver_position: ECEFPosition,
    receiver_type: str,
    receiver_name: str,
    fork: ForkSession,
    keep_sids: list[str] | None = None,
    reader_name: str = "rinex3",
    store_sbf_raw_observables: bool = True,
) -> ForkSession:
    """Worker uses region='auto' to write to correct position."""
    _fname, ds, _aux, _sids = preprocess_with_hermite_aux(
        rinex_file,
        keep_vars,
        aux_zarr_path,
        receiver_position,
        receiver_type,
        keep_sids,
        reader_name,
        store_sbf_raw_observables=store_sbf_raw_observables,
    )

    ds_clean = prepare_write(
        _sanitize_ds_for_write(ds), fork.store, receiver_name, append_dim=None
    )
    ds_clean.to_zarr(
        fork.store,
        group=receiver_name,
        mode="a",
        region="auto",  # ✅ Let xarray infer the region
        consolidated=False,
    )

    return fork  # Return the modified fork


# ============================================================================
# Cross-group fork/merge batch writes
# ============================================================================


@dataclass
class GroupWritePlan:
    """One receiver group's dedup-checked write plan, pre-fork.

    Built by `RinexDataProcessor._prepare_group_write` -- a pure
    metadata-table read, no session/fork involved -- so it's safe to compute
    for every group before any fork exists.
    """

    receiver_name: str
    augmented_datasets: list[tuple[Path, xr.Dataset]]
    rinex_files: list[Path]
    aux_datasets: dict[Path, dict[str, xr.Dataset]] | None
    sid_issues: dict[str, list[str]] | None
    reader_format: str | None
    file_hash_map: dict[Path, str | None]
    existing_hashes: set[str]


@dataclass
class GroupWriteResult:
    """One receiver group's outcome from a forked (or pre-pass-only) write."""

    receiver_name: str
    fork: ForkSession | None
    actions: dict[str, int] = field(
        default_factory=lambda: {
            "initial": 0,
            "skipped": 0,
            "appended": 0,
            "written": 0,
        }
    )
    metadata_records: list[dict[str, Any]] = field(default_factory=list)
    file_append_seconds: list[float] = field(default_factory=list)
    total_epochs: int = 0
    total_nbytes: int = 0
    existing_hashes: set[str] = field(default_factory=set)
    aux_datasets: dict[Path, dict[str, xr.Dataset]] | None = None
    reader_format: str | None = None
    duration_seconds: float = 0.0
    snapshot_id: str | None = None


# ============================================================================
# MAIN (HALF-PARALLEL) PROCESSOR CLASS
# ============================================================================


class RinexDataProcessor:
    """Orchestrates RINEX data processing with optimized parallelization.

    Pipeline:
    1. Initialize auxiliary data (ephemerides, clock) - ONCE
    2. Preprocess aux data with Hermite splines to disk - ONCE per day
    3. Parallel process RINEX files via ProcessPoolExecutor
    4. Each worker reads its time slice from preprocessed Zarr
    5. Compute spherical coordinates and append to Icechunk store
    6. Yield final daily datasets

    Parameters
    ----------
    matched_data_dirs : MatchedDirs
        Matched directories for canopy and reference data
    site : GnssResearchSite
        Research site with Icechunk stores
    aux_file_path : Path, optional
        Root path for auxiliary files
    n_max_workers : int | None, default None
        Maximum parallel workers (CPUs) for RINEX processing.
        ``None`` lets ``ProcessPoolExecutor`` auto-detect via
        ``os.cpu_count()``.

    """

    def __init__(
        self,
        matched_data_dirs: MatchedDirs,
        site: GnssResearchSite,
        aux_file_path: Path | None = None,
        n_max_workers: int | None = None,
        reader_name: str = "rinex3",
        use_sbf_geometry: bool = False,
        config: CanvodConfig | None = None,
    ) -> None:
        t_init_start = time.perf_counter()

        self.matched_data_dirs = matched_data_dirs
        self.site = site
        self.aux_file_path = aux_file_path
        if n_max_workers is not None:
            self.n_max_workers = min(n_max_workers, os.cpu_count() or n_max_workers)
        else:
            self.n_max_workers = None
        self._reader_name = reader_name  # fallback; prefer per-receiver reader_format
        # use_sbf_geometry: explicit param wins, otherwise read from config
        self._use_sbf_geometry_override = use_sbf_geometry
        self._logger = structlog.get_logger(__name__).bind(
            site=site.site_name,
            workers=self.n_max_workers or os.cpu_count(),
            component="processor",  # Enable component-specific logging
        )
        # Dedicated logger for icechunk store operations
        self._icechunk_log = structlog.get_logger(__name__).bind(
            site=site.site_name,
            component="icechunk",
        )

        t_config_start = time.perf_counter()
        if config is None:
            warnings.warn(
                "Creating RinexDataProcessor without config= is left over from development "
                "and will be removed with the next major version. Pass "
                "config=canvod.config.load_config() instead.",
                FutureWarning,
                stacklevel=2,
            )
            config = load_config()
        self._config = config
        # Physical path -> canonical canVOD filename, filled by
        # _get_rinex_files and read when building log-book rows.
        self._canonical_names: dict[Path, str] = {}
        self._keeper_tags_enabled: bool = config.processing.storage.keeper_tags
        self.keep_sids = config.sids.get_sids()

        # Resolve ephemeris source: explicit param > config > default (final)
        if self._use_sbf_geometry_override:
            self.use_sbf_geometry = True
        else:
            self.use_sbf_geometry = (
                config.processing.params.ephemeris_source == "broadcast"
            )

        # Cache config values formerly in globals
        aux_cfg = config.processing.aux_data
        self._agency = aux_cfg.agency
        self._product_type = aux_cfg.product_type
        if not self.use_sbf_geometry:
            # Fail before any file is read, not at the first day's download
            check_product(aux_cfg.agency, aux_cfg.product_type, aux_cfg.fetch_clock)
        servers = aux_cfg.get_ftp_servers(config.nasa_earthdata_acc_mail)
        self._ftp_server = servers[0][0]
        self._gnss_store_strategy = config.processing.storage.gnss_store_strategy
        t_config_end = time.perf_counter()

        self._logger.info(
            "processor_initialized",
            aux_file_path=str(aux_file_path) if aux_file_path else None,
            sid_filtering=len(self.keep_sids) if self.keep_sids else "all",
            cpu_count=os.cpu_count(),
            config_load_seconds=round(t_config_end - t_config_start, 4),
        )

        # Initialize auxiliary data pipeline (loads SP3 and CLK files)
        # Skip when using broadcast ephemerides (no SP3/CLK needed)
        if self.use_sbf_geometry:
            self.aux_pipeline = None
            self._logger.info(
                "aux_pipeline_skipped",
                reason="ephemeris_source=broadcast, using SBF SatVisibility",
            )
        else:
            self.aux_pipeline = self._initialize_aux_pipeline()

        t_init_end = time.perf_counter()
        self._logger.info(
            "processor_init_complete",
            total_init_seconds=round(t_init_end - t_init_start, 2),
            config_seconds=round(t_config_end - t_config_start, 4),
            aux_pipeline_seconds=round(t_init_end - t_config_end, 2),
        )

    def _initialize_aux_pipeline(self) -> AuxDataPipeline:
        """Initialize and load auxiliary data pipeline.

        Returns
        -------
        AuxDataPipeline
            Loaded pipeline with ephemerides and clock data

        """
        t0 = time.perf_counter()
        self._logger.info(
            "aux_pipeline_initialization_started",
            agency=self._agency,
            product_type=self._product_type,
        )

        # Use cached config (avoids re-reading YAML)
        config = self._config
        user_email = config.nasa_earthdata_acc_mail

        # Determine aux_file_path: explicit > config aux_data_dir > site data root
        aux_file_path = self.aux_file_path
        if aux_file_path is None:
            configured_aux_dir = config.processing.storage.aux_data_dir
            if configured_aux_dir is not None:
                aux_file_path = configured_aux_dir
            else:
                aux_file_path = Path(self.site.site_config["gnss_site_data_root"])

        t1 = time.perf_counter()
        pipeline = AuxDataPipeline.create_standard(
            matched_dirs=self.matched_data_dirs,
            aux_file_path=aux_file_path,
            agency=self._agency,
            product_type=self._product_type,
            ftp_server=self._ftp_server,
            user_email=user_email,
            keep_sids=self.keep_sids,
            aggregate_glonass_fdma=config.processing.params.aggregate_glonass_fdma,
        )
        t2 = time.perf_counter()

        self._logger.info(
            "aux_pipeline_create_standard_complete",
            duration_seconds=round(t2 - t1, 2),
        )

        # Load all auxiliary files into memory
        pipeline.load_all()
        t3 = time.perf_counter()

        self._logger.info(
            "aux_pipeline_initialization_complete",
            total_seconds=round(t3 - t0, 2),
            create_standard_seconds=round(t2 - t1, 2),
            load_all_seconds=round(t3 - t2, 2),
            products=list(pipeline._cache.keys())
            if hasattr(pipeline, "_cache")
            else [],
        )
        return pipeline

    def _make_reader(self, fpath: Path, reader_format: str | None = None):
        """Instantiate the configured GNSS reader for *fpath*.

        Parameters
        ----------
        fpath : Path
            GNSS data file.
        reader_format : str | None
            Reader format override.  Falls back to ``self._reader_name``.

        """
        from canvodpy.factories import ReaderFactory

        aggregate = self._config.processing.params.aggregate_glonass_fdma
        name = reader_format or self._reader_name
        return ReaderFactory.create(
            name,
            fpath=fpath,
            aggregate_glonass_fdma=aggregate,
            **run_reader_options(name),
        )

    _parse_sampling_interval_from_filename = staticmethod(
        parse_sampling_interval_from_filename
    )

    def _preprocess_aux_data_with_hermite(
        self,
        rinex_files: list[Path],
        output_path: Path,
        reader_format: str | None = None,
        group: str | None = None,
        grid_seconds: float | None = None,
    ) -> float:
        """Preprocess auxiliary data using proper interpolation strategies.

        Parameters
        ----------
        group : str | None
            Zarr group to write under (e.g. a shared-cache fingerprint
            path). ``None`` (default) writes to the store root, unchanged
            legacy behavior.
        grid_seconds : float | None
            When set (shared-cache mode), build the target epoch grid
            from this fixed interval instead of the detected
            ``sampling_interval`` -- a site-independent grid is required
            for the cache entry to be safely shared across sites with
            different sampling rates. ``sampling_interval`` is still
            detected and returned either way.
        """
        t0 = time.perf_counter()
        self._logger.info(
            "aux_preprocessing_started",
            rinex_files=len(rinex_files),
            output_path=str(output_path),
            interpolation_method="hermite_cubic",
        )

        # 1. Sampling interval: from the file name, else from the first file
        sampling_interval = self._parse_sampling_interval_from_filename(
            rinex_files[0].name,
        )
        # Derive day_start from the YYYYDOY we already know
        day_date = self.matched_data_dirs.yyyydoy.date
        day_start = np.datetime64(day_date, "D")

        if sampling_interval is not None:
            t1 = time.perf_counter()
            self._logger.info(
                "sampling_detected",
                sampling_interval_seconds=sampling_interval,
                source="filename",
                detection_seconds=round(t1 - t0, 4),
            )
        else:
            # Fallback: read first GNSS file (slow path)
            self._logger.debug(
                "sampling_detection_started",
                sample_file=rinex_files[0].name,
                reason="filename_parse_failed",
            )
            first_rnx = self._make_reader(rinex_files[0], reader_format)
            first_ds = first_rnx.to_ds(
                keep_data_vars=[],
                write_global_attrs=True,
            )
            t1 = time.perf_counter()
            sampling_interval = sampling_interval_from_epochs(first_ds.epoch.values)
            # day_start stays as derived from the known YYYYDOY -- do NOT
            # re-derive it from first_ds.epoch here. A file's first epoch can
            # fall a few seconds before the day boundary (SBF epochs did, by
            # the 18 leap seconds, while they were stored in UTC). Truncating
            # that epoch to a date used to silently shift the whole day's
            # target_epochs grid back by 24h, which pushed nearly every real
            # observation epoch outside the aux data's interpolated range --
            # .sel(..., method="nearest") then clamped every one of them to
            # the grid's last (wrong-day) point, producing a single constant,
            # usually-wrong satellite position reused for the entire day
            # (canvodpy #geometry-augmentation-bug round 2, 2026-08).
            self._logger.info(
                "sampling_detected",
                sampling_interval_seconds=sampling_interval,
                source="full_rinex_read",
                rinex_read_seconds=round(t1 - t0, 2),
            )

        effective_grid_seconds = (
            grid_seconds if grid_seconds is not None else sampling_interval
        )
        target_epochs = aux_epoch_grid(day_start, effective_grid_seconds)

        self._logger.info(
            "epoch_grid_generated",
            n_epochs=len(target_epochs),
            grid_seconds=effective_grid_seconds,
            day_start=str(target_epochs[0]),
            day_end=str(target_epochs[-1]),
        )

        # 2. Interpolate orbits (Hermite) and clocks (piecewise linear,
        # unless fetch_clock is disabled -- see AuxDataConfig.fetch_clock)
        assert self.aux_pipeline is not None, "aux_pipeline must be initialized"
        ephem_ds = self.aux_pipeline.get("ephemerides")
        clock_ds = (
            self.aux_pipeline.get("clock")
            if self.aux_pipeline.is_loaded("clock")
            else None
        )
        t2 = time.perf_counter()
        aux_processed = interpolate_aux_day(ephem_ds, clock_ds, target_epochs)
        t3 = time.perf_counter()
        self._logger.info(
            "aux_interpolation_complete",
            duration_seconds=round(t3 - t2, 2),
            clock=clock_ds is not None,
            final_dims=dict(aux_processed.sizes),
            final_vars=list(aux_processed.data_vars.keys()),
        )

        # 8. Write to Zarr
        self._logger.info(
            "aux_zarr_write_started",
            output_path=str(output_path),
            group=group,
            data_size=dict(aux_processed.sizes),
        )
        with scoped_zarr_concurrency(
            self._config.processing.aux_data.zarr_async_concurrency
        ):
            aux_processed.to_zarr(
                output_path, group=group, mode="w", consolidated=False
            )
        t4 = time.perf_counter()

        self._logger.info(
            "aux_preprocessing_complete",
            total_seconds=round(t4 - t0, 2),
            rinex_read_seconds=round(t1 - t0, 2),
            interpolation_seconds=round(t3 - t2, 2),
            zarr_write_seconds=round(t4 - t3, 2),
            data_size=dict(aux_processed.sizes),
            output_path=str(output_path),
        )

        return sampling_interval

    def _as_receiver_day(self, location: ReceiverDay | Path) -> ReceiverDay:
        """``location`` as a receiver day.

        Deprecated entry points still pass a receiver's day folder; its
        receiver and recipe are looked up in the site configuration.
        """
        if isinstance(location, ReceiverDay):
            return location
        folder = Path(location)
        site_config = self._get_site_config()
        base = site_config.get_base_path()
        for name, cfg in site_config.receivers.items():
            if base / cfg.directory in (folder, folder.parent):
                return ReceiverDay(
                    name,
                    folder,
                    self.matched_data_dirs.yyyydoy.to_str(),
                    recipe_file(self.site.site_name, cfg.recipe),
                )
        return ReceiverDay("", folder, self.matched_data_dirs.yyyydoy.to_str())

    def _get_rinex_files(
        self, day: ReceiverDay | Path, reader_format: str | None = None
    ) -> list[Path]:
        """Get the sorted GNSS data files a run processes for ``day``.

        Delegates to :func:`canvodpy.orchestrator.discovery.discover_files`
        (the same selection the dry-run preview reports): the receiver's
        naming recipe when configured, otherwise canonical canVOD names
        only, found anywhere below the receiver's directory by the date in
        their names. Each file's canonical name is cached for the log book
        (see :meth:`_canonical_name`).

        Parameters
        ----------
        day : ReceiverDay | Path
            Receiver and day to collect files for (a folder path only from
            deprecated entry points).
        reader_format : str | None
            If ``"sbf"``, restrict to SBF files; if ``"rinex3"``/``"rinex"``,
            to RINEX files. Otherwise discovers both.

        """
        day = self._as_receiver_day(day)
        discovered = discover_files(day, reader_format)
        if not discovered:
            self._logger.warning("no_files_for_day", day=str(day))
        for found in discovered:
            self._canonical_names[found.path] = found.canonical_name
        return [found.path for found in discovered]

    def _file_start(self, fname: Path) -> datetime | None:
        """Start time from the canonical name of ``fname`` (``None`` if none)."""
        from canvod.preflight.convention import CanVODFilename

        canonical = self._canonical_name(fname)
        if not canonical:
            return None
        return CanVODFilename.from_filename(canonical).start

    def _canonical_name(self, fname: Path) -> str:
        """Canonical canVOD filename for a discovered file (``""`` if none)."""
        cached = self._canonical_names.get(fname)
        if cached is not None:
            return cached
        return canonical_name_for(fname)

    def _logbook_row(
        self,
        fname: Path,
        ds: xr.Dataset,
        rinex_hash: str,
        exists: bool,
        rel_path: str,
        action: str,
    ) -> dict[str, Any]:
        """Build one ingest log-book row for a GNSS file.

        One row per file encountered, including files skipped as already
        ingested (``exists=True``), which keeps an audit trail of every run
        that saw the file. ``commit_msg`` is filled in just before the rows
        are written, inside the same session as the data they describe;
        ``snapshot_id`` stays empty because a commit's ID only exists once
        the commit that contains the row has been made. The row's commit is
        recovered from the repository ancestry: its message equals
        ``commit_msg`` and its metadata lists the row's ``rinex_hash``.
        """
        canonical_name = ds.attrs.get("canonical_name") or self._canonical_name(fname)
        _warn_if_name_disagrees_with_data(self._logger, fname, canonical_name, ds)
        return {
            "fname": fname,
            "rinex_hash": rinex_hash,
            "start": np.datetime64(ds.epoch.min().values),
            "end": np.datetime64(ds.epoch.max().values),
            "dataset_attrs": ds.attrs.copy(),
            "exists": exists,
            "rel_path": rel_path,
            "canonical_name": canonical_name,
            "physical_path": ds.attrs.get("physical_path") or str(fname),
            "action": action,
            "write_strategy": self._gnss_store_strategy,
            "run_id": get_run_id() or "",
            "commit_msg": "",
            "snapshot_id": "",
        }

    def _get_site_config(self):
        """Get the SiteConfig for the current site."""
        sites_cfg = self._config.sites
        # Find our site by matching site name
        for site_name, site_cfg in sites_cfg.sites.items():
            if site_name == self.site.site_name:
                return site_cfg
        msg = f"Site '{self.site.site_name}' not found in config"
        raise ValueError(msg)

    def _ensure_gnss_store_metadata(
        self, receivers: Sequence[str], reader_format: str | None
    ) -> None:
        """Give a new GNSS store its metadata; refuse unlisted receivers.

        Runs before a batch writes data, so the store never holds data
        without its repository metadata (ADR 0014). Every commit then
        writes the store's root copy and snapshot summary itself.

        Raises
        ------
        ValueError
            If the store predates repository metadata (names the migrate
            command), or a receiver is not listed in it (names the amend
            command).
        """
        from canvod.store_metadata import ensure_store_metadata

        resources = self._config.processing.params.resolve_resources()
        ensure_store_metadata(
            self.site.gnss_store_path,
            config=self._config,
            site_name=self.site.site_name,
            store_type="gnss_store",
            source_format=reader_format or self._reader_name,
            names=receivers,
            dask_workers=resources.get("n_workers"),
            dask_threads_per_worker=resources.get("threads_per_worker"),
        )

    def _compute_receiver_position(
        self,
        position_files: list[Path],
        receiver_name: str,
        reader_format: str | None = None,
    ) -> ECEFPosition | None:
        """Compute ECEF position from the first valid GNSS file.

        Uses the ``ReaderFactory`` to create a minimal dataset (header-only)
        and extracts the ECEF position from its attributes.  This works for
        any registered reader format (RINEX, SBF, …) without format-specific
        logic.

        Parameters
        ----------
        position_files : list[Path]
            GNSS files to try (first valid one wins).
        receiver_name : str
            Receiver name for logging.
        reader_format : str | None
            Reader format name (e.g. ``"rinex3"``, ``"sbf"``).
            Falls back to ``self._reader_name`` when *None*.

        Returns
        -------
        ECEFPosition | None
            Computed position, or None if no valid file found.

        """
        fmt = reader_format or self._reader_name

        for ff in position_files:
            try:
                reader = self._make_reader(ff, reader_format=fmt)
                ds = reader.to_ds(keep_data_vars=[], write_global_attrs=True)
                receiver_position = ECEFPosition.from_ds_metadata(ds)
                self._logger.info(
                    "Computed receiver position for %s: %s",
                    receiver_name,
                    receiver_position,
                )
                return receiver_position
            except (ValidationError, pydantic_core.ValidationError) as e:
                self._logger.warning(
                    "Validation error for %s: %s",
                    ff.name,
                    e,
                )
            except (KeyError, OSError, RuntimeError, ValueError) as e:
                self._logger.warning(
                    "Could not extract position from %s: %s",
                    ff.name,
                    e,
                )

        self._logger.error(
            "No valid GNSS files found for position extraction for %s",
            receiver_name,
        )
        return None

    def _resolve_receiver_positions(
        self,
        normalized_configs: list[tuple],
        files_by_dir: dict,
    ) -> dict:
        """Resolve every receiver's ECEF position upfront (Phase 1).

        Returns dict keyed by receiver_name (store group name).
        Positions are computed once per unique source directory and shared.
        """
        position_mode = self._config.processing.params.receiver_position_mode
        pos_by_source: dict = {}  # (source_dir, fmt) -> ECEFPosition | None
        result: dict = {}

        for name, rtype, data_dir, position_data_dir, fmt in normalized_configs:
            if position_mode == "per_receiver":
                source_dir = data_dir
                self._logger.warning(
                    "receiver_position_mode='per_receiver': using %s's own "
                    "position (breaks direct SNR comparability)",
                    name,
                )
            else:
                source_dir = (
                    position_data_dir if position_data_dir is not None else data_dir
                )

            key = (source_dir, fmt)
            if key not in pos_by_source:
                files = files_by_dir.get(key) or self._get_rinex_files(source_dir, fmt)
                pos_by_source[key] = self._compute_receiver_position(
                    files, name, reader_format=fmt
                )
            result[name] = pos_by_source[key]

        return result

    def _recompute_scs_for_position(
        self,
        cached_datasets: list,
        aux_zarr_path,
        receiver_position,
    ) -> list:
        """Recompute spherical coordinates for a new receiver position.

        Opens the aux Zarr once (hoisted outside the per-file loop) and
        recomputes theta/phi/r for every cached dataset using the new position.
        """
        if aux_zarr_path is None:
            raise RuntimeError(
                "SCS recompute from cache requires an aux zarr; "
                "not available with SBF geometry"
            )
        # Hoist open_zarr outside the per-file loop (was reopened per file)
        aux_store = xr.open_zarr(
            aux_zarr_path, decode_timedelta=True, consolidated=False
        )
        augmented_datasets = []
        try:
            for fpath, ds in cached_datasets:
                scs_vars = [v for v in ("theta", "phi", "r") if v in ds.data_vars]
                ds_no_scs = ds.drop_vars(scs_vars)
                common_sids = sorted(
                    set(ds_no_scs.sid.values) & set(aux_store.sid.values)
                )
                aux_slice = aux_store.sel(epoch=ds_no_scs.epoch, method="nearest").sel(
                    sid=common_sids
                )
                ds_recomputed = _compute_spherical_coords_fast(
                    ds_no_scs, aux_slice, receiver_position
                )
                # Mirror Wave A: drop r if it was absent in the cached dataset
                if "r" not in scs_vars and "r" in ds_recomputed.data_vars:
                    ds_recomputed = ds_recomputed.drop_vars("r")
                augmented_datasets.append((fpath, ds_recomputed))
        finally:
            aux_store.close()
        return augmented_datasets

    @staticmethod
    def _build_compute_waves(
        normalized_configs: list,
        skipped: set,
    ) -> tuple[list, list, dict]:
        """Group receivers into Wave A (parse) and Wave B (SCS recompute).

        Returns (wave_a, wave_b, parse_owner) where:
        - wave_a: [(name, data_dir, fmt)] — one parse job per unique (data_dir, fmt)
        - wave_b: [(name, data_dir, fmt)] — SCS recompute from Wave A cache
        - parse_owner: {(data_dir, fmt): name} — which receiver owns each parse job
        """
        parse_owner: dict = {}
        wave_a: list = []
        wave_b: list = []
        for name, rtype, data_dir, _pos, fmt in normalized_configs:
            if name in skipped:
                continue
            key = (data_dir, fmt)
            if key not in parse_owner:
                parse_owner[key] = name
                wave_a.append((name, data_dir, fmt))
            else:
                wave_b.append((name, data_dir, fmt))
        return wave_a, wave_b, parse_owner

    def _ensure_aux_data_preprocessed(
        self,
        canopy_files: list[Path],
        date_str: str,
        reader_format: str | None = None,
    ) -> tuple[Path, str | None]:
        """Ensure auxiliary data is preprocessed and available.

        When ``StorageConfig.shared_aux_cache_dir`` is set, checks a network-wide, fingerprint-keyed cache before
        rebuilding -- ephemeris products are satellite-based, not
        site-based, so multiple sites sharing the same agency/product/date
        can reuse one cache entry instead of each rebuilding it. Falls back
        to the legacy per-site behavior (always rebuild) when unset.

        Parameters
        ----------
        canopy_files : list[Path]
            GNSS files for sampling detection
        date_str : str
            Date string (e.g., '2025213')
        reader_format : str | None
            Reader format for the files (used in sampling fallback).

        Returns
        -------
        tuple[Path, str | None]
            ``(store_path, group)`` -- the Zarr store to open and the group
            within it holding this day's aux data. ``group`` is ``None`` in
            legacy (non-shared-cache) mode, meaning the store root.

        Raises
        ------
        RuntimeError
            If preprocessing fails or the data isn't present after it
        """
        shared_cache_dir = self._config.processing.storage.get_shared_aux_cache_dir()
        if shared_cache_dir is not None:
            return self._ensure_shared_aux_cache(
                canopy_files, date_str, shared_cache_dir, reader_format=reader_format
            )

        import shutil

        t0 = time.perf_counter()
        aux_base_dir = self._config.processing.storage.get_aux_data_dir()
        # Nest alongside canvod-auxiliary's 01_SP3/02_CLK download subdirs
        # instead of littering aux_base_dir's root with one aux_*.zarr per date.
        aux_zarr_path = aux_base_dir / "00_aux_zarr" / f"aux_{date_str}.zarr"
        aux_zarr_path.parent.mkdir(parents=True, exist_ok=True)

        # Always reprocess from raw SP3/CLK files — the Hermite interpolation
        # is cheap and this avoids stale caches when SIDs change.
        had_cache = aux_zarr_path.exists()
        if had_cache:
            try:
                shutil.rmtree(aux_zarr_path)
            except OSError as _rmtree_err:
                if _rmtree_err.errno == 66:  # ENOTEMPTY — macOS Finder race; retry
                    shutil.rmtree(aux_zarr_path, ignore_errors=True)
                else:
                    raise

        t1 = time.perf_counter()
        self._logger.info(
            "aux_preprocessing_required",
            output_path=str(aux_zarr_path),
            interpolation="hermite_cubic",
            cache_cleared=had_cache,
            rmtree_seconds=round(t1 - t0, 4) if had_cache else 0,
        )
        try:
            self._preprocess_aux_data_with_hermite(
                canopy_files, aux_zarr_path, reader_format=reader_format
            )

            if not aux_zarr_path.exists():
                raise RuntimeError(
                    f"Aux preprocessing completed but file not found: {aux_zarr_path}"
                )

            # macOS creates .DS_Store inside directories Finder/Spotlight has
            # touched; zarr's group listing then warns on the unrecognized
            # member. Same fix as MyIcechunkStore._clean_ds_store() in
            # canvod-store, applied here since this plain aux Zarr isn't
            # opened through that class.
            sanitize_directory(aux_zarr_path)

            self._logger.info(
                "aux_preprocessing_verified",
                file_exists=True,
                path=str(aux_zarr_path),
            )
        except Exception as e:
            self._logger.error(
                "aux_preprocessing_failed",
                error=str(e),
                exception=type(e).__name__,
                path=str(aux_zarr_path),
            )
            raise

        return aux_zarr_path, None

    def _ensure_shared_aux_cache(
        self,
        canopy_files: list[Path],
        date_str: str,
        shared_cache_dir: Path,
        reader_format: str | None = None,
    ) -> tuple[Path, str]:
        """Shared-cache lookup/populate, called when the cache is enabled.

        On a miss, writes to a per-attempt temp group and renames it into
        place only on success, rather than writing directly to the final
        path -- a network-wide cache has a wider blast radius than a
        per-site one if a torn/partial write is ever read by a different
        site's concurrent run. NOTE: ``Path.rename()`` is one syscall from
        Python's side, but a zarr group is a directory tree (many chunk
        files + zarr.json) -- whether the underlying filesystem honors a
        directory rename as a single atomic operation is server/protocol
        dependent, not a hard guarantee the way a single-file rename
        typically is. This is strictly better than a direct write, not a
        fully closed risk -- verifiable only on the actual (CIFS) mount
        this is meant to protect, which has already dropped mid-operation
        three times this week for unrelated reasons.
        """
        import shutil
        import uuid

        cache_root = shared_cache_dir / "aux_cache.zarr"
        assert self.aux_pipeline is not None, "aux_pipeline must be initialized"
        fingerprint = compute_aux_cache_fingerprint(
            agency=self._config.processing.aux_data.agency,
            product_type=self._config.processing.aux_data.product_type,
            ephemeris_source=self._config.processing.params.ephemeris_source,
            canonical_grid_seconds=CANONICAL_AUX_GRID_SECONDS,
            source_file_paths=self.aux_pipeline.source_file_paths(),
            aggregate_glonass_fdma=(
                self._config.processing.params.aggregate_glonass_fdma
            ),
        )
        group = f"{fingerprint}/{date_str}"

        if (cache_root / group).exists():
            self._logger.info("aux_cache_hit", fingerprint=fingerprint, date=date_str)
            # Sweep on every hit, not just on populate (below) -- Finder can
            # drop a fresh .DS_Store into a shared/mounted cache dir between
            # runs, and a hit path that skips this leaves every subsequent
            # xr.open_zarr() on cache_root tripping zarr's group-listing
            # warning until the next miss happens to populate+sweep it.
            sanitize_directory(cache_root)
            return cache_root, group

        self._logger.info("aux_cache_miss", fingerprint=fingerprint, date=date_str)
        tmp_group = f"{fingerprint}/.tmp-{date_str}-{uuid.uuid4().hex[:8]}"
        try:
            self._preprocess_aux_data_with_hermite(
                canopy_files,
                cache_root,
                reader_format=reader_format,
                group=tmp_group,
                grid_seconds=CANONICAL_AUX_GRID_SECONDS,
            )
            if not (cache_root / tmp_group).exists():
                raise RuntimeError(
                    f"Aux preprocessing completed but group not found: "
                    f"{cache_root}/{tmp_group}"
                )
            # Promotion, not a second write to the final path. If two sites
            # race the same miss, the loser's rename just overwrites the
            # winner's with an equally-valid result (both did legitimate,
            # correct work) -- what this avoids is a *torn* write at the
            # final path from concurrent writers, not the (benign)
            # redundant computation itself.
            (cache_root / tmp_group).rename(cache_root / group)

            # macOS creates .DS_Store inside directories Finder/Spotlight has
            # touched; zarr's group listing then warns on the unrecognized
            # member. Same fix as MyIcechunkStore._clean_ds_store() in
            # canvod-store, applied here since this is a plain Zarr store
            # (cache_root), not opened through that class. Sweeps the whole
            # cache_root tree, not just this date's group, since a stray
            # .DS_Store anywhere above it (e.g. at the fingerprint level)
            # would still trigger the warning on every future open.
            sanitize_directory(cache_root)
        except Exception as e:
            self._logger.error(
                "aux_cache_populate_failed",
                error=str(e),
                exception=type(e).__name__,
                fingerprint=fingerprint,
                date=date_str,
            )
            # Best-effort cleanup -- a failed attempt (e.g. a CIFS hiccup
            # mid-write) shouldn't leave a permanent orphaned .tmp- dir in
            # a shared, multi-site cache store with no GC mechanism.
            shutil.rmtree(cache_root / tmp_group, ignore_errors=True)
            raise

        self._logger.info("aux_cache_populated", fingerprint=fingerprint, date=date_str)
        return cache_root, group

    def _parallel_process_rinex(
        self,
        rinex_files: list[Path],
        keep_vars: list[str],
        aux_zarr_path: Path,
        receiver_position: ECEFPosition,
        receiver_type: str,
        reader_format: str | None = None,
        show_progress: bool = True,
        pool_workers: int | None = None,
        aux_group: str | None = None,
    ) -> tuple[
        list[tuple[Path, xr.Dataset]],
        dict[Path, dict[str, xr.Dataset]],
        dict[str, list[str]],
    ]:
        """Parallel process RINEX files using ProcessPoolExecutor.

        Uses TRUE parallelism (no GIL) with separate processes.
        Each worker reads only its time slice from the Zarr store.

        Parameters
        ----------
        rinex_files : list[Path]
            List of RINEX files to process
        keep_vars : list[str]
            Variables to keep
        aux_zarr_path : Path
            Path to preprocessed aux Zarr store (with Hermite interpolation)
        receiver_position : ECEFPosition
            Receiver position (computed once)
        receiver_type : str
            Receiver type
        reader_format : str | None
            Per-receiver reader format. Falls back to ``self._reader_name``.
        show_progress : bool
            Whether to show the Rich progress bar (default True).
        pool_workers : int | None
            Override for worker count. When None, uses ``self.n_max_workers``.
        aux_group : str | None
            Zarr group within ``aux_zarr_path`` to read aux data from
            (shared-cache mode). None reads the store root.

        Returns
        -------
        tuple
            (augmented_datasets, aux_datasets_by_file, sid_issues) where
            augmented_datasets is sorted chronologically by filename.

        """
        effective_reader = reader_format or self._reader_name
        store_r = self._config.processing.params.store_radial_distance
        store_raw = self._config.processing.params.store_sbf_raw_observables
        return self._parallel_process_rinex_pool(
            rinex_files,
            keep_vars,
            aux_zarr_path,
            receiver_position,
            receiver_type,
            effective_reader,
            store_r,
            store_raw,
            show_progress=show_progress,
            pool_workers=pool_workers,
            aux_group=aux_group,
        )

    def _parallel_process_rinex_pool(
        self,
        rinex_files: list[Path],
        keep_vars: list[str],
        aux_zarr_path: Path,
        receiver_position: ECEFPosition,
        receiver_type: str,
        reader_format: str | None = None,
        store_radial_distance: bool = False,
        store_sbf_raw_observables: bool = True,
        show_progress: bool = True,
        pool_workers: int | None = None,
        aux_group: str | None = None,
    ) -> tuple[
        list[tuple[Path, xr.Dataset]],
        dict[Path, dict[str, xr.Dataset]],
        dict[str, list[str]],
    ]:
        """Fallback: process RINEX files via ProcessPoolExecutor."""
        start_time = time.time()
        workers = pool_workers if pool_workers is not None else self.n_max_workers
        effective_workers = workers or os.cpu_count() or 1
        self._logger.info(
            "parallel_processing_started",
            workers=effective_workers,
            files=len(rinex_files),
            receiver_type=receiver_type,
            executor_type="ProcessPoolExecutor",
        )

        self._logger.debug(
            "parallel_config",
            max_workers=workers,
            cpu_count=os.cpu_count(),
            files_per_worker=round(len(rinex_files) / effective_workers, 1),
        )

        results: list[tuple[Path, xr.Dataset]] = []
        aux_datasets_by_file: dict[Path, dict[str, xr.Dataset]] = {}
        sid_issues_agg: dict[str, set] = {}
        task_submission_start = time.time()

        effective_reader = reader_format or self._reader_name
        _res = self._config.processing.params.resolve_resources()
        with ProcessPoolExecutor(
            max_workers=workers,
            initializer=_worker_init_with_run_id,
            initargs=(
                _res["nice_priority"],
                _res["cpu_affinity"],
                get_run_id(),
                active_log_dir(),
            ),
        ) as executor:
            futures = {
                executor.submit(
                    preprocess_with_hermite_aux,
                    rinex_file,
                    keep_vars,
                    aux_zarr_path,
                    receiver_position,
                    receiver_type,
                    self.keep_sids,
                    effective_reader,
                    self.use_sbf_geometry,
                    store_radial_distance,
                    store_sbf_raw_observables,
                    aux_group=aux_group,
                    rinex_v3_parser=self._config.processing.params.rinex_v3_parser,
                    aggregate_glonass_fdma=(
                        self._config.processing.params.aggregate_glonass_fdma
                    ),
                    date_key=self.matched_data_dirs.yyyydoy.to_str(),
                ): rinex_file
                for rinex_file in rinex_files
            }

            task_submission_time = time.time() - task_submission_start
            self._logger.debug(
                "tasks_submitted",
                task_count=len(futures),
                submission_time_seconds=round(task_submission_time, 3),
            )

            completed_count = 0
            failed_count = 0

            yyyydoy = self.matched_data_dirs.yyyydoy.to_str()
            desc = f"{yyyydoy} {receiver_type}"
            with _processing_progress(disable=not show_progress) as progress:
                task = progress.add_task(desc, total=len(futures))
                for fut in as_completed(futures):
                    try:
                        fname, ds_augmented, aux, sids = fut.result()
                        results.append((fname, ds_augmented))
                        aux_datasets_by_file[fname] = aux
                        for key, vals in sids.items():
                            sid_issues_agg.setdefault(key, set()).update(vals)
                        completed_count += 1

                        if completed_count % 10 == 0:
                            self._logger.debug(
                                "processing_progress",
                                completed=completed_count,
                                total=len(futures),
                                failed=failed_count,
                                progress_pct=round(
                                    100 * completed_count / len(futures), 1
                                ),
                            )
                    except BrokenProcessPool as e:
                        failed_file = futures[fut].name
                        failed_count += 1
                        self._logger.error(
                            "worker_pool_broken",
                            file=failed_file,
                            error=str(e),
                            failed_count=failed_count,
                            hint="worker process likely killed by OOM or segfault",
                        )
                    except (
                        OSError,
                        RuntimeError,
                        ValueError,
                        RinexError,
                        NmeaError,
                    ) as e:
                        failed_file = futures[fut].name
                        failed_count += 1
                        self._logger.error(
                            "file_processing_failed",
                            file=failed_file,
                            error=str(e),
                            exception=type(e).__name__,
                            failed_count=failed_count,
                        )
                    progress.advance(task)

        # Sort chronologically by filename
        self._logger.debug("sorting_results_chronologically")
        results.sort(key=lambda x: x[0].name)

        duration = time.time() - start_time
        self._logger.info(
            "parallel_processing_complete",
            files_processed=len(results),
            files_total=len(rinex_files),
            files_failed=len(rinex_files) - len(results),
            duration_seconds=round(duration, 2),
            avg_time_per_file=round(duration / len(rinex_files), 2)
            if rinex_files
            else 0,
            throughput_files_per_sec=round(len(results) / duration, 2)
            if duration > 0
            else 0,
        )
        sid_issues_final = {k: sorted(v) for k, v in sid_issues_agg.items()}
        return results, aux_datasets_by_file, sid_issues_final

    def _check_store_vars_consistency(
        self,
        session: Session,
        receiver_name: str,
        augmented_datasets: list[tuple[Path, xr.Dataset]],
        append_dim: str = "epoch",
    ) -> None:
        """Warn if the store has different variables than the current batch.

        Detects stale variables from previous runs with different keep_gnss_observables.

        Reads variable names directly off the Zarr group's array metadata
        (name + ``dimension_names``) instead of opening a full ``xr.Dataset``
        via ``xr.open_zarr()``. The latter resolves every array's chunk
        manifest to build a lazy Dask graph, so its cost scales with the
        group's total manifest count -- confirmed against a 332-day
        production run (Pearson r=0.99 between manifest count and this
        stage's duration), growing from ~0s to >5s/batch and becoming the
        single largest contributor to this pipeline stage's slowdown over a
        long-running store. A "data variable" here is any array (other than
        ``append_dim`` itself) whose dims include ``append_dim`` -- this
        matches the codebase's fixed ``(epoch, sid)`` data contract without
        needing the full dataset.
        """
        try:
            root = zarr.open_group(session.store, mode="r")
        except zarr.errors.GroupNotFoundError:
            return  # Brand-new store, nothing committed yet
        if receiver_name not in root:
            return  # New group, nothing to check

        # zarr's stubs type Group.__getitem__ as AnyArray | Group generically,
        # so ty can't narrow that a group-membership-checked key is a Group
        # (same weak-stub class as canvod-store/store.py's overrides).
        group = root[receiver_name]
        store_vars = set()
        for name in group.array_keys():  # ty: ignore[unresolved-attribute]
            if name == append_dim:
                continue
            arr = group[name]  # ty: ignore[invalid-argument-type]
            dims = getattr(arr.metadata, "dimension_names", None) or ()  # ty: ignore[unresolved-attribute]
            if append_dim in dims:
                store_vars.add(name)

        if not augmented_datasets:
            return
        _, first_ds = augmented_datasets[0]
        batch_vars: set[str] = {str(name) for name in first_ds.data_vars}

        stale_vars = store_vars - batch_vars
        missing_vars = batch_vars - store_vars

        if stale_vars:
            self._logger.warning(
                "store_has_stale_variables",
                receiver=receiver_name,
                stale_vars=sorted(stale_vars),
                hint=(
                    "The store contains variables not in the current keep_gnss_observables. "
                    "This causes dimension conflicts on read-back. "
                    "With gnss_store_strategy='overwrite', stale vars will be "
                    "dropped automatically. Otherwise delete the store and reprocess."
                ),
            )
        if missing_vars:
            self._logger.info(
                "store_missing_new_variables",
                receiver=receiver_name,
                new_vars=sorted(map(str, missing_vars)),
            )

    def _prepare_store_for_overwrite(
        self,
        session: Session,
        receiver_name: str,
        augmented_datasets: list[tuple[Path, xr.Dataset]],
        existing_hashes: set[str],
        file_hash_map: dict[Path, str | None],
        aux_datasets: dict[Path, dict[str, xr.Dataset]] | None = None,
    ) -> set[Path]:
        """Rewrite the group with the batch's files replacing their epoch ranges.

        Reads the existing group, masks out the temporal ranges of files
        being overwritten, drops data_vars not present in the incoming batch,
        merges in every hashed file of the batch, sorts by epoch and rewrites
        the group (``MyIcechunkStore.rewrite_group``). Merging before the
        rewrite, instead of appending the replacement data afterwards, keeps
        ``epoch`` monotonic when the replaced range lies before the latest
        stored data. The log book is kept; ``sbf_obs`` loses the replaced
        ranges and gains the ``sbf_obs`` of the merged files.

        Returns
        -------
        set[Path]
            Files whose data this rewrite already stored (empty when nothing
            was overwritten); the caller must not append them again.
        """
        log = self._logger

        # 1. Read existing store data
        try:
            ds_store = xr.open_zarr(
                session.store, group=receiver_name, consolidated=False
            ).compute(
                scheduler="synchronous"
            )  # synchronous avoids Dask serialization error
        except KeyError, zarr.errors.GroupNotFoundError:
            return set()  # New group, nothing to prepare

        # 2. Collect epoch ranges to remove (files that exist and will be overwritten)
        epochs_to_remove = []
        for fname, ds in augmented_datasets:
            h = file_hash_map.get(fname)
            if h and h in existing_hashes:
                start = np.datetime64(ds.epoch.min().values)
                end = np.datetime64(ds.epoch.max().values)
                epochs_to_remove.append((start, end))

        if not epochs_to_remove:
            return set()  # Nothing to overwrite

        log.info(
            "prepare_overwrite",
            receiver=receiver_name,
            ranges_to_remove=len(epochs_to_remove),
        )

        # 3. Build combined mask: keep epochs NOT covered by any overwrite range
        epoch_vals = ds_store.epoch.values
        keep_mask = np.ones(len(epoch_vals), dtype=bool)
        for start, end in epochs_to_remove:
            keep_mask &= (epoch_vals < start) | (epoch_vals > end)

        ds_filtered = ds_store.isel(epoch=keep_mask)

        # 4. Drop stale variables not in current batch
        if augmented_datasets:
            _, first_ds = augmented_datasets[0]
            batch_vars = set(first_ds.data_vars)
            stale_vars = set(ds_filtered.data_vars) - batch_vars
            if stale_vars:
                log.warning(
                    "dropping_stale_variables",
                    receiver=receiver_name,
                    stale_vars=sorted(stale_vars),
                )
                ds_filtered = ds_filtered.drop_vars(stale_vars)

        # 5. Merge the batch into the kept epochs, in epoch order
        store = self.site.gnss_store
        merged_fnames = {
            fname for fname, _ds in augmented_datasets if file_hash_map.get(fname)
        }
        incoming = [
            store._normalize_encodings(store._cleanse_dataset_attrs(ds))
            for fname, ds in augmented_datasets
            if fname in merged_fnames
        ]
        ds_rewrite = xr.concat(
            [ds_filtered, *incoming], dim="epoch", combine_attrs="override"
        ).sortby("epoch")

        # 6. Rewrite the group, keeping its metadata/
        sbf_parts = self._sbf_obs_parts(aux_datasets, sorted(merged_fnames))
        store.rewrite_group(
            session,
            receiver_name,
            ds_rewrite,
            epochs_to_remove,
            {"sbf_obs": sbf_parts} if sbf_parts else None,
        )

        return merged_fnames

    def _check_existing_with_temporal_overlap(
        self,
        receiver_name: str,
        augmented_datasets: list[tuple[Path, xr.Dataset]],
        file_hash_map: dict[Path, str | None],
    ) -> set[str]:
        """Check for existing files by hash AND temporal overlap.

        Performs three checks:
        1. Hash match against store metadata (exact duplicate)
        2. Temporal overlap against store metadata (e.g. re-run)
        3. Intra-batch overlap (e.g. daily concat + 15-min sub-files
           in the same batch)

        Returns the union of all flagged hashes so the caller can treat
        them as ``exists=True``.
        """
        valid_hashes = [h for h in file_hash_map.values() if h]

        # Load the metadata table once and share it with both checks below
        # instead of each doing its own full-table read: the time of the
        # batch check grows with the number of metadata rows, so one read
        # instead of two halves that cost. `None` means fresh store / no
        # metadata yet.
        metadata_df = self.site.gnss_store.load_metadata_for_dedup(receiver_name)
        if metadata_df is None:
            existing_hashes: set[str] = set()
        else:
            existing_hashes = self.site.gnss_store.batch_check_existing(
                receiver_name, valid_hashes, metadata_df=metadata_df
            )

            # Check 2: temporal overlap against store metadata
            new_hashes = [h for h in valid_hashes if h not in existing_hashes]
            if new_hashes:
                file_intervals = []
                for fname, ds in augmented_datasets:
                    h = file_hash_map[fname]
                    if h and h not in existing_hashes:
                        file_intervals.append(
                            (
                                h,
                                np.datetime64(ds.epoch.min().values),
                                np.datetime64(ds.epoch.max().values),
                            )
                        )
                if file_intervals:
                    temporal_overlaps = self.site.gnss_store.check_temporal_overlaps(
                        receiver_name, file_intervals, metadata_df=metadata_df
                    )
                    existing_hashes |= temporal_overlaps

        # Check 3: intra-batch overlap. Files are taken in order of their
        # first epoch (on ties, the shorter file first) and a file whose
        # epochs touch those of a file already taken is skipped, the same
        # rule check 2 applies against the store. Discovery already rejects
        # files whose *names* overlap; this catches data that disagrees with
        # its name.
        intervals = []
        for fname, ds in augmented_datasets:
            h = file_hash_map[fname]
            if h and h not in existing_hashes:
                start = np.datetime64(ds.epoch.min().values)
                end = np.datetime64(ds.epoch.max().values)
                intervals.append((start, end, len(intervals), h, fname))
        intervals.sort()

        kept: tuple[np.datetime64, Path] | None = None
        for start, end, _, h, fname in intervals:
            if kept is not None and start <= kept[0]:
                existing_hashes.add(h)
                self._logger.warning(
                    "intra_batch_overlap",
                    file=Path(fname).name,
                    overlaps=kept[1].name,
                    file_range=f"{start} → {end}",
                    message="Skipping file whose epochs overlap another "
                    "file of the same batch",
                )
                continue
            kept = (end, Path(fname))

        return existing_hashes

    # ── Cross-group fork/merge batch writes (skip/unsafe_append only) ──────
    #
    # Parallelizes PHASE 3's per-group
    # writes across receiver groups (e.g. reference + N canopies) using
    # Icechunk's fork/merge primitive instead of one sequential commit per
    # group. Scope: only the "skip" and "unsafe_append" gnss_store_strategy
    # values -- "overwrite" keeps using `_append_to_icechunk`, which stages
    # each receiver on a temp branch and promotes it with
    # `MyIcechunkStore.promote_branch` (refused if main moved meanwhile).

    def _sbf_obs_parts(
        self,
        aux_datasets: dict[Path, dict[str, xr.Dataset]] | None,
        fnames: Sequence[Path],
    ) -> list[xr.Dataset]:
        """The ``sbf_obs`` of *fnames* to store (none with ``store_sbf_metadata: false``)."""
        if not aux_datasets or not self._config.processing.params.store_sbf_metadata:
            return []
        return [
            aux_datasets[fname]["sbf_obs"]
            for fname in fnames
            if "sbf_obs" in aux_datasets.get(fname, {})
        ]

    def _write_sbf_obs(
        self,
        session: Any,
        receiver_name: str,
        aux_datasets: dict[Path, dict[str, xr.Dataset]] | None,
        written_fnames: Sequence[Path],
    ) -> None:
        """Add the ``sbf_obs`` of the written files into the observations' session.

        Only files whose observations were written in *session* contribute,
        so ``sbf_obs`` covers the same files as the observations and lands
        in the same commit. Skipped with ``store_sbf_metadata: false``.
        Errors propagate, so the caller does not commit either.
        """
        parts = self._sbf_obs_parts(aux_datasets, written_fnames)
        if not parts:
            return
        n_epochs = self.site.gnss_store.write_metadata_parts(
            parts, receiver_name, "sbf_obs", session
        )
        self._logger.info(
            "sbf_obs_written",
            receiver=receiver_name,
            files=len(parts),
            epochs=n_epochs,
        )

    def _check_preprocessing(
        self, receiver_name: str, augmented_datasets: list[tuple[Path, xr.Dataset]]
    ) -> None:
        """Refuse files preprocessed differently from ``receiver_name``'s data.

        Checks once per distinct record (each check reads the log book);
        raises ``PreprocessingMismatchError``, which stops the run.
        """
        checked: set[str] = set()
        for _fname, ds in augmented_datasets:
            record = str(ds.attrs.get(PREPROCESSING_ATTR, ""))
            if record not in checked:
                checked.add(record)
                self.site.gnss_store.check_preprocessing_matches(receiver_name, ds)

    def _prepare_group_write(
        self,
        augmented_datasets: list[tuple[Path, xr.Dataset]],
        receiver_name: str,
        rinex_files: list[Path],
        aux_datasets: dict[Path, dict[str, xr.Dataset]] | None = None,
        sid_issues: dict[str, list[str]] | None = None,
        reader_format: str | None = None,
    ) -> GroupWritePlan:
        """Dedup-check one receiver group's files ahead of a forked write.

        Mirrors `_append_to_icechunk`'s STEP 1: `receiver_name`-scoped
        metadata-table reads only (`load_metadata_for_dedup`,
        `batch_check_existing`, `check_temporal_overlaps` all key off
        `receiver_name`), zero cross-group reads, no store write.
        """
        self._check_preprocessing(receiver_name, augmented_datasets)
        file_hash_map = {
            fname: ds.attrs.get("File Hash") for fname, ds in augmented_datasets
        }
        existing_hashes = self._check_existing_with_temporal_overlap(
            receiver_name, augmented_datasets, file_hash_map
        )
        return GroupWritePlan(
            receiver_name=receiver_name,
            augmented_datasets=augmented_datasets,
            rinex_files=rinex_files,
            aux_datasets=aux_datasets,
            sid_issues=sid_issues,
            reader_format=reader_format,
            file_hash_map=file_hash_map,
            existing_hashes=existing_hashes,
        )

    def _write_group_into_fork(
        self,
        fork_session: ForkSession,
        plan: GroupWritePlan,
    ) -> GroupWriteResult:
        """Write one receiver group's remaining files into its own fork.

        Runs inside the cross-group thread pool, one call per group. Mirrors
        `_append_to_icechunk`'s STEP 2 (non-overwrite branches) + STEP 3,
        with `session` replaced by this group's own `fork_session` --
        `ForkSession` is a drop-in for `to_icechunk`/`append_metadata_bulk`,
        already proven by `_cooperative_distributed_writing`. No "initial"
        case here: `_write_receiver_batch_forked`'s pre-pass has already
        created any brand-new group (and trimmed its first file out of
        `plan.augmented_datasets`) before this is ever called, so every file
        seen here targets an already-existing group.
        """
        log = self._logger
        receiver_name = plan.receiver_name
        file_hash_map = plan.file_hash_map
        existing_hashes = plan.existing_hashes

        t_start = time.perf_counter()
        result = GroupWriteResult(
            receiver_name=receiver_name,
            fork=fork_session,
            existing_hashes=existing_hashes,
            aux_datasets=plan.aux_datasets,
            reader_format=plan.reader_format,
        )

        written_fnames: list[Path] = []
        for idx, (fname, ds) in enumerate(plan.augmented_datasets):
            try:
                rel_path = self.site.gnss_store.rel_path_for_commit(fname)
                rinex_hash = file_hash_map[fname]
                if not rinex_hash:
                    log.debug("No hash for %s, skipping", fname)
                    continue

                exists = rinex_hash in existing_hashes

                ds_clean = self.site.gnss_store._cleanse_dataset_attrs(ds)
                ds_clean = self.site.gnss_store._normalize_encodings(ds_clean)

                t_file = time.perf_counter()
                action = "skipped"
                match (exists, self._gnss_store_strategy):
                    case (True, "skip"):
                        result.actions["skipped"] += 1
                        log.debug("Skipped: %s", rel_path)

                    case (True, "unsafe_append"):
                        # File exists but write again anyway -- no
                        # epoch-uniqueness check, see StorageConfig.
                        # gnss_store_strategy docstring for the risk.
                        to_icechunk(
                            prepare_write(
                                ds_clean,
                                fork_session.store,
                                receiver_name,
                                append_dim="epoch",
                            ),
                            fork_session,
                            group=receiver_name,
                            append_dim="epoch",
                        )
                        result.actions["appended"] += 1
                        action = "appended"
                        log.debug("Appended (unsafe): %s", rel_path)

                    case (False, _):
                        to_icechunk(
                            prepare_write(
                                ds_clean,
                                fork_session.store,
                                receiver_name,
                                append_dim="epoch",
                            ),
                            fork_session,
                            group=receiver_name,
                            append_dim="epoch",
                        )
                        result.actions["written"] += 1
                        action = "written"
                        log.debug("Wrote: %s", rel_path)

                    case _:
                        log.warning(
                            "Unhandled strategy: exists=%s, strategy=%s for %s",
                            exists,
                            self._gnss_store_strategy,
                            rel_path,
                        )
                        action = "unhandled"

                result.metadata_records.append(
                    self._logbook_row(fname, ds, rinex_hash, exists, rel_path, action)
                )
                if action in ("written", "appended"):
                    written_fnames.append(fname)

                dt_file = time.perf_counter() - t_file
                result.file_append_seconds.append(dt_file)
                n_epochs = int(ds_clean.sizes.get("epoch", 0))
                result.total_epochs += n_epochs
                result.total_nbytes += int(ds_clean.nbytes)
                self._icechunk_log.info(
                    "icechunk.file_append",
                    duration_seconds=round(dt_file, 4),
                    receiver=receiver_name,
                    date=str(self.matched_data_dirs.yyyydoy),
                    file=fname.name,
                    file_index=idx,
                    action=action,
                    n_epochs=n_epochs,
                    n_sids=int(ds_clean.sizes.get("sid", 0)),
                )

            except (OSError, RuntimeError, ValueError):  # fmt: skip
                log.exception("Failed to process %s", fname.name)

        self._write_sbf_obs(
            fork_session, receiver_name, plan.aux_datasets, written_fnames
        )

        # Log-book rows are written into this fork by the caller once the
        # batch commit message is known (_write_receiver_batch_forked).
        result.duration_seconds = time.perf_counter() - t_start
        return result

    def _write_receiver_batch_forked(
        self,
        group_inputs: Sequence[
            tuple[
                str,  # receiver_name
                list[tuple[Path, xr.Dataset]],  # augmented_datasets
                list[Path],  # rinex_files
                dict[Path, dict[str, xr.Dataset]] | None,  # aux_datasets
                dict[str, list[str]] | None,  # sid_issues
                str | None,  # reader_format
            ]
        ],
    ) -> dict[str, GroupWriteResult]:
        """Write a whole batch's receiver groups in parallel via fork/merge.

        1. Sequential pre-pass, on its own clean session that commits alone
           before any fork exists: any group not yet in the store gets its
           first file written directly here (never touches a fork -- avoids
           relying on unverified concurrent-new-group-creation semantics in
           `Session.merge()`), and that file is trimmed out of the group's
           plan before dedup-checking so it's never written twice or
           double-counted. This session MUST be separate from the fork/merge
           session below and MUST commit on its own -- verified empirically
           (not documented anywhere in Icechunk's Python API) that when a
           session has its own pending uncommitted writes before `.fork()`
           is called on it, `session.merge(fork)` silently drops the fork's
           appended data on commit. The only way to combine "some groups
           need creating" with "other groups get parallel forked writes"
           correctly is two commits: the pre-pass commits alone, then the
           fork/merge phase opens a session with no pending writes of its
           own before forking. Cost: one small extra commit, only on
           batches that see a brand-new group (i.e. rarely, after a
           store's first day).
        2. `_prepare_group_write` per group (post-pre-pass, so a
           newly-created group's dedup check runs against the group it now
           has, not "doesn't exist yet").
        3. One independent fork per group, dispatched into a thread pool
           (`_write_group_into_fork`) -- not a process pool: PHASE 2 already
           holds all datasets in this process's memory, PHASE 3 is I/O-bound
           (releases the GIL), and threads keep `zarr_async_concurrency` at
           its configured per-process value instead of multiplying it by
           worker count against a CIFS/NFS mount.
        4. Fail-fast: if any group's write raises, do not merge or commit --
           groups before it in today's sequential loop stay committed on
           retry, but under one shared batch commit that property is
           structurally impossible, so a partial merge would silently drop
           a group's data from an apparently-successful commit. A pre-pass
           commit that already landed before a later fork failure is safe
           to leave in place: the next run's dedup check sees that group's
           first file as already-committed metadata and won't re-attempt it.
        5. One `base_session.merge(*forks)` + one `base_session.commit(...)`
           for the groups written this round via fork.
        """
        self._ensure_gnss_store_metadata(
            [name for name, *_ in group_inputs],
            next((fmt for *_, fmt in group_inputs if fmt), None),
        )
        version = get_version_from_pyproject()
        log = self._logger
        yyyydoy = str(self.matched_data_dirs.yyyydoy)

        groups = self.site.gnss_store.list_groups() or []
        results: dict[str, GroupWriteResult] = {}
        plan_inputs: list[
            tuple[
                str,
                list[tuple[Path, xr.Dataset]],
                list[Path],
                dict[Path, dict[str, xr.Dataset]] | None,
                dict[str, list[str]] | None,
                str | None,
            ]
        ] = []
        new_group_inputs: list[
            tuple[
                str,
                list[tuple[Path, xr.Dataset]],
                list[Path],
                dict[Path, dict[str, xr.Dataset]] | None,
                dict[str, list[str]] | None,
                str | None,
            ]
        ] = []

        for (
            receiver_name,
            augmented_datasets,
            rinex_files,
            aux_datasets,
            sid_issues,
            reader_format,
        ) in group_inputs:
            if not augmented_datasets:
                # No files for this group today -- still produce a
                # (zero-action) result so downstream steps 5-9 and the
                # PHASE 3 caller see it, matching `_append_to_icechunk`
                # being called (and yielded from) even with an empty
                # `augmented_datasets` list today.
                results.setdefault(
                    receiver_name,
                    GroupWriteResult(
                        receiver_name=receiver_name,
                        fork=None,
                        aux_datasets=aux_datasets,
                        reader_format=reader_format,
                    ),
                )
            elif receiver_name in groups:
                plan_inputs.append(
                    (
                        receiver_name,
                        augmented_datasets,
                        rinex_files,
                        aux_datasets,
                        sid_issues,
                        reader_format,
                    )
                )
            else:
                new_group_inputs.append(
                    (
                        receiver_name,
                        augmented_datasets,
                        rinex_files,
                        aux_datasets,
                        sid_issues,
                        reader_format,
                    )
                )

        # STEP 1 (pre-pass): new groups only, sequential, on its own session
        # that commits alone (see docstring point 1).
        prepass_snapshot_id: str | None = None
        if new_group_inputs:
            prepass_summary_parts: list[str] = []
            prepass_rows: dict[str, dict[str, Any]] = {}
            with self.site.gnss_store.writable_session("main") as prepass_session:
                for (
                    receiver_name,
                    augmented_datasets,
                    rinex_files,
                    aux_datasets,
                    sid_issues,
                    reader_format,
                ) in new_group_inputs:
                    # Find the first file with a usable hash (matches
                    # `_append_to_icechunk`'s STEP 3, which silently
                    # `continue`s past unhashed files without counting or
                    # consuming them -- the "initial" writer isn't
                    # necessarily index 0).
                    init_idx = next(
                        (
                            i
                            for i, (_fn, _ds) in enumerate(augmented_datasets)
                            if _ds.attrs.get("File Hash")
                        ),
                        None,
                    )
                    result = results.setdefault(
                        receiver_name,
                        GroupWriteResult(
                            receiver_name=receiver_name,
                            fork=None,
                            aux_datasets=aux_datasets,
                            reader_format=reader_format,
                        ),
                    )

                    if init_idx is None:
                        # No hashed file in this brand-new group's batch --
                        # nothing to create the group with, leave it absent
                        # from the store (same net effect as
                        # `_append_to_icechunk` today, which would also fail
                        # to ever hit its "initial" case here).
                        log.warning(
                            "No hashed file to initialize new group '%s' "
                            "with -- skipping (0 usable files)",
                            receiver_name,
                        )
                        continue

                    first_fname, first_ds = augmented_datasets[init_idx]
                    rinex_hash = first_ds.attrs.get("File Hash")
                    t_file = time.perf_counter()
                    rel_path = self.site.gnss_store.rel_path_for_commit(first_fname)
                    ds_clean = self.site.gnss_store._cleanse_dataset_attrs(first_ds)
                    ds_clean = self.site.gnss_store._normalize_encodings(ds_clean)
                    to_icechunk(
                        prepare_write(
                            ds_clean,
                            prepass_session.store,
                            receiver_name,
                            append_dim=None,
                        ),
                        prepass_session,
                        group=receiver_name,
                        encoding=with_time_units(
                            ds_clean, self.site.gnss_store.chunk_encoding_for(ds_clean)
                        ),
                    )
                    self._write_sbf_obs(
                        prepass_session, receiver_name, aux_datasets, [first_fname]
                    )
                    row = self._logbook_row(
                        first_fname,
                        first_ds,
                        str(rinex_hash),
                        False,
                        rel_path,
                        "initial",
                    )
                    prepass_rows[receiver_name] = row
                    result.metadata_records.append(row)
                    result.actions["initial"] += 1
                    dt_file = time.perf_counter() - t_file
                    result.file_append_seconds.append(dt_file)
                    n_epochs = int(ds_clean.sizes.get("epoch", 0))
                    result.total_epochs += n_epochs
                    result.total_nbytes += int(ds_clean.nbytes)
                    self._icechunk_log.info(
                        "icechunk.file_append",
                        duration_seconds=round(dt_file, 4),
                        receiver=receiver_name,
                        date=yyyydoy,
                        file=first_fname.name,
                        file_index=init_idx,
                        action="initial",
                        n_epochs=n_epochs,
                        n_sids=int(ds_clean.sizes.get("sid", 0)),
                    )
                    log.debug("Initial (pre-pass): %s", rel_path)

                    groups = [*groups, receiver_name]
                    prepass_summary_parts.append(f"{receiver_name}(initial=1)")
                    remaining = [
                        fd for i, fd in enumerate(augmented_datasets) if i != init_idx
                    ]
                    plan_inputs.append(
                        (
                            receiver_name,
                            remaining,
                            rinex_files,
                            aux_datasets,
                            sid_issues,
                            reader_format,
                        )
                    )

                if prepass_summary_parts:
                    prepass_msg = _with_run_id(
                        f"[v{version}] {yyyydoy}: pre-pass create "
                        f"{len(prepass_summary_parts)} groups: "
                        f"{', '.join(prepass_summary_parts)}"
                    )
                    for receiver_name, row in prepass_rows.items():
                        row["commit_msg"] = prepass_msg
                        self.site.gnss_store.append_metadata_bulk(
                            group_name=receiver_name,
                            rows=[row],
                            session=prepass_session,
                        )
                    prepass_snapshot_id = commit_with_rebase(
                        prepass_session,
                        prepass_msg,
                        store_path=self.site.gnss_store.store_path,
                        config=self._config,
                    )
                    log.info(
                        "Committed pre-pass %s (snapshot: %s...)",
                        yyyydoy,
                        prepass_snapshot_id[:8],
                    )
                    for name in (p[0] for p in new_group_inputs):
                        if name in results:
                            results[name].snapshot_id = prepass_snapshot_id

        # STEP 2: dedup-check plans, now that every group in this batch
        # already exists (pre-pass ran above, on its own committed session).
        plans = {
            name: self._prepare_group_write(
                augmented_datasets=aug,
                receiver_name=name,
                rinex_files=rinex_files,
                aux_datasets=aux_datasets,
                sid_issues=sid_issues,
                reader_format=reader_format,
            )
            for name, aug, rinex_files, aux_datasets, sid_issues, reader_format in plan_inputs
            if aug
        }

        # STEP 3/4/5: fork + dispatch + fail-fast collect + merge + one
        # commit, on a fresh session with no pending writes of its own.
        if plans:
            with self.site.gnss_store.writable_session("main") as base_session:
                forks = {name: base_session.fork() for name in plans}
                with ThreadPoolExecutor(max_workers=len(plans)) as tpe:
                    futures = {
                        tpe.submit(self._write_group_into_fork, forks[name], plan): name
                        for name, plan in plans.items()
                    }
                    completed: dict[str, GroupWriteResult] = {}
                    try:
                        for fut in as_completed(futures):
                            name = futures[fut]
                            completed[name] = fut.result()
                    except Exception:
                        log.error(
                            "cross_group_batch_write_failed",
                            date=yyyydoy,
                            succeeded=list(completed),
                            pending=[n for n in plans if n not in completed],
                        )
                        raise

                # This fork's own log-book rows, before pre-pass rows (already
                # committed with the pre-pass) are merged into the result.
                fork_rows = {
                    name: list(res.metadata_records) for name, res in completed.items()
                }

                # Merge pre-pass results (if any) into fork results.
                for name, forked_result in completed.items():
                    if name in results:
                        pre = results[name]
                        forked_result.actions["initial"] += pre.actions["initial"]
                        forked_result.metadata_records = (
                            pre.metadata_records + forked_result.metadata_records
                        )
                        forked_result.file_append_seconds = (
                            pre.file_append_seconds + forked_result.file_append_seconds
                        )
                        forked_result.total_epochs += pre.total_epochs
                        forked_result.total_nbytes += pre.total_nbytes
                        forked_result.duration_seconds += pre.duration_seconds
                    results[name] = forked_result

                summary = ", ".join(
                    f"{name}({', '.join(f'{k}={v}' for k, v in completed[name].actions.items() if v > 0)})"
                    for name in completed
                )
                commit_msg = _with_run_id(
                    f"[v{version}] {yyyydoy}: {len(completed)} groups: {summary}"
                )
                for name, rows in fork_rows.items():
                    if not rows:
                        continue
                    for row in rows:
                        row["commit_msg"] = commit_msg
                    self.site.gnss_store.append_metadata_bulk(
                        group_name=name, rows=rows, session=forks[name]
                    )

                base_session.merge(*forks.values())

                agg_metadata: dict[str, Any] = {
                    "date": yyyydoy,
                    "receivers": ",".join(completed),
                    "total_files": str(
                        sum(len(r.metadata_records) for r in completed.values())
                    ),
                }
                for name, r in completed.items():
                    if not r.metadata_records:
                        continue
                    group_meta = {
                        "receiver": name,
                        "start": str(min(rec["start"] for rec in r.metadata_records)),
                        "end": str(max(rec["end"] for rec in r.metadata_records)),
                        "rinex_hashes": ",".join(
                            str(rec["rinex_hash"])
                            for rec in r.metadata_records
                            if rec.get("rinex_hash")
                        ),
                        "canonical_names": ",".join(
                            str(rec["canonical_name"])
                            for rec in r.metadata_records
                            if rec.get("canonical_name")
                        ),
                    }
                    agg_metadata[f"group__{name}"] = json.dumps(group_meta)

                batch_snapshot_id = commit_with_rebase(
                    base_session,
                    commit_msg,
                    metadata=agg_metadata,
                    store_path=self.site.gnss_store.store_path,
                    config=self._config,
                )
                log.info(
                    "Committed batch %s (snapshot: %s...)",
                    yyyydoy,
                    batch_snapshot_id[:8],
                )
                for name in completed:
                    results[name].snapshot_id = batch_snapshot_id

        # STEP 6: per-group post-commit diagnostics + keeper tags, sourced
        # from each group's own snapshot_id -- a group may have landed in
        # the pre-pass commit only (single-file new group, never forked),
        # the batch commit only (pre-existing group), both (new group with
        # more than one file), or neither (empty augmented_datasets today).
        dir_counts = self.site.gnss_store.dir_entry_counts()
        for name, r in results.items():
            if r.snapshot_id is None:
                # Nothing written for this group today (empty
                # augmented_datasets or a hashless new group) -- no
                # snapshot to tag or report against.
                continue

            if self._keeper_tags_enabled:
                self.site.gnss_store.create_keeper_tag(name, yyyydoy, r.snapshot_id)

            self._icechunk_log.info(
                "store_stats",
                receiver=name,
                date=yyyydoy,
                **dir_counts,
            )

            if r.file_append_seconds:
                _sorted = sorted(r.file_append_seconds)
                _n = len(_sorted)
                process_data_per_file = {
                    "n": _n,
                    "mean": round(sum(_sorted) / _n, 4),
                    "p50": round(_sorted[_n // 2], 4),
                    "p95": round(_sorted[min(_n - 1, int(_n * 0.95))], 4),
                    "max": round(_sorted[-1], 4),
                    "first": round(r.file_append_seconds[0], 4),
                    "last": round(r.file_append_seconds[-1], 4),
                }
            else:
                process_data_per_file = {}

            self._icechunk_log.info(
                "batch_write_complete",
                receiver=name,
                date=yyyydoy,
                snapshot_id=r.snapshot_id[:12],
                total_files=len(r.metadata_records),
                total_epochs=r.total_epochs,
                total_nbytes=r.total_nbytes,
                duration_seconds=round(r.duration_seconds, 2),
                process_data_per_file=process_data_per_file,
                actions=r.actions,
                throughput_files_per_sec=(
                    round(len(r.metadata_records) / r.duration_seconds, 2)
                    if r.duration_seconds > 0
                    else 0.0
                ),
            )

        # STEP 7: source_format root attr, once per batch (idempotent).
        if results and self.site.gnss_store.source_format is None:
            first_result = next(iter(results.values()))
            reader_fmt = first_result.reader_format or self._reader_name
            self.site.gnss_store.set_root_attrs(
                {"source_format": reader_fmt}, branch="main"
            )
            log.info("Set store source_format='%s'", reader_fmt)

        return results

    def _append_to_icechunk(
        self,
        augmented_datasets: list[tuple[Path, xr.Dataset]],
        receiver_name: str,
        rinex_files: list[Path],
        aux_datasets: dict[Path, dict[str, xr.Dataset]] | None = None,
        sid_issues: dict[str, list[str]] | None = None,
        reader_format: str | None = None,
    ) -> set[str]:
        """Batch append with single commit.

        Returns the set of file hashes that were skipped due to dedup (already
        in the store). An empty set means all files were written successfully.
        Callers can use this to decide whether to build the daily dataset from
        in-memory parts (empty) or fall back to a store read (non-empty).

        This method:
        1. Opens ONE session for all data writes
        2. Uses only to_icechunk() within the session (no nested sessions)
        3. Makes ONE commit for all data
        4. Gives a new store its metadata first; the commit writes the
           root copy and snapshot summary (ADR 0014)
        5. Writes any auxiliary datasets (e.g. SBF metadata) after commit
        """
        _ = rinex_files
        log = self._logger
        self._ensure_gnss_store_metadata([receiver_name], reader_format)
        version = get_version_from_pyproject()

        t_start = time.time()

        self._icechunk_log.info(
            "batch_write_session_started",
            receiver=receiver_name,
            total_files=len(augmented_datasets),
            strategy="single_commit",
        )

        # STEP 1: Batch check which files exist
        log.info("Batch checking %s files...", len(augmented_datasets))
        t1 = time.time()

        self._icechunk_log.debug(
            "batch_check_started",
            receiver=receiver_name,
            files=len(augmented_datasets),
        )

        self._check_preprocessing(receiver_name, augmented_datasets)

        file_hash_map = {
            fname: ds.attrs.get("File Hash") for fname, ds in augmented_datasets
        }

        existing_hashes = self._check_existing_with_temporal_overlap(
            receiver_name, augmented_datasets, file_hash_map
        )

        t2 = time.time()
        self._icechunk_log.info(
            "batch_check_complete",
            receiver=receiver_name,
            duration_seconds=round(t2 - t1, 2),
            existing=len(existing_hashes),
            total=len(augmented_datasets),
            # Metadata-table row count at check time -- lets a future run
            # correlate batch_check duration against store growth directly
            # instead of assuming O(rows) scaling.
            metadata_rows=self.site.gnss_store.metadata_row_count(receiver_name),
        )
        log.info(
            "Batch check complete in %.2fs: %s/%s existing",
            t2 - t1,
            len(existing_hashes),
            len(augmented_datasets),
        )

        # STEP 2: Branch-stage-promote for overwrite; direct main for others
        is_overwrite = self._gnss_store_strategy == "overwrite"
        temp_branch = None
        current_snapshot = ""

        # Timing for the write-performance investigation: batch_write_complete's
        # `timings` dict left several calls unaccounted for, so its residual
        # (duration_seconds - sum(timings)) grew 12x over a 63-min local-store
        # run and correlated r=0.95 with manifest/snapshot count without
        # pinning down which call. These four timers close that gap. Default
        # 0.0 for steps that don't run this batch (e.g. non-overwrite runs
        # skip branch_setup entirely).
        t_branch_setup = 0.0
        if is_overwrite:
            _t_branch0 = time.perf_counter()
            yyyydoy = self.matched_data_dirs.yyyydoy.to_str()
            temp_branch = f"overwrite_{receiver_name}_{yyyydoy}"
            current_snapshot = self.site.gnss_store.repo.lookup_branch("main")
            if temp_branch in self.site.gnss_store.repo.list_branches():
                # Left by an earlier overwrite of this receiver and day that
                # failed or could not be promoted; this run redoes its work.
                log.warning(
                    "Replacing temp branch '%s' left by an earlier overwrite",
                    temp_branch,
                )
                self.site.gnss_store.repo.delete_branch(temp_branch)
            self.site.gnss_store.repo.create_branch(temp_branch, current_snapshot)
            log.info(
                "Created temp branch '%s' for overwrite (snapshot: %s...)",
                temp_branch,
                current_snapshot[:8],
            )
            branch = temp_branch
            t_branch_setup = time.perf_counter() - _t_branch0
        else:
            branch = "main"

        log.info("Opening Icechunk session...")
        t3 = time.time()
        with self.site.gnss_store.writable_session(branch) as session:
            groups = self.site.gnss_store.list_groups() or []
            t4 = time.time()
            log.info("Session opened in %.2fs", t4 - t3)

            # Fires on every batch after the group's first write. Uses raw
            # Zarr array metadata, not xr.open_zarr(), so it stays O(1) in
            # manifest count -- see _check_store_vars_consistency docstring.
            t_vars_consistency = 0.0
            if receiver_name in groups:
                _t_vars0 = time.perf_counter()
                self._check_store_vars_consistency(
                    session, receiver_name, augmented_datasets
                )
                t_vars_consistency = time.perf_counter() - _t_vars0

            # Prepare store for overwrite (rewrite the group with this batch
            # merged in epoch order; those files are not appended again)
            t_overwrite_prep = 0.0
            rewritten_fnames: set[Path] = set()
            if is_overwrite and receiver_name in groups:
                _t_ovr0 = time.perf_counter()
                rewritten_fnames = self._prepare_store_for_overwrite(
                    session,
                    receiver_name,
                    augmented_datasets,
                    existing_hashes,
                    file_hash_map,
                    aux_datasets,
                )
                t_overwrite_prep = time.perf_counter() - _t_ovr0

            actions = {
                "initial": 0,
                "skipped": 0,
                "appended": 0,
                "written": 0,
                "overwritten": 0,
            }
            metadata_records = []  # Collect metadata to write before commit
            written_fnames: list[Path] = []  # files whose observations are stored

            try:
                # STEP 3: Process all datasets using ONLY to_icechunk()
                log.info(
                    "Processing %s datasets...",
                    len(augmented_datasets),
                )
                t5 = time.time()
                file_append_seconds: list[float] = []
                total_epochs = 0
                total_nbytes = 0

                for idx, (fname, ds) in enumerate(augmented_datasets):
                    # Progress logging
                    if idx % 20 == 0 and idx > 0:
                        elapsed = time.time() - t5
                        rate = idx / elapsed if elapsed > 0 else 0
                        log.info(
                            "  Progress: %s/%s (%.1f files/s)",
                            idx,
                            len(augmented_datasets),
                            rate,
                        )

                    try:
                        rel_path = self.site.gnss_store.rel_path_for_commit(fname)
                        rinex_hash = file_hash_map[fname]

                        if not rinex_hash:
                            log.debug("No hash for %s, skipping", fname)
                            continue

                        # Fast hash check
                        exists = rinex_hash in existing_hashes

                        # Cleanse dataset
                        ds_clean = self.site.gnss_store._cleanse_dataset_attrs(
                            ds,
                        )
                        ds_clean = self.site.gnss_store._normalize_encodings(
                            ds_clean,
                        )

                        # Handle data writes using ONLY to_icechunk() with our session
                        t_file = time.perf_counter()
                        action = "skipped"
                        match (exists, self._gnss_store_strategy):
                            case _ if fname in rewritten_fnames:
                                # Already stored by the overwrite rewrite
                                action = "overwritten" if exists else "written"
                                actions[action] += 1
                                log.debug("Rewritten (overwrite): %s", rel_path)

                            case (False, _) if receiver_name not in groups:
                                # Initial group creation (first non-skipped file).
                                # encoding= fixes physical chunk shape to match
                                # chunk_strategies config (2026-07-18) -- Zarr
                                # fixes chunk shape at creation, and nothing
                                # previously applied config here, leaving it
                                # to Zarr's own default (see store.py's
                                # chunk_encoding_for docstring for the full
                                # investigation).
                                to_icechunk(
                                    prepare_write(
                                        ds_clean,
                                        session.store,
                                        receiver_name,
                                        append_dim=None,
                                    ),
                                    session,
                                    group=receiver_name,
                                    encoding=with_time_units(
                                        ds_clean,
                                        self.site.gnss_store.chunk_encoding_for(
                                            ds_clean
                                        ),
                                    ),
                                )
                                groups.append(receiver_name)
                                actions["initial"] += 1
                                action = "initial"
                                log.debug("Initial: %s", rel_path)

                            case (True, "skip"):
                                # File exists, skip writing data
                                actions["skipped"] += 1
                                log.debug("Skipped: %s", rel_path)

                            case (True, "unsafe_append"):
                                # File exists but write again anyway -- no
                                # epoch-uniqueness check, see StorageConfig.
                                # gnss_store_strategy docstring for the risk.
                                to_icechunk(
                                    prepare_write(
                                        ds_clean,
                                        session.store,
                                        receiver_name,
                                        append_dim="epoch",
                                    ),
                                    session,
                                    group=receiver_name,
                                    append_dim="epoch",
                                )
                                actions["appended"] += 1
                                action = "appended"
                                log.debug("Appended (unsafe): %s", rel_path)

                            case (False, _):
                                # New file, write it
                                to_icechunk(
                                    prepare_write(
                                        ds_clean,
                                        session.store,
                                        receiver_name,
                                        append_dim="epoch",
                                    ),
                                    session,
                                    group=receiver_name,
                                    append_dim="epoch",
                                )
                                actions["written"] += 1
                                action = "written"
                                log.debug("Wrote: %s", rel_path)

                            case (True, "overwrite"):
                                # Only reached when the rewrite had nothing to
                                # replace; the old data is already gone
                                to_icechunk(
                                    prepare_write(
                                        ds_clean,
                                        session.store,
                                        receiver_name,
                                        append_dim="epoch",
                                    ),
                                    session,
                                    group=receiver_name,
                                    append_dim="epoch",
                                )
                                actions["overwritten"] += 1
                                action = "overwritten"
                                log.debug("Overwrote: %s", rel_path)

                            case _:
                                log.warning(
                                    "Unhandled strategy: exists=%s, strategy=%s for %s",
                                    exists,
                                    self._gnss_store_strategy,
                                    rel_path,
                                )
                                action = "unhandled"

                        # Log-book row for ALL files, skipped ones included
                        # (written with the data, below)
                        metadata_records.append(
                            self._logbook_row(
                                fname, ds, rinex_hash, exists, rel_path, action
                            )
                        )
                        if action in ("initial", "written", "appended", "overwritten"):
                            written_fnames.append(fname)

                        # Per-file append timing: breaks open the "process_data"
                        # aggregate below into per-file numbers so a future run can
                        # tell whether cost grows uniformly within a batch (session/
                        # manifest state) or is concentrated in specific files.
                        dt_file = time.perf_counter() - t_file
                        file_append_seconds.append(dt_file)
                        n_epochs = int(ds_clean.sizes.get("epoch", 0))
                        total_epochs += n_epochs
                        total_nbytes += int(ds_clean.nbytes)
                        self._icechunk_log.info(
                            "icechunk.file_append",
                            duration_seconds=round(dt_file, 4),
                            receiver=receiver_name,
                            date=str(self.matched_data_dirs.yyyydoy),
                            file=fname.name,
                            file_index=idx,
                            action=action,
                            n_epochs=n_epochs,
                            n_sids=int(ds_clean.sizes.get("sid", 0)),
                        )

                    except (OSError, RuntimeError, ValueError):  # fmt: skip
                        log.exception("Failed to process %s", fname.name)

                t6 = time.time()
                log.info("Dataset processing complete in %.2fs", t6 - t5)

                # STEP 4: Write sbf_obs and the log book, then a single commit
                # for data + metadata. The sbf_obs of files an overwrite
                # rewrote is already in the rewritten group.
                self._write_sbf_obs(
                    session,
                    receiver_name,
                    aux_datasets,
                    [f for f in written_fnames if f not in rewritten_fnames],
                )
                summary = ", ".join(f"{k}={v}" for k, v in actions.items() if v > 0)
                commit_msg = _with_run_id(
                    f"[v{version}] {receiver_name} "
                    f"{self.matched_data_dirs.yyyydoy}: {summary}"
                )
                for record in metadata_records:
                    record["commit_msg"] = commit_msg

                log.info(
                    "Writing metadata for %s files...",
                    len(metadata_records),
                )
                t9 = time.time()
                # No commit without the log-book rows: a file stored without
                # its row is not recognized as stored by the next run.
                self.site.gnss_store.append_metadata_bulk(
                    group_name=receiver_name,
                    rows=metadata_records,
                    session=session,
                )
                t10 = time.time()
                log.info("Metadata write complete in %.2fs", t10 - t9)

                log.info("Committing: %s", summary)
                t7 = time.time()
                _commit_meta: dict = {
                    "receiver": receiver_name,
                    "date": str(self.matched_data_dirs.yyyydoy),
                    "files": str(len(metadata_records)),
                }
                if metadata_records:
                    _commit_meta["start"] = str(
                        min(r["start"] for r in metadata_records)
                    )
                    _commit_meta["end"] = str(max(r["end"] for r in metadata_records))
                    _commit_meta["rinex_hashes"] = ",".join(
                        str(r["rinex_hash"])
                        for r in metadata_records
                        if r.get("rinex_hash")
                    )
                    _commit_meta["canonical_names"] = ",".join(
                        str(r["canonical_name"])
                        for r in metadata_records
                        if r.get("canonical_name")
                    )
                snapshot_id = commit_with_rebase(
                    session,
                    commit_msg,
                    metadata=_commit_meta,
                    store_path=self.site.gnss_store.store_path,
                    config=self._config,
                )
                t8 = time.time()
                log.info(
                    "Commit complete in %.2fs (snapshot: %s...)",
                    t8 - t7,
                    snapshot_id[:8],
                )

                # Retention keeper tag -- additive, inert, off by default.
                # Never fails the write: create_keeper_tag() swallows tag
                # name collisions itself.
                t_keeper_tag = 0.0
                if self._keeper_tags_enabled:
                    _t_keeper0 = time.perf_counter()
                    self.site.gnss_store.create_keeper_tag(
                        receiver_name,
                        str(self.matched_data_dirs.yyyydoy),
                        snapshot_id,
                    )
                    t_keeper_tag = time.perf_counter() - _t_keeper0

                # Cheap on-disk store-internal stats (manifest/snapshot/
                # transaction directory entry counts) sampled once per
                # batch -- a directional proxy for Icechunk-internal growth,
                # to test whether the write-side slowdown tracks manifest
                # count. Deliberately skips chunks/ (unbounded).
                t_stats = time.perf_counter()
                dir_counts = self.site.gnss_store.dir_entry_counts()
                t_store_stats = time.perf_counter() - t_stats
                self._icechunk_log.info(
                    "store_stats",
                    duration_seconds=round(t_store_stats, 4),
                    receiver=receiver_name,
                    date=str(self.matched_data_dirs.yyyydoy),
                    **dir_counts,
                )

                # GC is intentionally skipped here. Running garbage_collect() after
                # every commit performs a full reachability scan over all snapshots,
                # manifests, and chunk objects — cost grows O(n) per batch → O(n²)
                # over a multi-year backfill. Call store.expire_old_snapshots() or
                # store.maintenance() once after the pipeline completes instead.

                # Timing summary
                t_end = time.time()

                if file_append_seconds:
                    _sorted = sorted(file_append_seconds)
                    _n = len(_sorted)
                    process_data_per_file = {
                        "n": _n,
                        "mean": round(sum(_sorted) / _n, 4),
                        "p50": round(_sorted[_n // 2], 4),
                        "p95": round(_sorted[min(_n - 1, int(_n * 0.95))], 4),
                        "max": round(_sorted[-1], 4),
                        "first": round(file_append_seconds[0], 4),
                        "last": round(file_append_seconds[-1], 4),
                    }
                else:
                    process_data_per_file = {}

                self._icechunk_log.info(
                    "batch_write_complete",
                    receiver=receiver_name,
                    date=str(self.matched_data_dirs.yyyydoy),
                    snapshot_id=snapshot_id[:12],
                    total_files=len(augmented_datasets),
                    total_epochs=total_epochs,
                    total_nbytes=total_nbytes,
                    duration_seconds=round(t_end - t_start, 2),
                    timings={
                        "batch_check": round(t2 - t1, 2),
                        "branch_setup": round(t_branch_setup, 2),
                        "open_session": round(t4 - t3, 2),
                        "vars_consistency": round(t_vars_consistency, 2),
                        "overwrite_prep": round(t_overwrite_prep, 2),
                        "process_data": round(t6 - t5, 2),
                        "commit": round(t8 - t7, 2),
                        "metadata": round(t10 - t9, 2),
                        "keeper_tag": round(t_keeper_tag, 2),
                        "store_stats": round(t_store_stats, 2),
                    },
                    process_data_per_file=process_data_per_file,
                    actions=actions,
                    throughput_files_per_sec=round(
                        len(augmented_datasets) / (t_end - t_start), 2
                    ),
                )

                log.info("\nTIMING BREAKDOWN:")
                log.info("  Batch check:    %.2fs", t2 - t1)
                log.info("  Open session:   %.2fs", t4 - t3)
                log.info("  Process data:   %.2fs", t6 - t5)
                log.info("  Commit:         %.2fs", t8 - t7)
                log.info("  Metadata:       %.2fs", t10 - t9)
                log.info("  TOTAL:          %.2fs", t_end - t_start)

                log.info(
                    "Successfully processed %s files for '%s'",
                    len(augmented_datasets),
                    receiver_name,
                )

            except (OSError, RuntimeError, ValueError):  # fmt: skip
                log.exception("Batch append failed")
                raise

        # STEP 5: Set source_format root attr (once, idempotent)
        if self.site.gnss_store.source_format is None:
            reader_fmt = reader_format or self._reader_name
            self.site.gnss_store.set_root_attrs(
                {"source_format": reader_fmt}, branch=branch
            )
            log.info("Set store source_format='%s'", reader_fmt)

        # Promote temp branch to main after successful commit. Refused with
        # BranchMovedError if main moved since the temp branch was created
        # (the new commits would be dropped); the temp branch is then kept.
        if is_overwrite and temp_branch:
            self.site.gnss_store.promote_branch(temp_branch, "main", current_snapshot)
            self.site.gnss_store.repo.delete_branch(temp_branch)

        # The "writing" step of the performance dashboard's per-day
        # breakdown, from t_start rather than a stage_timer() block.
        record_stage_timing(
            "writing",
            time.time() - t_start,
            receiver=receiver_name,
            date_key=self.matched_data_dirs.yyyydoy.to_str(),
        )

        return existing_hashes

    def _resolve_receiver_paths(self, receiver_type: str) -> tuple[Path, str | None]:
        """Resolve paths and receiver name for receiver type.

        Parameters
        ----------
        receiver_type : str
            Type of receiver ('canopy' or 'reference')

        Returns
        -------
        tuple[Path, str | None]
            (rinex_dir, receiver_name)

        """
        if receiver_type == "canopy":
            rinex_dir = self.matched_data_dirs.canopy_data_dir
        elif receiver_type == "reference":
            rinex_dir = self.matched_data_dirs.reference_data_dir
        else:
            msg = f"Unknown receiver type: {receiver_type}"
            raise ValueError(msg)

        # Get receiver name from site configuration
        receiver_name = None
        for name, config in self.site.active_receivers.items():
            if config.get("type") == receiver_type:
                receiver_name = name
                break

        return rinex_dir, receiver_name

    @deprecated(
        "parsed_rinex_data_gen_2_receivers() is left over from development and will be removed with the next major version. "
        "Use canvodpy.Site(<site>).pipeline() instead."
    )
    def parsed_rinex_data_gen_2_receivers(
        self,
        keep_vars: list[str] | None = None,
        receiver_types: list[str] | None = None,
    ) -> Generator[xr.Dataset]:
        """Generate datasets from RINEX files and append to Icechunk stores.

        Pipeline:
        1. Preprocess aux data ONCE per day with Hermite splines → Zarr
        2. Compute receiver position ONCE (shared for all receivers)
        3. For each receiver type (canopy, reference):
           a. Get list of RINEX files
           b. Parallel process via ProcessPoolExecutor
           c. Each worker: read RINEX + slice Zarr + compute φ, θ, r
           d. Sequential append to Icechunk store
           e. Yield final daily dataset

        Parameters
        ----------
        keep_vars : List[str], optional
            Variables to keep in datasets (default: from globals)
        receiver_types : List[str], optional
            Receiver types to process (default: ['canopy', 'reference'])

        Yields
        ------
        xr.Dataset
            Processed and augmented daily dataset for each receiver type

        """
        if receiver_types is None:
            receiver_types = ["canopy", "reference"]

        if keep_vars is None:
            keep_vars = self._config.processing.params.keep_gnss_observables

        self._logger.info(
            "Starting RINEX processing pipeline for: %s",
            receiver_types,
        )

        # Pre-flight: Get canopy files to infer sampling and compute position
        canopy_dir = self.matched_data_dirs.canopy_data_dir
        canopy_files = self._get_rinex_files(canopy_dir)
        if not canopy_files:
            msg = "No canopy RINEX files found - cannot infer sampling rate"
            raise ValueError(msg)

        # ====================================================================
        # STEP 1: Preprocess aux data ONCE per day with Hermite splines
        # (routes through _ensure_aux_data_preprocessed -- this call site used to duplicate the rmtree+rebuild logic
        # inline, bypassing the shared-cache lookup entirely)
        # ====================================================================
        self._logger.info("Preprocessing aux data with Hermite splines (once per day)")
        aux_zarr_path, aux_group = self._ensure_aux_data_preprocessed(
            canopy_files, self.matched_data_dirs.yyyydoy.to_str()
        )

        # ====================================================================
        # STEP 2: Compute receiver position
        # ====================================================================
        position_mode = self._config.processing.params.receiver_position_mode
        first_rnx = self._make_reader(canopy_files[0])
        first_ds = first_rnx.to_ds(keep_data_vars=[], write_global_attrs=True)
        shared_position = ECEFPosition.from_ds_metadata(first_ds)

        if position_mode == "per_receiver":
            self._logger.warning(
                "receiver_position_mode='per_receiver': each receiver will use "
                "its own RINEX header position. This breaks direct SNR "
                "comparability between receivers."
            )
        else:
            self._logger.info(
                "Computed receiver position (shared): %s",
                shared_position,
            )

        # ====================================================================
        # STEP 3: Process each receiver type
        # ====================================================================
        for receiver_type in receiver_types:
            self._logger.info("Processing receiver type: %s", receiver_type)

            # 3a. Resolve directories and receiver name
            rinex_dir, receiver_name = self._resolve_receiver_paths(receiver_type)

            if not receiver_name:
                self._logger.warning(
                    "No configured receiver for %s, skipping",
                    receiver_type,
                )
                continue

            # 3b. Get RINEX files for this receiver type
            rinex_files = self._get_rinex_files(rinex_dir)
            if not rinex_files:
                self._logger.warning(
                    "No RINEX files found in %s",
                    rinex_dir,
                )
                continue

            self._logger.info(
                "Found %s RINEX files to process",
                len(rinex_files),
            )

            # 3b'. Determine receiver position for this receiver
            if position_mode == "per_receiver":
                receiver_position = self._compute_receiver_position(
                    rinex_files, receiver_name
                )
                if receiver_position is None:
                    self._logger.error(
                        "Could not compute position for %s, skipping",
                        receiver_name,
                    )
                    continue
            else:
                receiver_position = shared_position

            # 3c. Parallel process via ProcessPoolExecutor
            augmented_datasets, aux_datasets, sid_issues = self._parallel_process_rinex(
                rinex_files=rinex_files,
                keep_vars=keep_vars,
                aux_zarr_path=aux_zarr_path,
                receiver_position=receiver_position,
                receiver_type=receiver_name,
                aux_group=aux_group,
            )

            # 3d. Sequential append to Icechunk store
            self._append_to_icechunk(
                augmented_datasets=augmented_datasets,
                receiver_name=receiver_name,
                rinex_files=rinex_files,
                aux_datasets=aux_datasets,
                sid_issues=sid_issues,
            )

            # 3e. Yield final daily dataset
            # Read back from store to get complete daily dataset
            date_obj = self.matched_data_dirs.yyyydoy.date
            assert date_obj is not None, "yyyydoy.date must not be None"
            start_time = datetime.combine(date_obj, datetime.min.time())
            end_time = datetime.combine(date_obj, datetime.max.time())
            time_range = (start_time, end_time)

            daily_dataset = self.site.read_receiver_data(
                receiver_name=receiver_name, time_range=time_range
            )

            self._logger.info(
                "Yielding daily dataset for %s ('%s'): %s",
                receiver_type,
                receiver_name,
                dict(daily_dataset.sizes),
            )

            yield daily_dataset

    def prepare_batch_tasks(
        self,
        keep_vars: list[str] | None,
        receiver_configs: list[tuple[str, str, ReceiverDay, ReceiverDay | None, str]],
    ) -> tuple[list[tuple], list[tuple[str, list[Path]]]]:
        """Prepare aux Zarr and task descriptors for flat loky submission.

        Performs Phase 1 work for one DOY without submitting to loky:
        normalize configs, preprocess aux data, compute positions, and
        build a flat list of task arguments.

        Parameters
        ----------
        keep_vars : list[str] | None
            Variables to keep in datasets.
        receiver_configs : list[tuple[str, str, ReceiverDay, ReceiverDay | None, str]]
            ``(receiver_name, receiver_type, data_dir, position_data_dir, reader_format)``
            tuples.

        Returns
        -------
        task_descriptors : list[tuple]
            Each tuple's last element is a bool marking its shape: ``False``
            tuples carry ``preprocess_with_hermite_aux`` args (one per
            (file, receiver) pair); ``True`` tuples carry
            ``preprocess_reference_with_hermite_aux_fanout`` args -- one per
            physical reference file, bundling every paired canopy's position
            into a single ``canopy_positions`` dict so the file is only
            parsed once regardless of how many canopies it's paired against.
            Element 4 is always a lane key (either
            the receiver/pairing name or a per-reference-file lane key) for
            ``_interleave_by_receiver``.
        receiver_file_map : list[tuple[str, list[Path]]]
            ``(receiver_name, rinex_files)`` for each receiver/pairing —
            needed for the Icechunk write phase.

        """
        t_batch_start = time.perf_counter()
        if keep_vars is None:
            keep_vars = self._config.processing.params.keep_gnss_observables

        # Get first receiver files to infer sampling rate for aux preprocessing
        first_receiver_name, _first_type, first_data_dir, _, first_fmt = (
            receiver_configs[0]
        )
        first_files = self._get_rinex_files(first_data_dir, first_fmt)

        if not first_files:
            msg = (
                f"No RINEX files found for {first_receiver_name} - "
                "cannot infer sampling rate"
            )
            self._logger.error(
                "prepare_batch_failed",
                reason="no_rinex_files",
                receiver=first_receiver_name,
            )
            raise ValueError(msg)

        date_str = self.matched_data_dirs.yyyydoy.to_str()
        if self.use_sbf_geometry:
            aux_zarr_path = None
            aux_group = None
            self._logger.info(
                "aux_preprocessing_skipped",
                reason="ephemeris_source=broadcast",
            )
        else:
            aux_zarr_path, aux_group = self._ensure_aux_data_preprocessed(
                first_files, date_str, reader_format=first_fmt
            )
        t_aux_done = time.perf_counter()

        task_descriptors: list[tuple] = []
        receiver_file_map: list[tuple[str, list[Path]]] = []
        store_radial_distance = self._config.processing.params.store_radial_distance
        store_sbf_raw_observables = (
            self._config.processing.params.store_sbf_raw_observables
        )
        rinex_v3_parser = self._config.processing.params.rinex_v3_parser
        aggregate_glonass_fdma = self._config.processing.params.aggregate_glonass_fdma

        # In broadcast + shared position mode, a reference file takes the
        # satellite geometry of the file of its paired canopy (its
        # position_data_dir) that starts at the same time. Index the files
        # of every canopy, by receiver name, by the start time of their
        # canonical names.
        canopy_files_by_start: dict[str, tuple[dict[datetime, Path], str]] = {}
        position_mode = self._config.processing.params.receiver_position_mode
        if self.use_sbf_geometry and position_mode == "shared":
            for rc_name, rc_type, rc_dir, _, rc_fmt in receiver_configs:
                if rc_type != "canopy":
                    continue
                by_start = {}
                for cf in self._get_rinex_files(rc_dir, rc_fmt):
                    start = self._file_start(cf)
                    if start is not None:
                        by_start[start] = cf
                canopy_files_by_start[rc_dir.receiver] = (
                    by_start,
                    rc_fmt or self._reader_name,
                )
                self._logger.info(
                    "canopy_broadcast_file_index_built",
                    canopy=rc_name,
                    canopy_files=len(by_start),
                )

        # Reference receivers paired against multiple canopies share the same
        # physical file set (same data_dir/reader_format) -- group them so
        # each file gets one fan-out task instead of one task per (file,
        # pairing) below. Only applies to the
        # Hermite-aux path: use_sbf_geometry pairs a reference with its own
        # SBF geometry per canopy via broadcast_canopy_file, a separate
        # mechanism left untouched.
        reference_groups: dict[
            tuple[ReceiverDay, str], list[tuple[str, ReceiverDay | None]]
        ] = {}
        if not self.use_sbf_geometry:
            for (
                receiver_name,
                _receiver_type,
                data_dir,
                position_data_dir,
                reader_format,
            ) in receiver_configs:
                if _receiver_type == "reference":
                    reference_groups.setdefault((data_dir, reader_format), []).append(
                        (receiver_name, position_data_dir)
                    )
        fanned_out_receiver_names = {
            receiver_name
            for pairings in reference_groups.values()
            for receiver_name, _pos_dir in pairings
        }

        for (
            receiver_name,
            _receiver_type,
            data_dir,
            position_data_dir,
            reader_format,
        ) in receiver_configs:
            if receiver_name in fanned_out_receiver_names:
                continue  # handled by the reference fan-out pass below

            rinex_files = self._get_rinex_files(data_dir, reader_format)
            if not rinex_files:
                self._logger.warning(
                    "no_rinex_files_found",
                    receiver=receiver_name,
                    data_dir=str(data_dir),
                    reader_format=reader_format,
                )
                continue

            if position_mode == "per_receiver":
                position_files = rinex_files
                self._logger.warning(
                    "receiver_position_mode='per_receiver': using %s's own "
                    "position (breaks direct SNR comparability)",
                    receiver_name,
                )
            else:
                position_files = (
                    self._get_rinex_files(position_data_dir, reader_format)
                    if position_data_dir
                    else rinex_files
                )
            t_pos_start = time.perf_counter()
            receiver_position = self._compute_receiver_position(
                position_files, receiver_name, reader_format=reader_format
            )
            t_pos_end = time.perf_counter()
            self._logger.info(
                "position_computed",
                receiver=receiver_name,
                position_seconds=round(t_pos_end - t_pos_start, 4),
                success=receiver_position is not None,
            )
            if receiver_position is None:
                continue

            receiver_file_map.append((receiver_name, rinex_files))

            effective_reader = reader_format or self._reader_name
            for rnx_file in rinex_files:
                # For reference receivers in broadcast + shared mode, the
                # file of the paired canopy that starts at the same time
                broadcast_canopy_file = None
                canopy_reader_fmt = None
                canopy_index = (
                    canopy_files_by_start.get(position_data_dir.receiver)
                    if _receiver_type == "reference" and position_data_dir
                    else None
                )
                if canopy_index is not None:
                    by_start, canopy_reader_fmt = canopy_index
                    start = self._file_start(rnx_file)
                    broadcast_canopy_file = (
                        by_start.get(start) if start is not None else None
                    )
                    if broadcast_canopy_file is None:
                        self._logger.warning(
                            "no_canopy_file_for_reference_geometry",
                            receiver=receiver_name,
                            file=rnx_file.name,
                            reason="the reference file's own broadcast "
                            "geometry is used",
                        )

                task_descriptors.append(
                    _task_args(
                        preprocess_with_hermite_aux,
                        is_reference_fanout=False,
                        rnx_file=rnx_file,
                        keep_vars=keep_vars,
                        aux_zarr_path=aux_zarr_path,
                        receiver_position=receiver_position,
                        receiver_type=receiver_name,
                        keep_sids=self.keep_sids,
                        reader_name=effective_reader,
                        use_sbf_geometry=self.use_sbf_geometry,
                        store_radial_distance=store_radial_distance,
                        store_sbf_raw_observables=store_sbf_raw_observables,
                        broadcast_canopy_file=broadcast_canopy_file,
                        broadcast_canopy_fmt=canopy_reader_fmt,
                        aux_group=aux_group,
                        rinex_v3_parser=rinex_v3_parser,
                        aggregate_glonass_fdma=aggregate_glonass_fdma,
                        date_key=self.matched_data_dirs.yyyydoy.to_str(),
                    )
                )

        # Reference fan-out pass: one task per physical reference file,
        # bundling every paired canopy's position so the file is parsed once.
        for (data_dir, reader_format), pairings in reference_groups.items():
            rinex_files = self._get_rinex_files(data_dir, reader_format)
            if not rinex_files:
                self._logger.warning(
                    "no_rinex_files_found",
                    receiver=[name for name, _pos_dir in pairings],
                    data_dir=str(data_dir),
                    reader_format=reader_format,
                )
                continue

            canopy_positions: dict[str, ECEFPosition] = {}
            for receiver_name, position_data_dir in pairings:
                if position_mode == "per_receiver":
                    position_files = rinex_files
                    self._logger.warning(
                        "receiver_position_mode='per_receiver': using %s's own "
                        "position (breaks direct SNR comparability)",
                        receiver_name,
                    )
                else:
                    position_files = (
                        self._get_rinex_files(position_data_dir, reader_format)
                        if position_data_dir
                        else rinex_files
                    )
                t_pos_start = time.perf_counter()
                receiver_position = self._compute_receiver_position(
                    position_files, receiver_name, reader_format=reader_format
                )
                t_pos_end = time.perf_counter()
                self._logger.info(
                    "position_computed",
                    receiver=receiver_name,
                    position_seconds=round(t_pos_end - t_pos_start, 4),
                    success=receiver_position is not None,
                )
                if receiver_position is None:
                    continue
                canopy_positions[receiver_name] = receiver_position
                receiver_file_map.append((receiver_name, rinex_files))

            if not canopy_positions:
                continue

            effective_reader = reader_format or self._reader_name
            reference_lane_key = f"reference:{data_dir.yyyydoy}"
            for rnx_file in rinex_files:
                task_descriptors.append(
                    _task_args(
                        preprocess_reference_with_hermite_aux_fanout,
                        is_reference_fanout=True,
                        rnx_file=rnx_file,
                        keep_vars=keep_vars,
                        aux_zarr_path=aux_zarr_path,
                        canopy_positions=canopy_positions,
                        receiver_type=reference_lane_key,
                        keep_sids=self.keep_sids,
                        reader_name=effective_reader,
                        store_radial_distance=store_radial_distance,
                        store_sbf_raw_observables=store_sbf_raw_observables,
                        aux_group=aux_group,
                        rinex_v3_parser=rinex_v3_parser,
                        aggregate_glonass_fdma=aggregate_glonass_fdma,
                        date_key=self.matched_data_dirs.yyyydoy.to_str(),
                    )
                )

        t_batch_end = time.perf_counter()
        self._logger.info(
            "prepare_batch_tasks_complete",
            date=date_str,
            total_seconds=round(t_batch_end - t_batch_start, 2),
            aux_seconds=round(t_aux_done - t_batch_start, 2),
            receivers_prepared=len(receiver_file_map),
            total_tasks=len(task_descriptors),
        )
        return task_descriptors, receiver_file_map

    def parsed_rinex_data_gen(
        self,
        keep_vars: list[str] | None = None,
        receiver_configs: list[tuple[str, str, ReceiverDay]]
        | list[tuple[str, str, ReceiverDay, ReceiverDay | None]]
        | list[tuple[str, str, ReceiverDay, ReceiverDay | None, str]]
        | None = None,
    ) -> Generator[tuple[str, xr.Dataset, float]]:
        """Generate datasets from RINEX files and append to Icechunk stores.

        Pipeline:
        1. Preprocess aux data ONCE per day with Hermite splines → Zarr
        2. For each receiver:
        a. Compute receiver position (from own files or position_data_dir)
        b. Parallel process RINEX files via ProcessPoolExecutor
        c. Append to Icechunk store with receiver_name as group
        d. Yield final daily dataset

        Parameters
        ----------
        keep_vars : list[str], optional
            Variables to keep in datasets (default: from globals)
        receiver_configs : list[tuple], optional
            List of (receiver_name, receiver_type, data_dir),
            (receiver_name, receiver_type, data_dir, position_data_dir), or
            (receiver_name, receiver_type, data_dir, position_data_dir, reader_format)
            tuples.
            When position_data_dir is provided, the receiver position is
            computed from files in that directory instead of data_dir.
            If None, uses default behavior with matched_data_dirs.

        Yields
        ------
        xr.Dataset
            Processed and augmented daily dataset for each receiver

        """
        if receiver_configs is None:
            receiver_configs = self._get_default_receiver_configs()

        # Normalize to 5-tuples
        normalized_configs: list[
            tuple[str, str, ReceiverDay, ReceiverDay | None, str]
        ] = []
        for cfg in receiver_configs:
            if len(cfg) == 3:
                normalized_configs.append((*cfg, None, self._reader_name))
            elif len(cfg) == 4:
                normalized_configs.append((*cfg, self._reader_name))
            else:
                normalized_configs.append(cfg)

        if keep_vars is None:
            keep_vars = self._config.processing.params.keep_gnss_observables

        pipeline_start = time.perf_counter()
        self._logger.info(
            "rinex_pipeline_started",
            receivers=len(normalized_configs),
            date=self.matched_data_dirs.yyyydoy.to_str(),
            keep_vars=keep_vars,
        )

        # ====================================================================
        # STEP 1: Preprocess aux data ONCE per day with Hermite splines
        # ====================================================================
        # Get first receiver files to infer sampling rate
        first_receiver_name, _first_receiver_type, first_data_dir, _, first_fmt = (
            normalized_configs[0]
        )
        first_files = self._get_rinex_files(first_data_dir, first_fmt)

        if not first_files:
            msg = (
                f"No RINEX files found for {first_receiver_name} - "
                "cannot infer sampling rate"
            )
            self._logger.error(
                "pipeline_failed",
                reason="no_rinex_files",
                receiver=first_receiver_name,
            )
            raise ValueError(msg)

        date_str = self.matched_data_dirs.yyyydoy.to_str()
        if self.use_sbf_geometry:
            aux_zarr_path = None
            aux_group = None
        else:
            aux_zarr_path, aux_group = self._ensure_aux_data_preprocessed(
                first_files, date_str, reader_format=first_fmt
            )

        # ====================================================================
        # PHASE 0.5 — file discovery upfront (one pass, keyed by (dir, fmt))
        # ====================================================================
        files_by_dir: dict = {}
        skipped: set = set()

        assert len({c[0] for c in normalized_configs}) == len(normalized_configs), (
            "Duplicate receiver names in normalized_configs"
        )

        for name, rtype, data_dir, pos_dir, fmt in normalized_configs:
            key = (data_dir, fmt)
            if key not in files_by_dir:
                files_by_dir[key] = self._get_rinex_files(data_dir, fmt)
            if not files_by_dir[key]:
                self._logger.warning(
                    "no_rinex_files_found",
                    receiver=name,
                    data_dir=str(data_dir),
                    reader_format=fmt,
                )
                skipped.add(name)

        # ====================================================================
        # PHASE 1 — resolve all receiver positions upfront
        # ====================================================================
        active_configs = [c for c in normalized_configs if c[0] not in skipped]
        # Build position-source files dict (may include position_data_dir entries)
        pos_files: dict = dict(files_by_dir)
        for name, rtype, data_dir, position_data_dir, fmt in active_configs:
            if position_data_dir is not None:
                key = (position_data_dir, fmt)
                if key not in pos_files:
                    pos_files[key] = self._get_rinex_files(position_data_dir, fmt)

        positions = self._resolve_receiver_positions(active_configs, pos_files)
        for name, pos in positions.items():
            if pos is None:
                skipped.add(name)

        # ====================================================================
        # PHASE 2 — parallel RINEX compute
        # ====================================================================
        wave_a, wave_b, parse_owner = self._build_compute_waves(
            normalized_configs, skipped
        )

        total_cores = self.n_max_workers or os.cpu_count() or 1
        outer_workers = min(len(wave_a), total_cores) if wave_a else 1
        inner_workers = max(1, total_cores // max(1, outer_workers))

        per_receiver_results: dict = {}  # name -> (augmented, aux_datasets, sid_issues)
        compute_durations: dict = {}  # name -> float (seconds)
        failed_dirs: set = set()

        def _parse_job(job_name, data_dir, fmt):
            t = time.perf_counter()
            result = self._parallel_process_rinex(
                rinex_files=files_by_dir[(data_dir, fmt)],
                keep_vars=keep_vars,
                aux_zarr_path=aux_zarr_path,  # ty: ignore[invalid-argument-type]
                receiver_position=positions[job_name],
                receiver_type=job_name,
                reader_format=fmt,
                show_progress=(len(wave_a) == 1),
                pool_workers=inner_workers if len(wave_a) > 1 else None,
                aux_group=aux_group,
            )
            return result, time.perf_counter() - t

        # Wave A: parse (one job per unique data_dir)
        if len(wave_a) <= 1:
            # Single receiver — run inline, full pool width, progress bar on
            for name, data_dir, fmt in wave_a:
                self._logger.info(
                    "receiver_processing_started",
                    receiver=name,
                    receiver_type="canopy",
                    data_dir=str(data_dir),
                )
                try:
                    (aug, aux_ds, sid_iss), dur = _parse_job(name, data_dir, fmt)
                    per_receiver_results[name] = (aug, aux_ds, sid_iss)
                    compute_durations[name] = dur
                except Exception as e:
                    self._logger.error(
                        "receiver_parse_failed",
                        receiver=name,
                        error=str(e),
                    )
                    failed_dirs.add((data_dir, fmt))
        else:
            with ThreadPoolExecutor(max_workers=outer_workers) as tpe:
                futs = {}
                for name, data_dir, fmt in wave_a:
                    self._logger.info(
                        "receiver_processing_started",
                        receiver=name,
                        receiver_type="parallel",
                        data_dir=str(data_dir),
                    )
                    futs[tpe.submit(_parse_job, name, data_dir, fmt)] = (
                        name,
                        data_dir,
                        fmt,
                    )
                for fut in as_completed(futs):
                    name, data_dir, fmt = futs[fut]
                    try:
                        (aug, aux_ds, sid_iss), dur = fut.result()
                        per_receiver_results[name] = (aug, aux_ds, sid_iss)
                        compute_durations[name] = dur
                    except Exception as e:
                        self._logger.error(
                            "receiver_parse_failed",
                            receiver=name,
                            error=str(e),
                        )
                        failed_dirs.add((data_dir, fmt))

        # Mark all receivers whose dir failed
        for name, rtype, data_dir, _pos, fmt in normalized_configs:
            if (data_dir, fmt) in failed_dirs and name not in skipped:
                skipped.add(name)

        # Wave B: SCS recompute from cached parse results
        recompute_jobs = [
            (name, data_dir, fmt)
            for name, data_dir, fmt in wave_b
            if name not in skipped and (data_dir, fmt) not in failed_dirs
        ]
        if recompute_jobs:

            def _recompute_job(job_name, data_dir, fmt):
                owner = parse_owner[(data_dir, fmt)]
                cached_aug, _, _ = per_receiver_results[owner]
                self._logger.info(
                    "recomputing_scs_from_cache",
                    receiver=job_name,
                    cached_files=len(cached_aug),
                    new_position=str(positions[job_name]),
                )
                t = time.perf_counter()
                result = self._recompute_scs_for_position(
                    cached_aug, aux_zarr_path, positions[job_name]
                )
                return result, time.perf_counter() - t

            if len(recompute_jobs) <= 1:
                for name, data_dir, fmt in recompute_jobs:
                    try:
                        aug, dur = _recompute_job(name, data_dir, fmt)
                        per_receiver_results[name] = (aug, None, None)
                        compute_durations[name] = dur
                    except Exception as e:
                        self._logger.error(
                            "scs_recompute_failed",
                            receiver=name,
                            error=str(e),
                        )
                        skipped.add(name)
            else:
                with ThreadPoolExecutor(
                    max_workers=min(len(recompute_jobs), total_cores)
                ) as tpe:
                    futs = {
                        tpe.submit(_recompute_job, n, d, f): (n, d, f)
                        for n, d, f in recompute_jobs
                    }
                    for fut in as_completed(futs):
                        name, data_dir, fmt = futs[fut]
                        try:
                            aug, dur = fut.result()
                            per_receiver_results[name] = (aug, None, None)
                            compute_durations[name] = dur
                        except Exception as e:
                            self._logger.error(
                                "scs_recompute_failed",
                                receiver=name,
                                error=str(e),
                            )
                            skipped.add(name)

        # processing.preprocessing (if set) on each receiver-day, after the
        # SCS recompute above (which needs the unprocessed observations)
        preprocessing = self._config.processing.preprocessing
        for name, (aug, aux_ds, sid_iss) in per_receiver_results.items():
            for fname, ds in aug:
                _warn_if_epoch_count_differs_from_name(
                    self._logger, fname, self._canonical_name(fname), ds
                )
            per_receiver_results[name] = (
                preprocess_files(aug, preprocessing),
                aux_ds,
                sid_iss,
            )

        # ====================================================================
        # PHASE 3 — writes + yields
        # ====================================================================
        # "overwrite" keeps the sequential per-group loop: each receiver is
        # staged on a temp branch and promoted with
        # `MyIcechunkStore.promote_branch` (refused if main moved meanwhile).
        # "skip"/"unsafe_append" go
        # through the cross-group fork/merge batch write instead: one
        # ThreadPoolExecutor dispatch + one shared commit for the whole
        # batch, rather than one sequential commit per group.
        date_obj = self.matched_data_dirs.yyyydoy.date
        assert date_obj is not None, "yyyydoy.date must not be None"
        start_time = datetime.combine(date_obj, datetime.min.time())
        end_time = datetime.combine(date_obj, datetime.max.time())
        time_range = (start_time, end_time)

        n_written = 0

        if self._gnss_store_strategy == "overwrite":
            for name, rtype, data_dir, _pos, fmt in normalized_configs:
                if name in skipped:
                    continue
                augmented, aux_datasets, sid_issues = per_receiver_results[name]
                rinex_files = files_by_dir[(data_dir, fmt)]

                t_write_start = time.perf_counter()
                self._append_to_icechunk(
                    augmented_datasets=augmented,
                    receiver_name=name,
                    rinex_files=rinex_files,
                    aux_datasets=aux_datasets,
                    sid_issues=sid_issues,
                    reader_format=fmt,
                )
                t_write_end = time.perf_counter()

                t_read_start = time.perf_counter()
                daily_dataset = self.site.read_receiver_data(
                    receiver_name=name, time_range=time_range
                )
                t_read_end = time.perf_counter()

                compute_s = compute_durations.get(name, 0.0)
                total_s = (
                    compute_s
                    + (t_write_end - t_write_start)
                    + (t_read_end - t_read_start)
                )
                self._logger.info(
                    "receiver_processing_complete",
                    receiver=name,
                    total_seconds=round(total_s, 2),
                    rinex_parallel_seconds=round(compute_s, 2),
                    icechunk_write_seconds=round(t_write_end - t_write_start, 2),
                    store_readback_seconds=round(t_read_end - t_read_start, 2),
                    dataset_size=dict(daily_dataset.sizes),
                    epochs=(
                        len(daily_dataset.epoch) if "epoch" in daily_dataset.dims else 0
                    ),
                )
                n_written += 1
                yield name, daily_dataset, total_s

        else:  # "skip" or "unsafe_append"
            group_inputs = []
            rinex_files_by_name: dict[str, list[Path]] = {}
            for name, rtype, data_dir, _pos, fmt in normalized_configs:
                if name in skipped:
                    continue
                augmented, aux_datasets, sid_issues = per_receiver_results[name]
                rinex_files = files_by_dir[(data_dir, fmt)]
                rinex_files_by_name[name] = rinex_files
                group_inputs.append(
                    (name, augmented, rinex_files, aux_datasets, sid_issues, fmt)
                )

            t_batch_start = time.perf_counter()
            results: dict[str, GroupWriteResult] = {}
            if group_inputs:
                results = self._write_receiver_batch_forked(group_inputs)
            t_batch_end = time.perf_counter()
            self._logger.info(
                "cross_group_batch_write_complete",
                date=self.matched_data_dirs.yyyydoy.to_str(),
                groups=list(results),
                duration_seconds=round(t_batch_end - t_batch_start, 2),
            )

            for name, rtype, data_dir, _pos, fmt in normalized_configs:
                if name in skipped or name not in results:
                    continue

                t_read_start = time.perf_counter()
                daily_dataset = self.site.read_receiver_data(
                    receiver_name=name, time_range=time_range
                )
                t_read_end = time.perf_counter()

                compute_s = compute_durations.get(name, 0.0)
                write_s = results[name].duration_seconds
                total_s = compute_s + write_s + (t_read_end - t_read_start)
                self._logger.info(
                    "receiver_processing_complete",
                    receiver=name,
                    total_seconds=round(total_s, 2),
                    rinex_parallel_seconds=round(compute_s, 2),
                    icechunk_write_seconds=round(write_s, 2),
                    store_readback_seconds=round(t_read_end - t_read_start, 2),
                    dataset_size=dict(daily_dataset.sizes),
                    epochs=(
                        len(daily_dataset.epoch) if "epoch" in daily_dataset.dims else 0
                    ),
                )
                n_written += 1
                yield name, daily_dataset, total_s

        self._logger.info(
            "rinex_pipeline_complete",
            date=self.matched_data_dirs.yyyydoy.to_str(),
            receivers_written=n_written,
            receivers_skipped=len(skipped),
        )

    def _get_default_receiver_configs(
        self,
    ) -> list[tuple[str, str, ReceiverDay, ReceiverDay | None]]:
        """Get default receiver configs for the day of matched_data_dirs.

        Returns a list of (store_group_name, receiver_type, day,
        position_day) tuples. For canopy receivers, position_day is None
        (use own files). For reference receivers, one entry is created per
        paired canopy, with position_day the canopy's same day.

        Returns
        -------
        list[tuple[str, str, ReceiverDay, ReceiverDay | None]]
            Receiver processing configurations.
        """
        configs: list[tuple[str, str, ReceiverDay, ReceiverDay | None]] = []
        site_config = self.site._site_config
        base_path = site_config.get_base_path()
        date_key = self.matched_data_dirs.yyyydoy.to_str()

        def _day(name: str) -> ReceiverDay:
            cfg = site_config.receivers[name]
            return ReceiverDay(
                name,
                base_path / cfg.directory,
                date_key,
                recipe_file(self.site.site_name, cfg.recipe),
            )

        canopy_days = {
            name: _day(name)
            for name, cfg in site_config.receivers.items()
            if cfg.type == "canopy"
        }

        # Add all canopy receivers (each uses own position)
        for name, day in canopy_days.items():
            configs.append((name, "canopy", day, None))

        # Add reference receivers — one entry per canopy in paired_canopies
        for name, cfg in site_config.receivers.items():
            if cfg.type != "reference":
                continue
            ref_day = _day(name)
            for canopy_name in site_config.resolve_paired_canopies(name):
                store_group = reference_store_group(name, canopy_name)
                configs.append(
                    (store_group, "reference", ref_day, canopy_days.get(canopy_name))
                )

        return configs

    def should_skip_day(
        self,
        receiver_types: list[str] | None = None,
        completeness_threshold: float = 1,
    ) -> tuple[bool, dict]:
        """Check if this day should be skipped based on existing data coverage.

        Parameters
        ----------
        receiver_types : list[str], optional
            Receiver types to check. Defaults to ['canopy', 'reference']
        completeness_threshold : float
            Fraction of expected epochs (default 0.95 = 95%)

        Returns
        -------
        tuple[bool, dict]
            (should_skip, coverage_info) where coverage_info contains details
            per receiver.

        """
        if receiver_types is None:
            receiver_types = ["canopy", "reference"]

        # Expected epochs for 24h at 30s sampling
        expected_epochs = int(24 * 3600 / 30)  # 2880
        required_epochs = int(expected_epochs * completeness_threshold)

        # Get datetime objects from YYYYDOY.date
        yyyydoy_date = self.matched_data_dirs.yyyydoy.date
        assert yyyydoy_date is not None, "yyyydoy.date must not be None"
        day_start = np.datetime64(
            datetime.combine(yyyydoy_date, dt_time.min),
            "ns",
        )
        day_end = np.datetime64(
            datetime.combine(yyyydoy_date, dt_time.max),
            "ns",
        )

        coverage_info = {}

        for receiver_type in receiver_types:
            # Get receiver name
            receiver_name = None
            for name, config in self.site.active_receivers.items():
                if config.get("type") == receiver_type:
                    receiver_name = name
                    break

            if not receiver_name:
                coverage_info[receiver_type] = {
                    "exists": False,
                    "reason": "No receiver configured",
                }
                return False, coverage_info

            try:
                # Read metadata table
                with self.site.gnss_store.readonly_session("main") as session:
                    zmeta = zarr.open_group(session.store, mode="r")[
                        f"{receiver_name}/metadata/table"
                    ]
                    data = {col: zmeta[col][:] for col in zmeta.array_keys()}  # ty: ignore[invalid-argument-type, not-subscriptable, unresolved-attribute]
                    df = pl.DataFrame(data)

                # Cast datetime columns
                df = df.with_columns(
                    [
                        pl.col("start").cast(pl.Datetime("ns")),
                        pl.col("end").cast(pl.Datetime("ns")),
                    ]
                )

                # Filter to this day
                day_rows = df.filter(
                    (pl.col("start") >= day_start) & (pl.col("end") <= day_end)  # ty: ignore[invalid-argument-type]
                )

                if day_rows.is_empty():
                    coverage_info[receiver_type] = {
                        "exists": False,
                        "epochs": 0,
                        "expected": expected_epochs,
                        "percent": 0.0,
                    }
                    return False, coverage_info

                # Calculate total epochs
                day_rows = day_rows.with_columns(
                    [
                        (
                            (pl.col("end") - pl.col("start")).dt.total_seconds() / 30
                        ).alias("n_epochs")
                    ]
                )

                total_epochs = int(day_rows["n_epochs"].sum())
                percent = total_epochs / expected_epochs * 100

                coverage_info[receiver_type] = {
                    "exists": True,
                    "epochs": total_epochs,
                    "expected": expected_epochs,
                    "percent": percent,
                    "complete": total_epochs >= required_epochs,
                }

                if total_epochs < required_epochs:
                    return False, coverage_info

            except (KeyError, OSError, RuntimeError, ValueError) as e:
                coverage_info[receiver_type] = {
                    "exists": False,
                    "reason": str(e),
                    "epochs": 0,
                    "expected": expected_epochs,
                    "percent": 0.0,
                }
                return False, coverage_info

        # All receivers are complete
        return True, coverage_info

    def __repr__(self) -> str:
        return (
            "RinexDataProcessor("
            f"date={self.matched_data_dirs.yyyydoy.to_str()}, "
            f"site={self.site.site_name}, "
            f"aux_pipeline={self.aux_pipeline})"
        )


@deprecated(
    "DistributedRinexDataProcessor is left over from development and will be removed with the next major version. "
    "It was never finished. Use canvodpy.Site(<site>).pipeline() instead."
)
class DistributedRinexDataProcessor(RinexDataProcessor):
    """Under development. Use with caution.

    In `MyIcechunkStore`, attrs `MyIcechunkStore.compression_algorithm` and
    `MyIcechunkStore.config` must be disabled, so that any instance becomes
    serializable.

    Subclass of RinexDataProcessor that uses cooperative distributed writing.

    See:
        https://icechunk.io/en/latest/parallel/#cooperative-distributed-writes

    """

    def __init__(
        self,
        matched_data_dirs: MatchedDirs,
        site: GnssResearchSite,
        aux_file_path: Path | None = None,
        n_max_workers: int = 12,
    ) -> None:
        super().__init__(matched_data_dirs, site, aux_file_path, n_max_workers)

    def __repr__(self) -> str:
        return (
            "DistributedRinexDataProcessor("
            f"date={self.matched_data_dirs.yyyydoy.to_str()}, "
            f"site={self.site.site_name}, "
            f"aux_pipeline={self.aux_pipeline})"
        )

    def _cooperative_distributed_writing(
        self,
        rinex_files: list[Path],
        keep_vars: list[str],
        aux_zarr_path: Path,
        receiver_position: ECEFPosition,
        receiver_type: str,
        receiver_name: str,
    ) -> list[Path]:
        version = get_version_from_pyproject()
        self._ensure_gnss_store_metadata([receiver_name], self._reader_name)
        repo = self.site.gnss_store.repo
        rinex_files_sorted = sorted(rinex_files, key=lambda p: p.name)

        # STEP 1: Initialize dataset structure with ALL files' time coordinates
        # This creates the full epoch dimension upfront
        session = repo.writable_session("main")

        # Collect all epochs from all files (or create empty structure)
        # Option A: Process all files first to get full time range
        all_epochs = []
        store_raw = self._config.processing.params.store_sbf_raw_observables
        for rinex_file in rinex_files_sorted:
            _fname, ds, _aux, _sids = preprocess_with_hermite_aux(
                rinex_file,
                keep_vars,
                aux_zarr_path,
                receiver_position,
                receiver_type,
                self.keep_sids,
                self._reader_name,
                store_sbf_raw_observables=store_raw,
            )
            all_epochs.extend(ds.epoch.values)

        # Create empty dataset with full structure
        _first_fname, first_ds, _aux, _sids = preprocess_with_hermite_aux(
            rinex_files_sorted[0],
            keep_vars,
            aux_zarr_path,
            receiver_position,
            receiver_type,
            self.keep_sids,
            self._reader_name,
            store_sbf_raw_observables=store_raw,
        )

        # Initialize with full epoch dimension
        empty_ds = first_ds.isel(epoch=[]).expand_dims({"epoch": len(all_epochs)})
        empty_ds = empty_ds.assign_coords({"epoch": np.sort(all_epochs)})

        to_icechunk(
            prepare_write(empty_ds, session.store, receiver_name, append_dim=None),
            session,
            group=receiver_name,
            mode="w",
        )
        commit_with_rebase(
            session,
            _with_run_id(f"Initialize {receiver_name} structure"),
            store_path=self.site.gnss_store.store_path,
            config=self._config,
        )

        # STEP 2: Now do cooperative distributed writes
        session = repo.writable_session("main")
        fork = session.fork()  # ONE fork

        remote_sessions = []

        self._logger.info(
            "cooperative_writing_started",
            executor_type="ProcessPoolExecutor",
            files=len(rinex_files_sorted),
        )
        _res2 = self._config.processing.params.resolve_resources()
        with ProcessPoolExecutor(
            max_workers=self.n_max_workers,
            initializer=_worker_init_with_run_id,
            initargs=(
                _res2["nice_priority"],
                _res2["cpu_affinity"],
                get_run_id(),
                active_log_dir(),
            ),
        ) as ex:
            futures = [
                ex.submit(
                    worker_task_with_region_auto,
                    rinex_file,
                    keep_vars,
                    aux_zarr_path,
                    receiver_position,
                    receiver_type,
                    receiver_name,
                    fork,
                    self.keep_sids,
                    self._reader_name,
                    store_raw,
                )
                for rinex_file in rinex_files_sorted
            ]

            yyyydoy = self.matched_data_dirs.yyyydoy.to_str()
            desc = f"{yyyydoy} Writing {receiver_name}"
            with _processing_progress() as progress:
                task = progress.add_task(desc, total=len(futures))
                for fut in as_completed(futures):
                    try:
                        returned_fork = fut.result()
                    except BrokenProcessPool as e:
                        self._logger.error(
                            "worker_pool_broken",
                            receiver=receiver_name,
                            error=str(e),
                            hint="worker process likely killed by OOM or segfault",
                        )
                        raise
                    except Exception as e:
                        self._logger.error(
                            "worker_task_failed",
                            receiver=receiver_name,
                            error=str(e),
                            exception=type(e).__name__,
                        )
                        raise
                    remote_sessions.append(returned_fork)
                    progress.advance(task)

        # Merge all remote sessions
        session.merge(*remote_sessions)
        _snapshot_id = commit_with_rebase(
            session,
            _with_run_id(f"[v{version}] Cooperative write for {receiver_name}"),
            store_path=self.site.gnss_store.store_path,
            config=self._config,
        )

        return [f.name for f in rinex_files_sorted]  # ty: ignore[invalid-return-type]

    @deprecated(
        "parsed_rinex_data_gen_parallel() is left over from development and will be removed with the next major version. "
        "Use canvodpy.Site(<site>).pipeline() instead."
    )
    def parsed_rinex_data_gen_parallel(
        self,
        keep_vars: list[str] | None = None,
        receiver_types: list[str] | None = None,
    ) -> Generator[xr.Dataset]:
        """Generate datasets from RINEX files and append to Icechunk stores.

        Pipeline:
        1. Preprocess aux data ONCE per day with Hermite splines → Zarr
        2. Compute receiver position ONCE (shared for all receivers)
        3. For each receiver type (canopy, reference):
           a. Get list of RINEX files
           b. Parallel process via ProcessPoolExecutor
           c. Each worker: read RINEX + slice Zarr + compute φ, θ, r
           d. Sequential append to Icechunk store
           e. Yield final daily dataset

        Parameters
        ----------
        keep_vars : List[str], optional
            Variables to keep in datasets (default: from globals)
        receiver_types : List[str], optional
            Receiver types to process (default: ['canopy', 'reference'])

        Yields
        ------
        xr.Dataset
            Processed and augmented daily dataset for each receiver type

        """
        if receiver_types is None:
            receiver_types = ["canopy", "reference"]

        if keep_vars is None:
            keep_vars = self._config.processing.params.keep_gnss_observables

        self._logger.info(
            "Starting RINEX processing pipeline for: %s",
            receiver_types,
        )

        # Pre-flight: Get canopy files to infer sampling and compute position
        canopy_dir = self.matched_data_dirs.canopy_data_dir
        canopy_files = self._get_rinex_files(canopy_dir)
        if not canopy_files:
            msg = "No canopy RINEX files found - cannot infer sampling rate"
            raise ValueError(msg)

        # ====================================================================
        # STEP 1: Preprocess aux data ONCE per day with Hermite splines
        # ====================================================================
        import shutil as _shutil

        _aux_base_dir = self._config.processing.storage.get_aux_data_dir()
        aux_zarr_path = _aux_base_dir / (
            f"aux_{self.matched_data_dirs.yyyydoy.to_str()}.zarr"
        )

        # Always reprocess from raw SP3/CLK files to avoid stale SID caches
        if aux_zarr_path.exists():
            _shutil.rmtree(aux_zarr_path)

        self._logger.info("Preprocessing aux data with Hermite splines (once per day)")
        _sampling_interval = self._preprocess_aux_data_with_hermite(
            canopy_files, aux_zarr_path
        )

        # ====================================================================
        # STEP 2: Compute receiver position
        # ====================================================================
        position_mode = self._config.processing.params.receiver_position_mode
        first_rnx = self._make_reader(canopy_files[0])
        first_ds = first_rnx.to_ds(keep_data_vars=[], write_global_attrs=True)
        shared_position = ECEFPosition.from_ds_metadata(first_ds)

        if position_mode == "per_receiver":
            self._logger.warning(
                "receiver_position_mode='per_receiver': each receiver will use "
                "its own RINEX header position. This breaks direct SNR "
                "comparability between receivers."
            )
        else:
            self._logger.info(
                "Computed receiver position (shared): %s",
                shared_position,
            )

        # ====================================================================
        # STEP 3: Process each receiver type
        # ====================================================================
        for receiver_type in receiver_types:
            self._logger.info("Processing receiver type: %s", receiver_type)

            # 3a. Resolve directories and receiver name
            rinex_dir, receiver_name = self._resolve_receiver_paths(receiver_type)

            if not receiver_name:
                self._logger.warning(
                    "No configured receiver for %s, skipping",
                    receiver_type,
                )
                continue

            # 3b. Get RINEX files for this receiver type
            rinex_files = self._get_rinex_files(rinex_dir)
            if not rinex_files:
                self._logger.warning(
                    "No RINEX files found in %s",
                    rinex_dir,
                )
                continue

            self._logger.info(
                "Found %s RINEX files to process",
                len(rinex_files),
            )

            # 3b'. Determine receiver position for this receiver
            if position_mode == "per_receiver":
                receiver_position = self._compute_receiver_position(
                    rinex_files, receiver_name
                )
                if receiver_position is None:
                    self._logger.error(
                        "Could not compute position for %s, skipping",
                        receiver_name,
                    )
                    continue
            else:
                receiver_position = shared_position

            # 3c. Parallel process via ProcessPoolExecutor
            _ = self._cooperative_distributed_writing(
                rinex_files=rinex_files,
                keep_vars=keep_vars,
                aux_zarr_path=aux_zarr_path,
                receiver_position=receiver_position,
                receiver_type=receiver_type,
                receiver_name=receiver_name,
            )

            # 3e. Yield final daily dataset
            # Read back from store to get complete daily dataset
            date_obj = self.matched_data_dirs.yyyydoy.date
            assert date_obj is not None, "yyyydoy.date must not be None"
            start_time = datetime.combine(date_obj, datetime.min.time())
            end_time = datetime.combine(date_obj, datetime.max.time())
            time_range = (start_time, end_time)

            daily_dataset = self.site.read_receiver_data(
                receiver_name=receiver_name, time_range=time_range
            )

            self._logger.info(
                "Yielding daily dataset for %s ('%s'): %s",
                receiver_type,
                receiver_name,
                dict(daily_dataset.sizes),
            )

            yield daily_dataset


if __name__ == "__main__":
    print(f"stared main block at {datetime.now(UTC)}")
    cfg = load_config()

    matcher = DataDirMatcher(
        root=Path("."),
        reference_pattern=Path("01_reference/01_GNSS/01_raw"),
        canopy_pattern=Path("02_canopy/01_GNSS/01_raw"),
    )

    site = GnssResearchSite(site_name="ExampleSite")

    stats = {"processed": 0, "skipped": 0, "failed": 0}

    for md in matcher:
        yyyydoy_str = md.yyyydoy.to_str()

        if yyyydoy_str != "2024258":
            continue

        try:
            print(f"instantiating processor for {yyyydoy_str}: {datetime.now(UTC)}")
            # Create processor first to check completeness
            processor = RinexDataProcessor(
                matched_data_dirs=md, site=site, n_max_workers=12, config=cfg
            )

            # Check if should skip
            if processor._gnss_store_strategy in ["skip", "unsafe_append"]:
                should_skip, coverage = processor.should_skip_day()

                if should_skip:
                    print(f"✓ Skipping {yyyydoy_str} - already complete:")
                    for receiver_type, info in coverage.items():
                        print(
                            f"  {receiver_type}: {info['epochs']}/"
                            f"{info['expected']} ({info['percent']:.1f}%)"
                        )
                    stats["skipped"] += 1
                    continue
                else:
                    print(f"⚠ Processing {yyyydoy_str} - incomplete coverage:")
                    for receiver_type, info in coverage.items():
                        if info["exists"]:
                            print(
                                f"  {receiver_type}: {info['epochs']}/"
                                f"{info['expected']} ({info['percent']:.1f}%)"
                            )
                        else:
                            print(f"  {receiver_type}: No data")

            # Process data
            print(
                f"about to call parsed_rinex_data_gen for {yyyydoy_str}: "
                f"{datetime.now(UTC)}"
            )
            data_generator = processor.parsed_rinex_data_gen()
            print(f"calling next for canopy: {datetime.now(UTC)}")
            canopy_ds = next(data_generator)
            print(f"calling next for reference: {datetime.now(UTC)}")
            reference_ds = next(data_generator)

            stats["processed"] += 1
            print(f"✓ Processed {yyyydoy_str}")

        except (OSError, RuntimeError, ValueError) as e:
            print(f"✗ Failed {yyyydoy_str}: {e}")
            stats["failed"] += 1
