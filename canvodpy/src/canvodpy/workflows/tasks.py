"""Airflow-compatible task functions for GNSS daily processing pipeline.

Each function accepts only primitives (str, dict, list, None) and returns
JSON-serializable dicts suitable for XCom.  They delegate to existing
canvodpy machinery — no pipeline rewrite.

DAG topology::

    validate_dirs → check_day (→ wait_for_sp3 with agency ephemeris)
      → process_day → validate_ingest → calculate_vod

``process_day`` and ``calculate_vod`` run the same code as ``canvodpy run``.
"""

from __future__ import annotations

import datetime
import shutil
from pathlib import Path
from typing import Any

import numpy as np
import structlog
import xarray as xr

from canvod.auxiliary.interpolation import aux_epoch_grid, interpolate_aux_day
from canvod.auxiliary.pipeline import AuxDataPipeline
from canvod.auxiliary.position import ECEFPosition
from canvod.config import load_config
from canvod.config.models import reference_store_group
from canvod.ops import preprocess_files
from canvod.readers import MatchedDirs
from canvod.utils.tools import YYYYDOY, deprecated
from canvodpy.orchestrator.discovery import (
    DiscoveredFile,
    parse_sampling_interval_from_filename,
)

logger = structlog.get_logger(__name__)


def _cap_blas_threads(n: int = 1) -> None:
    """Set BLAS/OpenMP thread-cap env vars if not already set by the caller.

    Called at the start of CPU-heavy tasks so that numpy/scipy don't spawn
    os.cpu_count() threads per process.  Only sets vars that are absent,
    so an operator-level override (e.g. Airflow env) always wins.
    """
    import os

    s = str(n)
    for var in (
        "OMP_NUM_THREADS",
        "MKL_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
    ):
        if var not in os.environ:
            os.environ[var] = s


def _resolve_date(yyyydoy: str) -> YYYYDOY:
    """Accept ``YYYYDDD`` *or* Airflow ``ds`` (``YYYY-MM-DD``)."""
    if "-" in yyyydoy:
        return YYYYDOY.from_date(datetime.date.fromisoformat(yyyydoy))
    return YYYYDOY.from_str(yyyydoy)


def _day_files(
    site: str,
    site_cfg: Any,
    date_obj: YYYYDOY,
    reader_format: str | None,
) -> dict[str, list[DiscoveredFile]]:
    """The files of each receiver of *site* that a run processes for one day.

    Same discovery and the same receiver checks as ``canvodpy run`` (see
    :mod:`canvodpy.orchestrator.discovery`): the receiver's naming recipe if
    it has one, otherwise canonical canVOD names only, found anywhere below
    the receiver's directory by the date in their names.

    Parameters
    ----------
    site : str
        Site name in the configuration.
    site_cfg : SiteConfig
        The site's configuration.
    date_obj : YYYYDOY
        The day.
    reader_format : str | None
        ``"rinex3"`` or ``"sbf"`` to select one file type for all receivers,
        ``None`` for the ``reader_format`` configured for each receiver (as
        ``canvodpy run`` reads them; ``"auto"`` selects all types).

    Returns
    -------
    dict[str, list[DiscoveredFile]]
        Receiver name to its files of the day (empty if there are none).

    Raises
    ------
    DiscoveryError
        If the receivers' files cannot be assigned unambiguously.
    """
    from canvodpy.orchestrator.discovery import (
        ReceiverDay,
        check_receivers,
        clear_discovery_cache,
        discover_files,
        recipe_file,
    )

    base = site_cfg.get_base_path()
    # Files may have arrived since the previous task in this process.
    clear_discovery_cache()
    check_receivers(
        {name: rcfg.model_dump() for name, rcfg in site_cfg.receivers.items()},
        base,
        site,
    )
    return {
        name: discover_files(
            ReceiverDay(
                name,
                base / rcfg.directory,
                date_obj.to_str(),
                recipe_file(site, rcfg.recipe),
            ),
            reader_format if reader_format is not None else rcfg.reader_format,
        )
        for name, rcfg in site_cfg.receivers.items()
    }


def _store_groups(site_cfg: Any) -> list[str]:
    """Every GNSS store group of a site: canopy receivers and pair groups."""
    return [
        group
        for name, rcfg in site_cfg.receivers.items()
        for group in (
            [name]
            if rcfg.type == "canopy"
            else [
                reference_store_group(name, canopy)
                for canopy in site_cfg.resolve_paired_canopies(name)
            ]
        )
    ]


# ---------------------------------------------------------------------------
# Task 1 — check_day
# ---------------------------------------------------------------------------


def _warn_epoch_counts(
    processed: list[tuple[Path, xr.Dataset]], discovered: list | None
) -> None:
    """Compare each file's epochs with its canonical name, as a run does.

    ``discovered`` are the day's ``DiscoveredFile`` entries, which carry the
    canonical names of recipe files; without them the physical name is used.
    """
    from canvodpy.orchestrator.discovery import canonical_name_for
    from canvodpy.orchestrator.processor import (
        _warn_if_epoch_count_differs_from_name,
    )

    names = {f.path: f.canonical_name for f in discovered or []}
    for fpath, ds in processed:
        _warn_if_epoch_count_differs_from_name(
            logger, fpath, names.get(fpath) or canonical_name_for(fpath), ds
        )


def check_day(site: str, yyyydoy: str) -> dict:
    """Check whether every receiver has files for the given date.

    The files are those ``canvodpy run`` processes for the day (see
    :mod:`canvodpy.orchestrator.discovery`), in the ``reader_format``
    configured for each receiver: selected by the receiver's naming recipe
    or by canonical canVOD names, anywhere below the receiver's directory.

    Parameters
    ----------
    site : str
        Research site name (must exist in config).
    yyyydoy : str
        Date in ``YYYYDDD`` format **or** Airflow ``ds`` (``YYYY-MM-DD``).

    Returns
    -------
    dict
        ``{"site", "yyyydoy", "ready": True, "receivers": {name:
        {"directory", "has_files", "files", "count"}}}``

    Raises
    ------
    RuntimeError
        If files are missing for any receiver (stops the DAG run so Airflow
        can retry later).
    DiscoveryError
        If the receivers' files cannot be assigned unambiguously, e.g. two
        files cover the same time. Retrying does not help; the data
        directory has to be fixed.
    """
    return _check_files(site, yyyydoy, None, "GNSS")


def _check_files(site: str, yyyydoy: str, reader_format: str | None, kind: str) -> dict:
    """Shared body of :func:`check_day`, :func:`check_rinex` and :func:`check_sbf`."""
    config = load_config()
    site_cfg = config.sites.sites[site]
    date_obj = _resolve_date(yyyydoy)
    base = site_cfg.get_base_path()
    day_files = _day_files(site, site_cfg, date_obj, reader_format)

    receivers = {
        name: {
            "directory": str(base / rcfg.directory),
            "has_files": bool(day_files[name]),
            "files": [str(f.path) for f in day_files[name]],
            "count": len(day_files[name]),
        }
        for name, rcfg in site_cfg.receivers.items()
    }
    missing = [n for n, r in receivers.items() if not r["has_files"]]
    if missing:
        msg = (
            f"{kind} files not yet available for {site} {date_obj.to_str()}: "
            f"missing receivers {missing}"
        )
        logger.warning(msg)
        raise RuntimeError(msg)

    logger.info(
        "check_%s: %s %s, all receivers ready",
        kind.lower(),
        site,
        date_obj.to_str(),
    )
    return {
        "site": site,
        "yyyydoy": date_obj.to_str(),
        "ready": True,
        "receivers": receivers,
    }


@deprecated(
    "`check_rinex` is left over from development and will be removed with the next "
    "major version. Use `check_day` instead."
)
def check_rinex(site: str, yyyydoy: str) -> dict:
    """Check whether RINEX files exist for all receivers on the given date.

    The files are those ``canvodpy run`` would process for the day (see
    :mod:`canvodpy.orchestrator.discovery`): selected by the receiver's
    naming recipe or by canonical canVOD names, anywhere below the
    receiver's directory.

    Parameters
    ----------
    site : str
        Research site name (must exist in config).
    yyyydoy : str
        Date in ``YYYYDDD`` format **or** Airflow ``ds`` (``YYYY-MM-DD``).

    Returns
    -------
    dict
        ``{"site", "yyyydoy", "ready": True, "receivers": {name:
        {"directory", "has_files", "files", "count"}}}``

    Raises
    ------
    RuntimeError
        If RINEX files are missing for any receiver (stops the DAG run
        so Airflow can retry later).
    DiscoveryError
        If the receivers' files cannot be assigned unambiguously, e.g. two
        files cover the same time. Retrying does not help; the data
        directory has to be fixed.
    """
    return _check_files(site, yyyydoy, "rinex3", "RINEX")


@deprecated(
    "`check_sbf` is left over from development and will be removed with the next "
    "major version. Use `check_day` instead."
)
def check_sbf(site: str, yyyydoy: str) -> dict:
    """Check whether SBF files exist for all receivers on the given date.

    Same as :func:`check_rinex`, for SBF binary data. SBF files are
    available immediately after receiver transfer (no sensor wait needed).

    Parameters
    ----------
    site : str
        Research site name (must exist in config).
    yyyydoy : str
        Date in ``YYYYDDD`` format **or** Airflow ``ds`` (``YYYY-MM-DD``).

    Returns
    -------
    dict
        See :func:`check_rinex`.

    Raises
    ------
    RuntimeError
        If SBF files are missing for any receiver.
    DiscoveryError
        See :func:`check_rinex`.
    """
    return _check_files(site, yyyydoy, "sbf", "SBF")


# ---------------------------------------------------------------------------
# Task 1b — validate_data_dirs
# ---------------------------------------------------------------------------


def validate_data_dirs(site: str) -> dict:
    """Pre-flight validation of all receiver data directories for a site.

    The same check as ``canvodpy config validate`` (see
    :func:`canvodpy.orchestrator.data_check.check_site_data`), which applies
    the file discovery of ``canvodpy run``. It reports, per receiver, the
    days and files a run would process, and fails on everything that would
    stop a run or make its results wrong: a missing directory or recipe,
    files that cannot be told apart or cover the same time, two receivers
    with the same identity, and a sampling interval in a file name that
    differs from that of the data.

    Parameters
    ----------
    site : str
        Research site name (must exist in config).

    Returns
    -------
    dict
        ``{"site": str, "valid": True, "receivers": {name: {"directory",
        "recipe", "identity", "days", "files", "unrecognized",
        "warnings"}}}``. ``days`` is the number of days with files;
        ``unrecognized`` counts files that are never processed.

    Raises
    ------
    KeyError
        If *site* is not in the configuration.
    ValueError
        Listing every problem found, if a run would stop or produce wrong
        results.
    """
    from canvodpy.orchestrator.data_check import check_site_data

    config = load_config()
    if site not in config.sites.sites:
        available = ", ".join(config.sites.sites) or "(none)"
        msg = f"Unknown site '{site}'. Available sites: {available}"
        raise KeyError(msg)

    report = check_site_data(site, config)
    receivers_result = {
        name: {
            "directory": str(r.directory),
            "recipe": r.recipe,
            "identity": r.identity,
            "days": len(r.days),
            "files": r.files,
            "unrecognized": len(r.unrecognized),
            "compressed": len(r.compressed),
            "warnings": r.warnings,
        }
        for name, r in report.receivers.items()
    }
    for name, r in report.receivers.items():
        for warning in r.warnings:
            logger.warning("validate_data_dirs: %s/%s: %s", site, name, warning)

    if not report.ok:
        problems = report.errors + [
            f"[{name}] {error}"
            for name, r in report.receivers.items()
            for error in r.errors
        ]
        msg = f"Data directory validation failed for site '{site}':\n\n" + (
            "\n\n".join(problems)
        )
        logger.error(msg)
        raise ValueError(msg)

    logger.info("validate_data_dirs: %s, all receivers valid", site)
    return {"site": site, "valid": True, "receivers": receivers_result}


# ---------------------------------------------------------------------------
# SP3/CLK sensor helper — shared by all DAGs that wait for agency products
# ---------------------------------------------------------------------------


def check_sp3_availability(ds: str) -> object:
    """Return a ``PokeReturnValue`` for the SP3/CLK date-age sensor.

    Uses a date-age heuristic keyed to ``processing.aux_data.product_type``:

    * ``rapid``       — gate at 2 days
    * ``final``       — gate at 14 days (default)

    Raises ``AirflowSkipException`` when age > 30 days to prevent zombie runs.
    Falls back to ``"final"`` if config cannot be loaded.

    Intended for use inside ``@task.sensor`` bodies so that the four identical
    sensor copies (2 DAGs × 2 repos) share a single implementation.

    Parameters
    ----------
    ds : str
        Airflow ``ds`` macro value (``YYYY-MM-DD`` ISO date string).
    """
    import datetime as dt

    from airflow.exceptions import (
        AirflowSkipException,  # type: ignore[unresolved-import]
    )
    from airflow.sensors.base import PokeReturnValue  # type: ignore[unresolved-import]

    target = dt.date.fromisoformat(ds)
    age = (dt.date.today() - target).days

    if age > 30:
        raise AirflowSkipException(
            f"SP3 not available for {ds} after {age} days; abandoning"
        )

    try:
        product_type = load_config().processing.aux_data.product_type
    except Exception:
        product_type = "final"

    _MIN_AGE: dict[str, int] = {"rapid": 2, "final": 14}
    min_age = _MIN_AGE.get(product_type, 14)
    available = age >= min_age

    return PokeReturnValue(
        is_done=available,
        xcom_value={
            "sp3_ready": available,
            "product_type": product_type,
            "age_days": age,
            "min_age_days": min_age,
        },
    )


# ---------------------------------------------------------------------------
# Task 2 — fetch_aux_data
# ---------------------------------------------------------------------------


@deprecated(
    "`fetch_aux_data` is left over from development and will be removed with the next "
    "major version. Use `process_day` instead."
)
def fetch_aux_data(
    site: str,
    yyyydoy: str,
    agency: str | None = None,
    product_type: str | None = None,
    sampling_interval_s: float | None = None,
) -> dict:
    """Download SP3+CLK, Hermite-interpolate, and write to a temp Zarr store.

    SP3/CLK products are published with a delay (rapid ~1 day,
    final ~12-14 days).  When products are not yet available the FTP
    download raises ``RuntimeError("Failed to download …")``.  This
    exception is **not** caught here — it propagates to Airflow so the
    task is marked as failed and retried on the next scheduled run.

    Parameters
    ----------
    site : str
        Research site name.
    yyyydoy : str
        Date in ``YYYYDDD`` format **or** Airflow ``ds`` (``YYYY-MM-DD``).
    agency : str, optional
        Analysis center code (e.g. ``"COD"``).  Defaults to config value.
    product_type : str, optional
        ``"final"`` or ``"rapid"``.  Defaults to config value.
    sampling_interval_s : float, optional
        Observation sampling interval in seconds.  Auto-detected from
        filename if ``None``.

    Returns
    -------
    dict
        ``{"site", "yyyydoy", "aux_zarr_path", "sampling_interval_s",
        "n_epochs", "n_sids"}``
    """
    config = load_config()
    site_cfg = config.sites.sites[site]
    date_obj = _resolve_date(yyyydoy)
    keep_sids = config.sids.get_sids()

    # Resolve aux_file_path
    configured_aux_dir = config.processing.storage.aux_data_dir
    if configured_aux_dir is not None:
        aux_file_path = configured_aux_dir
    else:
        aux_file_path = site_cfg.get_base_path()

    user_email = config.nasa_earthdata_acc_mail
    base = site_cfg.get_base_path()

    # Build a MatchedDirs for the date (pipeline reads .yyyydoy from it)
    canopy_dir = reference_dir = base
    for _name, rcfg in site_cfg.receivers.items():
        if rcfg.type == "canopy" and canopy_dir == base:
            canopy_dir = base / rcfg.directory
        elif rcfg.type == "reference" and reference_dir == base:
            reference_dir = base / rcfg.directory
    matched_dirs = MatchedDirs(
        canopy_data_dir=canopy_dir,
        reference_data_dir=reference_dir,
        yyyydoy=date_obj,
    )

    # 1. Create and load pipeline (downloads SP3 + CLK via FTP)
    #    RuntimeError propagates to Airflow if products not yet available
    pipeline = AuxDataPipeline.create_standard(
        matched_dirs=matched_dirs,
        aux_file_path=aux_file_path,
        agency=agency,
        product_type=product_type,
        user_email=user_email,
        keep_sids=keep_sids,
    )
    pipeline.load_all()

    ephem_ds = pipeline.get("ephemerides")
    clock_ds = pipeline.get("clock")

    # 2. Detect sampling interval from the canonical name of the first file
    if sampling_interval_s is None:
        for files in _day_files(site, site_cfg, date_obj, None).values():
            if files:
                sampling_interval_s = parse_sampling_interval_from_filename(
                    files[0].canonical_name,
                )
                if sampling_interval_s is not None:
                    break
    if sampling_interval_s is None:
        msg = (
            f"No file of {site} on {date_obj.to_str()} names its sampling "
            "interval; pass sampling_interval_s."
        )
        raise ValueError(msg)

    # 3. Interpolate onto the day's grid at the sampling interval
    target_epochs = aux_epoch_grid(
        np.datetime64(date_obj.date, "D"), sampling_interval_s
    )
    aux_processed = interpolate_aux_day(ephem_ds, clock_ds, target_epochs)

    # 4. Write to Zarr
    aux_dir = config.processing.storage.get_aux_data_dir()
    aux_zarr_path = aux_dir / f"aux_{date_obj.to_str()}.zarr"

    if aux_zarr_path.exists():
        shutil.rmtree(aux_zarr_path)
    aux_processed.to_zarr(aux_zarr_path, mode="w")

    logger.info(
        "fetch_aux_data: wrote %s  dims=%s",
        aux_zarr_path,
        dict(aux_processed.sizes),
    )

    return {
        "site": site,
        "yyyydoy": date_obj.to_str(),
        "aux_zarr_path": str(aux_zarr_path),
        "sampling_interval_s": sampling_interval_s,
        "n_epochs": int(aux_processed.sizes["epoch"]),
        "n_sids": int(aux_processed.sizes["sid"]),
    }


# ---------------------------------------------------------------------------
# Task 3 — process_rinex
# ---------------------------------------------------------------------------


@deprecated(
    "`process_rinex` is left over from development and will be removed with the next "
    "major version. Use `process_day` instead."
)
def process_rinex(
    site: str,
    yyyydoy: str,
    aux_zarr_path: str,
    receiver_files: dict | None = None,
) -> dict:
    """Read RINEX, augment with aux data, and write to the GNSS store.

    Parameters
    ----------
    site : str
        Research site name.
    yyyydoy : str
        Date in ``YYYYDDD`` format **or** Airflow ``ds`` (``YYYY-MM-DD``).
    aux_zarr_path : str
        Path to the pre-processed auxiliary Zarr store (from ``fetch_aux_data``).
    receiver_files : dict, optional
        ``{receiver_name: {"files": [str, ...], "count": N}}`` from
        ``check_rinex``.  When ``None``, the files are discovered as
        :func:`check_rinex` does.

    Returns
    -------
    dict
        ``{"site", "yyyydoy", "receivers_processed": [...], "files_written": N}``
    """
    from pydantic import ValidationError

    from canvod.readers.rinex.v3_04 import Rnxv3Header
    from canvod.store import GnssResearchSite
    from canvodpy.orchestrator.processor import preprocess_with_hermite_aux

    config = load_config()
    _cap_blas_threads(config.processing.processing.threads_per_worker or 1)
    site_cfg = config.sites.sites[site]
    date_obj = _resolve_date(yyyydoy)
    keep_vars = config.processing.params.keep_gnss_observables
    keep_sids = config.sids.get_sids()
    aux_path = Path(aux_zarr_path)

    research_site = GnssResearchSite(site)
    # The same step as ``canvodpy run`` takes before it writes data
    research_site.ensure_store_metadata("gnss_store", _store_groups(site_cfg), "rinex3")
    receivers_processed: list[str] = []
    total_files_written = 0
    # Discovered only if the files are not passed in from check_rinex/check_sbf
    day_files: dict[str, list[DiscoveredFile]] | None = None

    # Iterate over configured receivers
    for recv_name, rcfg in site_cfg.receivers.items():
        recv_type = rcfg.type

        # Determine store groups for this receiver
        if recv_type == "canopy":
            store_groups = [recv_name]
        else:
            # Reference receivers write to {ref}_{canopy} store groups
            canopy_names = site_cfg.resolve_paired_canopies(recv_name)
            store_groups = [reference_store_group(recv_name, cn) for cn in canopy_names]

        # Resolve RINEX files
        if receiver_files and recv_name in receiver_files:
            rnx_files = [Path(f) for f in receiver_files[recv_name]["files"]]
        else:
            if day_files is None:
                day_files = _day_files(site, site_cfg, date_obj, "rinex3")
            rnx_files = [f.path for f in day_files[recv_name]]

        if not rnx_files:
            logger.warning("process_rinex: no files for %s, skipping", recv_name)
            continue

        # Compute receiver position from first RINEX header
        position: ECEFPosition | None = None
        for ff in rnx_files:
            try:
                header = Rnxv3Header.from_file(ff)
                position = ECEFPosition(
                    x=header.approx_position[0].magnitude,
                    y=header.approx_position[1].magnitude,
                    z=header.approx_position[2].magnitude,
                )
                break
            except (ValidationError, OSError, RuntimeError, ValueError) as exc:
                logger.warning("Header parse failed for %s: %s", ff.name, exc)

        if position is None:
            logger.error("No valid RINEX header for %s; skipping", recv_name)
            continue

        # Process each file sequentially (Airflow handles parallelism across sites)
        processed: list[tuple[Path, xr.Dataset]] = []
        for rnx_file in rnx_files:
            try:
                _path, augmented_ds, _aux_ds, _sid_issues = preprocess_with_hermite_aux(
                    rnx_file=rnx_file,
                    keep_vars=keep_vars,
                    aux_zarr_path=aux_path,
                    receiver_position=position,
                    receiver_type=recv_name,
                    keep_sids=keep_sids,
                    rinex_v3_parser=config.processing.params.rinex_v3_parser,
                    date_key=yyyydoy,
                )
            except Exception:
                logger.exception("Failed to process %s", rnx_file.name)
                continue
            processed.append((rnx_file, augmented_ds))

        _warn_epoch_counts(processed, day_files[recv_name] if day_files else None)
        # processing.preprocessing (if set) on the whole day, so time bins
        # can span two files; then write each file as before
        for rnx_file, augmented_ds in preprocess_files(
            processed, config.processing.preprocessing
        ):
            file_hash = augmented_ds.attrs.get("File Hash")
            time_start = augmented_ds.epoch.min().values
            time_end = augmented_ds.epoch.max().values

            # Write to each store group for this receiver
            for group in store_groups:
                # Early-exit pre-check (hash match + temporal overlap).
                # write_or_append_group(dedup=True) repeats this check as the
                # authoritative store-level gate, covering races and future
                # refactors that might bypass this pre-check.
                skip, reason = research_site.gnss_store.should_skip_file(
                    group_name=group,
                    file_hash=file_hash,
                    time_start=time_start,
                    time_end=time_end,
                )
                if skip:
                    logger.info(
                        "Skipping %s in group %s (reason=%s)",
                        rnx_file.name,
                        group,
                        reason,
                    )
                    continue

                research_site.gnss_store.write_or_append_group(
                    dataset=augmented_ds,
                    group_name=group,
                    commit_message=f"Airflow ingest {rnx_file.name}",
                    dedup=True,
                )
                total_files_written += 1

        receivers_processed.append(recv_name)
        logger.info(
            "process_rinex: %s processed %d files -> groups %s",
            recv_name,
            len(rnx_files),
            store_groups,
        )

    return {
        "site": site,
        "yyyydoy": date_obj.to_str(),
        "receivers_processed": receivers_processed,
        "files_written": total_files_written,
        "store_radial_distance": config.processing.processing.store_radial_distance,
    }


# ---------------------------------------------------------------------------
# Task 3b — process_sbf (broadcast or agency ephemeris)
# ---------------------------------------------------------------------------


@deprecated(
    "`process_sbf` is left over from development and will be removed with the next "
    "major version. Use `process_day` instead."
)
def process_sbf(
    site: str,
    yyyydoy: str,
    receiver_files: dict | None = None,
    aux_zarr_path: str | None = None,
) -> dict:
    """Read SBF, augment with ephemeris, and write to Icechunk store.

    Supports two ephemeris modes controlled by ``aux_zarr_path``:

    * ``aux_zarr_path=None`` *(default)* — **broadcast geometry**: theta/phi
      come from SBF ``SatVisibility`` blocks embedded in the binary.  No
      external products needed; results are available same-day.
    * ``aux_zarr_path=<path>`` — **agency geometry**: theta/phi are computed
      from Hermite-interpolated SP3/CLK products (same path produced by
      ``fetch_aux_data``).  Geometry quality matches the RINEX pipeline at
      the cost of a 12-18 day product lag.

    In both modes SBF observables (SNR, Phase, Pseudorange, Doppler) are
    written, and with ``store_sbf_metadata`` (default) the file's metadata
    (PVT, DOP, SatVisibility as ``sbf_obs``) goes into the same commit, under
    ``{group}/metadata/sbf_obs`` of each store group the file is written to.

    Parameters
    ----------
    site : str
        Research site name.
    yyyydoy : str
        Date in ``YYYYDDD`` format **or** Airflow ``ds`` (``YYYY-MM-DD``).
    receiver_files : dict, optional
        ``{receiver_name: {"files": [str, ...], "count": N}}`` from
        ``check_sbf``.  When ``None``, the files are discovered as
        :func:`check_sbf` does.
    aux_zarr_path : str or None, optional
        Path to the Hermite-interpolated auxiliary Zarr store produced by
        ``fetch_aux_data``.  When ``None``, broadcast geometry is used.

    Returns
    -------
    dict
        ``{"site", "yyyydoy", "receivers_processed", "files_written",
        "sbf_obs_written", "ephemeris_source"}``
    """
    from canvod.store import GnssResearchSite
    from canvodpy.orchestrator.processor import preprocess_with_hermite_aux

    config = load_config()
    _cap_blas_threads(config.processing.processing.threads_per_worker or 1)
    site_cfg = config.sites.sites[site]
    date_obj = _resolve_date(yyyydoy)
    keep_vars = config.processing.params.keep_gnss_observables
    keep_sids = config.sids.get_sids()
    store_sbf_metadata = config.processing.params.store_sbf_metadata

    use_broadcast = aux_zarr_path is None
    # preprocess_with_hermite_aux always requires an aux path argument;
    # when using broadcast geometry the path is unused internally.
    effective_aux_path = Path("/dev/null") if use_broadcast else Path(aux_zarr_path)

    research_site = GnssResearchSite(site)
    # The same step as ``canvodpy run`` takes before it writes data
    research_site.ensure_store_metadata("gnss_store", _store_groups(site_cfg), "sbf")
    receivers_processed: list[str] = []
    total_files_written = 0
    # Discovered only if the files are not passed in from check_rinex/check_sbf
    day_files: dict[str, list[DiscoveredFile]] | None = None
    sbf_obs_written = False

    for recv_name, rcfg in site_cfg.receivers.items():
        recv_type = rcfg.type

        # Determine store groups
        if recv_type == "canopy":
            store_groups = [recv_name]
        else:
            canopy_names = site_cfg.resolve_paired_canopies(recv_name)
            store_groups = [reference_store_group(recv_name, cn) for cn in canopy_names]

        # Resolve SBF files
        if receiver_files and recv_name in receiver_files:
            sbf_files = [Path(f) for f in receiver_files[recv_name]["files"]]
        else:
            if day_files is None:
                day_files = _day_files(site, site_cfg, date_obj, "sbf")
            sbf_files = [f.path for f in day_files[recv_name]]

        if not sbf_files:
            logger.warning("process_sbf: no SBF files for %s, skipping", recv_name)
            continue

        # Receiver position from first SBF file's metadata
        position: ECEFPosition | None = None
        for ff in sbf_files:
            try:
                from canvodpy.factories import ReaderFactory

                reader = ReaderFactory.create("sbf", fpath=ff)
                ds_tmp = reader.to_ds(keep_data_vars=None, write_global_attrs=True)
                position = ECEFPosition.from_ds_metadata(ds_tmp)
                break
            except Exception as exc:
                logger.warning("SBF position extract failed for %s: %s", ff.name, exc)

        if position is None:
            logger.error("No valid position for %s; skipping", recv_name)
            continue

        # Process each SBF file
        processed: list[tuple[Path, xr.Dataset]] = []
        aux_by_file: dict[Path, dict[str, xr.Dataset]] = {}
        for sbf_file in sbf_files:
            try:
                _path, augmented_ds, aux_datasets, _sid_issues = (
                    preprocess_with_hermite_aux(
                        rnx_file=sbf_file,
                        keep_vars=keep_vars,
                        aux_zarr_path=effective_aux_path,
                        receiver_position=position,
                        receiver_type=recv_name,
                        keep_sids=keep_sids,
                        reader_name="sbf",
                        use_sbf_geometry=use_broadcast,
                        date_key=yyyydoy,
                    )
                )
            except Exception:
                logger.exception("Failed to process SBF %s", sbf_file.name)
                continue
            processed.append((sbf_file, augmented_ds))
            aux_by_file[sbf_file] = aux_datasets

        _warn_epoch_counts(processed, day_files[recv_name] if day_files else None)
        # processing.preprocessing (if set) on the whole day, so time bins
        # can span two files; then write each file as before
        for sbf_file, augmented_ds in preprocess_files(
            processed, config.processing.preprocessing
        ):
            aux_datasets = aux_by_file[sbf_file]
            # sbf_obs goes into the same commit as the file's observations
            metadata_datasets = (
                {"sbf_obs": aux_datasets["sbf_obs"]}
                if store_sbf_metadata and "sbf_obs" in aux_datasets
                else None
            )

            file_hash = augmented_ds.attrs.get("File Hash")
            time_start = augmented_ds.epoch.min().values
            time_end = augmented_ds.epoch.max().values

            # Write to each store group
            for group in store_groups:
                # Early-exit pre-check (hash match + temporal overlap).
                # write_or_append_group(dedup=True) repeats this check as the
                # authoritative store-level gate, covering races and future
                # refactors that might bypass this pre-check.
                skip, reason = research_site.gnss_store.should_skip_file(
                    group_name=group,
                    file_hash=file_hash,
                    time_start=time_start,
                    time_end=time_end,
                )
                if skip:
                    logger.info(
                        "Skipping %s in group %s (reason=%s)",
                        sbf_file.name,
                        group,
                        reason,
                    )
                    continue

                written = research_site.gnss_store.write_or_append_group(
                    dataset=augmented_ds,
                    group_name=group,
                    commit_message=f"Airflow SBF ingest {sbf_file.name}",
                    dedup=True,
                    metadata_datasets=metadata_datasets,
                )
                total_files_written += 1
                sbf_obs_written = sbf_obs_written or (
                    written and metadata_datasets is not None
                )

        receivers_processed.append(recv_name)
        logger.info(
            "process_sbf: %s processed %d files -> groups %s",
            recv_name,
            len(sbf_files),
            store_groups,
        )

    return {
        "site": site,
        "yyyydoy": date_obj.to_str(),
        "receivers_processed": receivers_processed,
        "files_written": total_files_written,
        "sbf_obs_written": sbf_obs_written,
        "ephemeris_source": "broadcast" if use_broadcast else "agency",
        "store_radial_distance": config.processing.processing.store_radial_distance,
        "store_sbf_raw_observables": config.processing.processing.store_sbf_raw_observables,
    }


# ---------------------------------------------------------------------------
# Task 3 — process_day (the code of ``canvodpy run``)
# ---------------------------------------------------------------------------


def process_day(site: str, yyyydoy: str) -> dict:
    """Process one day of all receivers of a site and write the GNSS store.

    Runs ``Site(site).pipeline().process_date()``, the same code as
    ``canvodpy run``: file discovery, auxiliary data, reader, receiver
    position, satellite geometry, ``processing.preprocessing`` and the
    store write with its log book. Each receiver is read with the
    ``reader_format`` of its site configuration.

    Parameters
    ----------
    site : str
        Research site name.
    yyyydoy : str
        Date in ``YYYYDDD`` format **or** Airflow ``ds`` (``YYYY-MM-DD``).

    Returns
    -------
    dict
        ``{"site", "yyyydoy", "groups": {group: n_epochs}}``.

    Raises
    ------
    RuntimeError
        If nothing was processed for the day (e.g. no files, or the
        auxiliary data could not be downloaded), so Airflow retries the
        task; the log of the run gives the reason.
    """
    from canvodpy.api import Site

    date_obj = _resolve_date(yyyydoy)
    with Site(site).pipeline() as pipeline:
        datasets = pipeline.process_date(date_obj.to_str())
    if not datasets:
        msg = f"Nothing processed for {site} {date_obj.to_str()}; see the log"
        raise RuntimeError(msg)

    return {
        "site": site,
        "yyyydoy": date_obj.to_str(),
        "groups": {
            name: int(ds.sizes.get("epoch", 0)) for name, ds in datasets.items()
        },
    }


# ---------------------------------------------------------------------------
# Task 3c — validate_ingest (quality gate between ingest and VOD)
# ---------------------------------------------------------------------------


def validate_ingest(site: str, yyyydoy: str) -> dict:
    """Spot-check stored data before VOD computation.

    Reads back ingested data from the Icechunk store and verifies basic
    physical plausibility. Catches corrupt writes, coordinate transform
    bugs, or SID mismatches before they propagate into VOD.

    Parameters
    ----------
    site : str
        Research site name.
    yyyydoy : str
        Date in ``YYYYDDD`` format **or** Airflow ``ds`` (``YYYY-MM-DD``).

    Returns
    -------
    dict
        ``{"site", "yyyydoy", "valid": bool, "checks": {...}}``

    Raises
    ------
    RuntimeError
        If any check fails (blocks VOD computation).
    """
    from canvod.store import GnssResearchSite

    config = load_config()
    site_cfg = config.sites.sites[site]
    date_obj = _resolve_date(yyyydoy)

    research_site = GnssResearchSite(site)
    checks: dict[str, dict] = {}
    all_valid = True

    import datetime as _dt

    assert date_obj.date is not None
    day_start = _dt.datetime.combine(date_obj.date, _dt.time.min)
    day_end = day_start + _dt.timedelta(days=1)
    time_range = (day_start, day_end)

    for recv_name, rcfg in site_cfg.receivers.items():
        recv_checks: dict[str, str] = {}

        try:
            ds = research_site.read_receiver_data(
                receiver_name=recv_name,
                time_range=time_range,
            )
        except Exception:
            recv_checks["data_loaded"] = "SKIP: no data for this date"
            checks[recv_name] = recv_checks
            continue

        n_epochs = ds.sizes.get("epoch", 0)
        n_sids = ds.sizes.get("sid", 0)

        # Check 1: non-empty
        if n_epochs == 0 or n_sids == 0:
            recv_checks["non_empty"] = f"FAIL: {n_epochs} epochs, {n_sids} sids"
            all_valid = False
        else:
            recv_checks["non_empty"] = f"OK: {n_epochs} epochs, {n_sids} sids"

        # Check 2: SNR in plausible range (0-70 dB-Hz)
        for snr_var in ["cn0", "SNR", "S1C", "S1W", "S2C", "S2W"]:
            if snr_var in ds.data_vars:
                snr_vals = ds[snr_var].values[np.isfinite(ds[snr_var].values)]
                if len(snr_vals) > 0:
                    snr_min, snr_max = float(snr_vals.min()), float(snr_vals.max())
                    if snr_min < 0 or snr_max > 70:
                        recv_checks["snr_range"] = (
                            f"FAIL: {snr_var} range [{snr_min:.1f}, {snr_max:.1f}]"
                        )
                        all_valid = False
                    else:
                        recv_checks["snr_range"] = (
                            f"OK: {snr_var} [{snr_min:.1f}, {snr_max:.1f}]"
                        )
                break

        # Check 3: theta (polar angle) in valid range [0, π/2]
        if "theta" in ds.coords:
            theta = ds.coords["theta"].values[np.isfinite(ds.coords["theta"].values)]
            if len(theta) > 0:
                t_min, t_max = float(theta.min()), float(theta.max())
                if t_min < -0.01 or t_max > np.pi / 2 + 0.01:
                    recv_checks["theta_range"] = (
                        f"FAIL: theta [{t_min:.4f}, {t_max:.4f}] rad"
                    )
                    all_valid = False
                else:
                    recv_checks["theta_range"] = (
                        f"OK: theta [{t_min:.4f}, {t_max:.4f}] rad"
                    )

        # Check 4: phi (azimuth) in valid range [0, 2π]
        if "phi" in ds.coords:
            phi = ds.coords["phi"].values[np.isfinite(ds.coords["phi"].values)]
            if len(phi) > 0:
                p_min, p_max = float(phi.min()), float(phi.max())
                if p_min < -0.01 or p_max > 2 * np.pi + 0.01:
                    recv_checks["phi_range"] = (
                        f"FAIL: phi [{p_min:.4f}, {p_max:.4f}] rad"
                    )
                    all_valid = False
                else:
                    recv_checks["phi_range"] = f"OK: phi [{p_min:.4f}, {p_max:.4f}] rad"

        checks[recv_name] = recv_checks

    result = {
        "site": site,
        "yyyydoy": date_obj.to_str(),
        "valid": all_valid,
        "checks": checks,
    }

    if not all_valid:
        failed = {
            r: {k: v for k, v in c.items() if v.startswith("FAIL")}
            for r, c in checks.items()
            if any(v.startswith("FAIL") for v in c.values())
        }
        msg = f"Ingest validation failed for {site} {date_obj.to_str()}: {failed}"
        logger.error(msg)
        raise RuntimeError(msg)

    logger.info("validate_ingest: %s %s, all checks passed", site, date_obj.to_str())
    return result


# ---------------------------------------------------------------------------
# Task 4 — calculate_vod
# ---------------------------------------------------------------------------


def calculate_vod(site: str, yyyydoy: str) -> dict:
    """Compute VOD for all active analysis pairs and write to the VOD store.

    Reads the day from the GNSS store and goes through
    ``VodComputer.compute_bulk_all`` -- the same VOD code as ``canvodpy run``
    and ``site.vod`` -- writing all analyses of the day in one commit.

    Parameters
    ----------
    site : str
        Research site name.
    yyyydoy : str
        Date in ``YYYYDDD`` format **or** Airflow ``ds`` (``YYYY-MM-DD``).

    Returns
    -------
    dict
        ``{"site", "yyyydoy", "analyses": {name: {"mean_vod", "std_vod",
        "n_epochs"}}}``
    """
    from canvodpy.api import Site

    date_obj = _resolve_date(yyyydoy)

    day_date = date_obj.date
    if day_date is None:
        msg = f"Missing calendar date for {date_obj.to_str()}"
        raise ValueError(msg)
    start_time = datetime.datetime.combine(day_date, datetime.time.min)
    end_time = datetime.datetime.combine(day_date, datetime.time.max)

    logger.info("calculate_vod: %s %s", site, date_obj.to_str())
    results = Site(site).vod.compute_bulk_all(start=start_time, end=end_time)

    analyses_result: dict[str, dict] = {}
    for analysis_name, vod_ds in results.items():
        vod_values = vod_ds["VOD"].values
        analyses_result[analysis_name] = {
            "mean_vod": float(np.nanmean(vod_values)),
            "std_vod": float(np.nanstd(vod_values)),
            "n_epochs": int(vod_ds.sizes.get("epoch", 0)),
        }

    return {
        "site": site,
        "yyyydoy": date_obj.to_str(),
        "analyses": analyses_result,
    }


# ---------------------------------------------------------------------------
# Task 5 — cleanup (runs regardless of upstream outcome)
# ---------------------------------------------------------------------------


@deprecated(
    "`cleanup` is left over from development and will be removed with the "
    "next major version. Use `process_day` instead; it keeps its auxiliary "
    "data where `canvodpy run` keeps it."
)
def cleanup(site: str, yyyydoy: str) -> dict:
    """Remove temporary files created during pipeline execution.

    Cleans up the aux Zarr store from ``fetch_aux_data`` and any other
    temporary artifacts. Designed to run with ``TriggerRule.ALL_DONE``
    so it executes even if upstream tasks fail.

    Parameters
    ----------
    site : str
        Research site name.
    yyyydoy : str
        Date in ``YYYYDDD`` format **or** Airflow ``ds`` (``YYYY-MM-DD``).

    Returns
    -------
    dict
        ``{"site", "yyyydoy", "cleaned": [...]}``
    """
    date_obj = _resolve_date(yyyydoy)
    cleaned: list[str] = []

    # Clean up aux Zarr temp files
    try:
        config = load_config()
        aux_dir = config.processing.storage.get_aux_data_dir()
        aux_zarr_path = aux_dir / f"aux_{date_obj.to_str()}.zarr"
        if aux_zarr_path.exists():
            shutil.rmtree(aux_zarr_path)
            cleaned.append(str(aux_zarr_path))
            logger.info("cleanup: removed %s", aux_zarr_path)
    except Exception:
        logger.exception("cleanup: failed to remove aux Zarr")

    return {
        "site": site,
        "yyyydoy": date_obj.to_str(),
        "cleaned": cleaned,
    }
