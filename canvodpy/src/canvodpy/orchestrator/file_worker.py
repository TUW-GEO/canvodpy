"""Reading one file in a worker process: the reader, satellite geometry, checks.

The tasks of a run (:mod:`canvodpy.orchestrator.processor`, the forked day
writes of :mod:`canvodpy.orchestrator.forked_writes`, the Airflow tasks)
read each file through :func:`preprocess_with_hermite_aux`, or
:func:`preprocess_reference_with_hermite_aux_fanout` for a reference
receiver shared by several canopies. The functions are at module level so
the worker pool can pickle them.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import numpy as np
import structlog
import xarray as xr
from pydantic import ValidationError

from canvod.auxiliary.interpolation import create_interpolator_from_attrs
from canvod.auxiliary.position import (
    ECEFPosition,
    add_spherical_coords_to_dataset,
    compute_spherical_coordinates,
)
from canvod.auxiliary.preprocessing import aux_for_sids
from canvod.readers.gnss_specs.exceptions import NmeaError, RinexError
from canvod.store.prepare import NO_POSITION_ATTR, ORBIT_INTERPOLATION_ATTR
from canvod.utils.logging import record_stage_timing, set_run_id, stage_timer
from canvod.utils.tools import _worker_init
from canvodpy.logging.logging_config import configure_logging


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


def _open_aux_store(aux_zarr_path: Path, group: str | None = None) -> xr.Dataset:
    """Open the auxiliary store with every variable as stored.

    ``clock_offset`` is a float in seconds (CF ``units: seconds``). xarray
    would decode it to ``timedelta64[ns]`` with ``decode_timedelta=True``,
    rounding the clock to the nanosecond and casting its NaN through
    int64; ``ephemeris/provider.py`` opens the same store the same way.
    """
    return xr.open_zarr(
        aux_zarr_path, group=group, decode_timedelta=False, consolidated=False
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
            ds.attrs[SOURCE_FORMAT_ATTR] = rnx.source_format
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
                observations = ds
                ds = provider.augment_dataset(
                    ds, receiver_position, aux_datasets=aux_datasets
                )
                ds.attrs[NO_POSITION_ATTR] = json.dumps(
                    satellites_without_position(observations, ds["theta"])
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
            aux_store = _open_aux_store(aux_zarr_path, group=aux_group)
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

            # Filter both datasets to common SIDs; the observations of the
            # signals without ephemeris are kept to report them (#571).
            observations = ds
            rinex_only = rinex_sids - aux_sids
            aux_only = aux_sids - rinex_sids
            ds = ds.sel(sid=common_sids)
            aux_slice = aux_for_sids(aux_slice, common_sids)
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
            # The angles are NaN where the satellite has no position, the
            # same for every receiver position.
            no_position = json.dumps(
                satellites_without_position(
                    observations, next(iter(ds_augmented.values()))["theta"]
                )
            )
            # How the orbits were interpolated, as the aux data record it
            orbit_interpolation = json.dumps(
                create_interpolator_from_attrs(aux_store.attrs).config.to_dict(),
                sort_keys=True,
            )
            for ds_name in ds_augmented.values():
                ds_name.attrs[NO_POSITION_ATTR] = no_position
                ds_name.attrs[ORBIT_INTERPOLATION_ATTR] = orbit_interpolation
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
    """Read RINEX and compute coordinates using the interpolated aux data from Zarr.

    This function runs in separate processes, so it must be at module level.
    The aux data has already been interpolated with the method set by ``sp3_interpolation``.

    Parameters
    ----------
    rnx_file : Path
        RINEX file path
    keep_vars : List[str]
        Variables to keep
    aux_zarr_path : Path
        Path to preprocessed aux data Zarr store
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
    # Get satellite positions (already interpolated onto the epoch grid)
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


#: Variables of an augmented dataset that are not observations.
_GEOMETRY_VARS = frozenset({"phi", "theta", "r", "clock"})


def satellites_without_position(
    observations: xr.Dataset, theta: xr.DataArray
) -> dict[str, int]:
    """Epochs per satellite with observations but no position (#571).

    A satellite has no position at an epoch when its polar angle is NaN:
    no ephemeris covers the epoch. Its angles stay NaN, never extrapolated.
    An epoch counts when any signal of the satellite has an observation (a
    finite value of any float variable over ``epoch`` and ``sid``).

    Parameters
    ----------
    observations : xr.Dataset
        The file's observations, with every signal the file has.
    theta : xr.DataArray
        The polar angle of the signals with ephemerides; a signal of
        ``observations`` missing here has no position at all.

    Returns
    -------
    dict[str, int]
        ``{satellite: epochs}``, sorted by satellite; empty when every
        observed satellite has a position.
    """
    observed = np.zeros((observations.sizes["epoch"], observations.sizes["sid"]), bool)
    for name, var in observations.data_vars.items():
        if (
            name in _GEOMETRY_VARS
            or set(var.dims) != {"epoch", "sid"}
            or not np.issubdtype(var.dtype, np.floating)
        ):
            continue
        observed |= np.isfinite(var.transpose("epoch", "sid").values)
    angles = theta.reindex(sid=observations.sid).transpose("epoch", "sid").values
    lacking = observed & np.isnan(angles)
    svs = np.asarray(observations["sv"].values).astype(str)
    return {
        str(sv): int(lacking[:, svs == sv].any(axis=1).sum())
        for sv in sorted(set(svs[lacking.any(axis=0)]))
    }


#: Dataset attribute naming the format of the reader that read the file
#: (``GNSSDataReader.source_format``); set by the worker, recorded by the
#: GNSS store as its ``source_format``.
SOURCE_FORMAT_ATTR = "Source Format"
