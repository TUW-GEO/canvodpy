"""Ephemeris provider ABC and implementations.

Provides a unified interface for augmenting GNSS datasets with satellite
angular coordinates (theta, phi).  Three implementations:

- ``AgencyEphemerisProvider`` — SP3/CLK from analysis centers (COD, ESA, IGS),
  Hermite interpolation.  Extracted from the orchestrator's aux data pipeline.
- ``SbfBroadcastProvider`` — theta/phi directly from SBF SatVisibility blocks.
- ``RinexNavProvider`` — (future) parses RINEX NAV files.

Examples
--------
Standalone augmentation (Level 4 functional)::

    from canvod.auxiliary.ephemeris.provider import AgencyEphemerisProvider

    provider = AgencyEphemerisProvider(agency="COD")
    provider.preprocess_day(date="2025001", site_config=site_cfg)
    ds = provider.augment_dataset(ds, receiver_position=rx_pos)

"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import xarray as xr

    from canvod.auxiliary.position.position import ECEFPosition


class EphemerisProvider(ABC):
    """Abstract base class for satellite ephemeris providers.

    Implementations augment a GNSS dataset with angular coordinates
    (theta, phi) relative to a receiver position.
    """

    @abstractmethod
    def augment_dataset(
        self,
        ds: xr.Dataset,
        receiver_position: ECEFPosition,
    ) -> xr.Dataset:
        """Add theta and phi (and optionally r) to *ds*.

        Parameters
        ----------
        ds : xr.Dataset
            GNSS observation dataset with ``(epoch, sid)`` dims.
        receiver_position : ECEFPosition
            Receiver ECEF coordinates.

        Returns
        -------
        xr.Dataset
            Dataset with ``theta``, ``phi`` (and optionally ``r``) added.
        """

    @abstractmethod
    def preprocess_day(
        self,
        date: str,
        site_config: Any,
    ) -> Path | None:
        """Download / prepare ephemeris data for one day.

        Parameters
        ----------
        date : str
            Date in ``YYYYDOY`` format.
        site_config : Any
            Site configuration object providing receiver info, data root, etc.

        Returns
        -------
        Path or None
            Path to cached/preprocessed ephemeris data, or ``None``
            if preparation is not needed (e.g. broadcast provider).
        """


class AgencyEphemerisProvider(EphemerisProvider):
    """SP3/CLK-based ephemeris from analysis centers.

    Downloads final or rapid products from COD, ESA, IGS etc.,
    interpolates via Hermite cubic splines, and computes theta/phi
    via ECEF→spherical coordinate transformation.

    Parameters
    ----------
    agency : str
        Analysis center code (``"COD"``, ``"ESA"``, ``"GFZ"``, ``"JPL"``).
    product_type : str
        Product type (``"final"`` or ``"rapid"``).
    aux_data_dir : Path, optional
        Directory for cached aux Zarr files.
    keep_sids : list[str], optional
        SID filter list.
    store_radial_distance : bool
        Whether to keep ``r`` in the output.
    fetch_clock : bool, optional
        Whether to also download/interpolate CLK clock-correction files.
        If None, uses ``config.processing.aux_data.fetch_clock``.
    """

    def __init__(
        self,
        agency: str = "COD",
        product_type: str = "final",
        aux_data_dir: Path | None = None,
        keep_sids: list[str] | None = None,
        store_radial_distance: bool = False,
        fetch_clock: bool | None = None,
    ) -> None:
        self.agency = agency
        self.product_type = product_type
        self.aux_data_dir = aux_data_dir
        self.keep_sids = keep_sids
        self.store_radial_distance = store_radial_distance
        self.fetch_clock = fetch_clock
        self._date: str | None = None
        self._aux_dir: Path | None = None
        self._ephem_ds: xr.Dataset | None = None
        self._clock_ds: xr.Dataset | None = None
        self._aux_zarr_paths: dict[float, Path] = {}

    def preprocess_day(
        self,
        date: str,
        site_config: Any,
    ) -> Path | None:
        """Download and read the SP3 (and CLK) products of one day.

        The products are interpolated later, in :meth:`augment_dataset`,
        onto the day's epoch grid at the sampling interval of the dataset
        being augmented, the same grid ``canvodpy run`` uses (see
        :mod:`canvod.auxiliary.interpolation.day_grid`). The interpolated
        day is written once per sampling interval to
        ``aux_<date>_<interval>s.zarr`` in the returned directory.

        Parameters
        ----------
        date : str
            Date in ``YYYYDOY`` format.
        site_config : Any
            Site configuration (needs ``gnss_site_data_root``, receiver info).

        Returns
        -------
        Path
            Directory of the interpolated aux Zarr stores.
        """
        from canvod.auxiliary.pipeline import AuxDataPipeline

        aux_dir = self.aux_data_dir or Path(site_config.gnss_site_data_root)

        # Build MatchedDirs stub (only yyyydoy is used by the pipeline)
        from canvod.readers.matching.models import MatchedDirs
        from canvod.utils.tools import YYYYDOY

        matched_dirs = MatchedDirs(
            canopy_data_dir=aux_dir,
            reference_data_dir=aux_dir,
            yyyydoy=YYYYDOY.from_str(date),
        )

        pipeline = AuxDataPipeline.create_standard(
            matched_dirs=matched_dirs,
            aux_file_path=aux_dir,
            agency=self.agency,
            product_type=self.product_type,
            keep_sids=self.keep_sids,
            fetch_clock=self.fetch_clock,
        )
        pipeline.load_all()

        self._date = date
        self._aux_dir = aux_dir
        self._ephem_ds = pipeline.get("ephemerides")
        self._clock_ds = pipeline.get("clock") if pipeline.is_loaded("clock") else None
        self._aux_zarr_paths = {}
        return aux_dir

    def _aux_store(self, interval_s: float) -> Path:
        """Interpolated aux store of the day at ``interval_s``, built once."""
        import shutil

        import numpy as np
        from canvod.utils.tools import YYYYDOY

        from canvod.auxiliary.interpolation import aux_epoch_grid, interpolate_aux_day

        path = self._aux_zarr_paths.get(interval_s)
        if path is not None:
            return path

        assert self._aux_dir is not None and self._ephem_ds is not None
        path = self._aux_dir / f"aux_{self._date}_{interval_s:g}s.zarr"
        # Always reprocess (cheap; avoids stale caches)
        if path.exists():
            shutil.rmtree(path)
        day_start = np.datetime64(YYYYDOY.from_str(str(self._date)).date, "D")
        aux = interpolate_aux_day(
            self._ephem_ds, self._clock_ds, aux_epoch_grid(day_start, interval_s)
        )
        aux.to_zarr(path, mode="w", consolidated=False)
        self._aux_zarr_paths[interval_s] = path
        return path

    def augment_dataset(
        self,
        ds: xr.Dataset,
        receiver_position: ECEFPosition,
    ) -> xr.Dataset:
        """Add theta/phi to dataset using preprocessed SP3/CLK data.

        Parameters
        ----------
        ds : xr.Dataset
            GNSS observation dataset.
        receiver_position : ECEFPosition
            Receiver ECEF position.

        Returns
        -------
        xr.Dataset
            Augmented dataset with theta, phi (and optionally r).

        Raises
        ------
        RuntimeError
            If ``preprocess_day()`` has not been called.
        """
        import xarray as xr

        from canvod.auxiliary.interpolation import sampling_interval_from_epochs
        from canvod.auxiliary.position.spherical_coords import (
            add_spherical_coords_to_dataset,
            compute_spherical_coordinates,
        )

        if self._ephem_ds is None:
            raise RuntimeError(
                "Call preprocess_day() before augment_dataset(). "
                "The aux data must be prepared first."
            )

        # Interpolated day at the dataset's sampling interval; each
        # observation epoch takes the nearest grid epoch.
        interval_s = sampling_interval_from_epochs(ds.epoch.values)
        aux_store = xr.open_zarr(
            self._aux_store(interval_s), decode_timedelta=False, consolidated=False
        )
        aux_slice = aux_store.sel(epoch=ds.epoch, method="nearest").load()

        # Inner join on SIDs
        common_sids = sorted(set(ds.sid.values) & set(aux_slice.sid.values))
        if not common_sids:
            raise ValueError(
                f"No common SIDs between dataset ({len(ds.sid)}) "
                f"and aux data ({len(aux_slice.sid)})"
            )

        ds = ds.sel(sid=common_sids)
        aux_slice = aux_slice.sel(sid=common_sids)

        # Compute spherical coordinates
        sat_x = aux_slice["X"].values
        sat_y = aux_slice["Y"].values
        sat_z = aux_slice["Z"].values
        r, theta, phi = compute_spherical_coordinates(
            sat_x,
            sat_y,
            sat_z,
            receiver_position,
        )
        ds = add_spherical_coords_to_dataset(ds, r, theta, phi)

        if not self.store_radial_distance and "r" in ds:
            ds = ds.drop_vars("r")

        # Add clock if available
        if "clock" in aux_slice.data_vars:
            ds = ds.assign({"clock": aux_slice["clock"]})

        return ds


class SbfBroadcastProvider(EphemerisProvider):
    """Ephemeris from SBF SatVisibility broadcast data.

    Transfers theta/phi directly from SBF metadata datasets,
    skipping external orbit/clock downloads entirely.  Only works
    when the source format is SBF.

    Only angles the receiver computed from the broadcast ephemeris are used
    (``broadcast_angle_source == 2``). Almanac-based angles become NaN: on
    the canVODpy test data (2025-001) they differ from the ephemeris-based
    angles by up to 0.26 deg for GLONASS and up to 104 deg for BeiDou.

    Parameters
    ----------
    canopy_file : Path, optional
        Path to canopy SBF file for reference receivers in shared-position
        mode.  When provided, the canopy file's geometry overrides the
        reference file's own geometry.
    canopy_reader_format : str
        Reader format for the canopy file. Only ``"sbf"`` carries
        SatVisibility geometry.
    keep_sids : list of str, optional
        SIDs to keep when reading ``canopy_file``. Only saves work: the
        geometry is aligned to the observation SIDs either way.
    """

    def __init__(
        self,
        canopy_file: Path | None = None,
        canopy_reader_format: str = "sbf",
        keep_sids: list[str] | None = None,
    ) -> None:
        if canopy_reader_format != "sbf":
            raise ValueError(
                f"canopy_reader_format={canopy_reader_format!r}: only SBF files "
                "carry SatVisibility geometry, use 'sbf'."
            )
        self.canopy_file = canopy_file
        self.canopy_reader_format = canopy_reader_format
        self.keep_sids = keep_sids

    def preprocess_day(
        self,
        date: str,
        site_config: Any,
    ) -> Path | None:
        """No preprocessing needed for broadcast ephemeris."""
        return None

    def augment_dataset(
        self,
        ds: xr.Dataset,
        receiver_position: ECEFPosition,
        *,
        aux_datasets: dict[str, xr.Dataset] | None = None,
    ) -> xr.Dataset:
        """Add theta/phi from SBF SatVisibility metadata.

        Parameters
        ----------
        ds : xr.Dataset
            SBF observation dataset.
        receiver_position : ECEFPosition
            Receiver ECEF position (unused but required by ABC).
        aux_datasets : dict, optional
            Auxiliary datasets from ``reader.to_ds_and_auxiliary()``.
            Must contain ``"sbf_obs"`` with theta/phi.

        Returns
        -------
        xr.Dataset
            Dataset with theta/phi added from SBF broadcast. Cells without
            an ephemeris-based angle are NaN.

        Raises
        ------
        ValueError
            If no ``sbf_obs`` is available, it lacks the SatVisibility
            variables, or it holds no ephemeris-based angle for any
            observation.
        """
        import numpy as np

        # Determine source of sbf_obs metadata
        if self.canopy_file is not None:
            from canvod.readers.sbf.reader import SbfReader

            _, canopy_aux = SbfReader(fpath=self.canopy_file).to_ds_and_auxiliary(
                keep_data_vars=None,
                keep_sids=self.keep_sids,
            )
            meta_ds = canopy_aux.get("sbf_obs")
        elif aux_datasets is not None:
            meta_ds = aux_datasets.get("sbf_obs")
        else:
            raise ValueError(
                "SbfBroadcastProvider requires either canopy_file or "
                "aux_datasets with 'sbf_obs' key."
            )

        required = ("broadcast_theta", "broadcast_phi", "broadcast_angle_source")
        if meta_ds is None or any(name not in meta_ds for name in required):
            raise ValueError(
                "sbf_obs metadata does not contain broadcast_theta, "
                "broadcast_phi and broadcast_angle_source. "
                "Cannot use broadcast ephemeris."
            )

        from canvod.auxiliary.position.spherical_coords import (
            add_broadcast_spherical_coords_to_dataset,
        )

        # Extract broadcast geometry (already in radians from reader); keep
        # only angles computed from the broadcast ephemeris (2), not the
        # almanac (1) or an unknown source (-1).
        from_ephemeris = meta_ds["broadcast_angle_source"] == 2
        bt = meta_ds["broadcast_theta"].where(from_ephemeris)
        bp = meta_ds["broadcast_phi"].where(from_ephemeris)

        # Align to observation epoch space
        if "epoch" in bt.dims:
            common_epochs = np.intersect1d(ds.epoch.values, bt.epoch.values)
            bt = bt.sel(epoch=common_epochs).reindex(
                epoch=ds.epoch.values, fill_value=np.nan
            )
            bp = bp.sel(epoch=common_epochs).reindex(
                epoch=ds.epoch.values, fill_value=np.nan
            )

        # Align to observation SID space
        common_sids = sorted(set(ds.sid.values) & set(bt.sid.values))
        bt = bt.sel(sid=common_sids).reindex(sid=ds.sid.values, fill_value=np.nan)
        bp = bp.sel(sid=common_sids).reindex(sid=ds.sid.values, fill_value=np.nan)

        if np.isnan(bt.values).all():
            raise ValueError(
                "sbf_obs holds no ephemeris-based SatVisibility angle for any "
                "observation. Cannot use broadcast ephemeris."
            )

        # Use .values to prevent coord leakage from meta_ds (pdop, hdop, …)
        return add_broadcast_spherical_coords_to_dataset(ds, bt.values, bp.values)
