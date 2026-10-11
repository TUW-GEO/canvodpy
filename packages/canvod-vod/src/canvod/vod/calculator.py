"""VOD calculators based on Tau-Omega model variants."""

import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import numpy as np
import structlog
import xarray as xr
from canvod.utils.tools import deprecated, deprecated_argument
from pydantic import BaseModel, ConfigDict, field_validator, model_validator

log = structlog.get_logger(__name__)


class VODCalculator(ABC, BaseModel):
    """Abstract base class for VOD calculation from GNSS store data.

    Notes
    -----
    This is an abstract base class (ABC) and a Pydantic model.

    On construction, ``canopy_ds`` and ``sky_ds`` are aligned with an inner
    join on all shared coordinates, so every calculator works only on the
    epochs and signals present in both receivers, whoever constructs it.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    canopy_ds: xr.Dataset
    sky_ds: xr.Dataset

    @field_validator("canopy_ds", "sky_ds")
    @classmethod
    def validate_datasets(cls, v: xr.Dataset) -> xr.Dataset:
        """Validate dataset inputs.

        Parameters
        ----------
        v : xr.Dataset
            Dataset to validate.

        Returns
        -------
        xr.Dataset
            Validated dataset.

        Raises
        ------
        ValueError
            If the input is not an xarray Dataset or lacks SNR.
        """
        if not isinstance(v, xr.Dataset):
            raise ValueError("Must be xr.Dataset")
        if "SNR" not in v.data_vars:
            raise ValueError("Dataset must contain 'SNR' variable")
        return v

    @model_validator(mode="after")
    def _align_receivers(self) -> VODCalculator:
        """Restrict both datasets to the epochs and signals they share."""
        self.canopy_ds, self.sky_ds = xr.align(
            self.canopy_ds, self.sky_ds, join="inner"
        )
        return self

    @abstractmethod
    def calculate_vod(self) -> xr.Dataset:
        """Calculate VOD and return a dataset with VOD, phi, theta.

        Returns
        -------
        xr.Dataset
            Dataset containing VOD and angular coordinates.
        """
        raise NotImplementedError

    @classmethod
    @deprecated(
        "VODCalculator.from_icechunkstore() is left over from development and "
        "will be removed with the next major version. Use "
        "canvodpy.Site(<site>).vod.compute_bulk(<analysis>, write=False) "
        "instead, which reads the configured store groups, drops duplicate "
        "epochs and sorts them."
    )
    def from_icechunkstore(
        cls,
        icechunk_store_pth: Path,
        canopy_group: str,
        sky_group: str,
        **open_kwargs: Any,
    ) -> xr.Dataset:
        """Convenience method to calculate VOD directly from an IcechunkStore.

        Parameters
        ----------
        icechunk_store_pth : Path
            Path to Icechunk store.
        canopy_group : str
            Canopy receiver group name, e.g. ``"canopy_01"``.
        sky_group : str
            Reference receiver group name. Runs store a reference receiver
            once per canopy receiver it is paired with, as
            ``{reference}_{canopy}``, e.g. ``"reference_01_canopy_01"``.
        open_kwargs : dict[str, Any]
            Additional keyword arguments for IcechunkStore.open().
            Currently unused.

        Returns
        -------
        xr.Dataset
            VOD dataset.

        Notes
        -----
        Requires canvod-store to be installed.
        """
        try:
            from canvod.store import MyIcechunkStore
        except ImportError as e:
            raise ImportError(
                "canvod-store package required for from_icechunkstore(). "
                "Install with: uv add canvod-store"
            ) from e

        store = MyIcechunkStore(icechunk_store_pth)

        with store.readonly_session() as session:
            canopy_ds = xr.open_zarr(store=session.store, group=canopy_group)
            sky_ds = xr.open_zarr(store=session.store, group=sky_group)

        return cls.from_datasets(canopy_ds=canopy_ds, sky_ds=sky_ds)

    @classmethod
    @deprecated_argument(
        "align",
        "The 'align' argument of from_datasets() is left over from "
        "development and will be removed with the next major "
        "version. It is ignored: the calculator always aligns both "
        "datasets on their shared epochs and signals. Remove the "
        "argument.",
    )
    def from_datasets(
        cls,
        canopy_ds: xr.Dataset,
        sky_ds: xr.Dataset,
        align: bool | None = None,
    ) -> xr.Dataset:
        """Convenience method to calculate VOD directly from datasets.

        Parameters
        ----------
        canopy_ds : xr.Dataset
            Canopy receiver dataset.
        sky_ds : xr.Dataset
            Sky/reference receiver dataset.

        Returns
        -------
        xr.Dataset
            VOD dataset.
        """
        calculator = cls(canopy_ds=canopy_ds, sky_ds=sky_ds)
        return calculator.calculate_vod()


VOD_ATTRS: dict[str, str] = {
    "long_name": "Vegetation optical depth",
    "coverage_content_type": "modelResult",
    "units": "1",
    "description": (
        "Zeroth-order tau-omega approximation: "
        "VOD = -ln(10 ** (delta_snr / 10)) * cos(theta)."
    ),
}

DELTA_SNR_ATTRS: dict[str, str] = {
    "long_name": "SNR of the canopy receiver minus SNR of the reference receiver",
    "coverage_content_type": "physicalMeasurement",
    "units": "dB",
}


class TauOmegaZerothOrder(VODCalculator):
    """Calculate VOD using the zeroth-order Tau-Omega approximation.

    Based on Humphrey, V., & Frankenberg, C. (2022).
    """

    def get_delta_snr(self) -> xr.DataArray:
        """Calculate delta SNR = SNR_canopy - SNR_sky.

        Returns
        -------
        xr.DataArray
            Delta SNR in decibels.
        """
        return self.canopy_ds["SNR"] - self.sky_ds["SNR"]

    def decibel2linear(self, delta_snr_db: xr.DataArray) -> xr.DataArray:
        """Convert decibel values to linear values.

        Parameters
        ----------
        delta_snr_db : xr.DataArray
            Delta SNR in decibels.

        Returns
        -------
        xr.DataArray
            Linear-scale values.
        """
        return 10 ** (delta_snr_db / 10)

    def calculate_vod(self) -> xr.Dataset:
        """Calculate VOD using the zeroth-order approximation.

        Returns a lazy xarray.Dataset when the inputs are dask-backed so that
        the caller can rechunk and let a single write trigger computation.
        For in-memory (numpy) inputs the result is computed immediately.

        Returns
        -------
        xr.Dataset
            Dataset containing VOD and angular coordinates.

        Raises
        ------
        ValueError
            If all delta SNR values are NaN.
        """
        start_time = time.time()
        log.info(
            "vod_calculation_started",
            canopy_epochs=len(self.canopy_ds.epoch),
            sky_epochs=len(self.sky_ds.epoch),
            sids=len(self.canopy_ds.sid),
        )

        delta_snr = self.get_delta_snr()

        # Lazy (dask-backed) inputs stay lazy so that a single write triggers
        # the VOD computation; only the two input checks below are computed.
        _lazy = delta_snr.chunks is not None

        canopy_transmissivity = self.decibel2linear(delta_snr)

        # Both checks in one pass; for lazy inputs this reads only the two
        # SNR variables, not the full datasets.
        checks = xr.Dataset(
            {
                "all_nan": delta_snr.isnull().all(),
                "n_invalid": (canopy_transmissivity <= 0).sum(),
            }
        ).compute()

        if bool(checks["all_nan"]):
            log.error("vod_calculation_failed", reason="all_delta_snr_nan")
            raise ValueError(
                "All delta_snr values are NaN - check data alignment",
            )

        n_invalid = int(checks["n_invalid"])
        if n_invalid > 0:
            total = canopy_transmissivity.size
            log.warning(
                "invalid_transmissivity",
                invalid_count=n_invalid,
                total_count=total,
                percent=round(100 * n_invalid / total, 2),
            )

        theta = self.canopy_ds["theta"]
        vod = -np.log(canopy_transmissivity) * np.cos(theta)

        # Grid cells assigned before the store write (processing.preprocessing)
        cell_ids = {
            name: self.canopy_ds[name]
            for name in self.canopy_ds.data_vars
            if str(name).startswith("cell_id_")
        }
        vod_ds = xr.Dataset(
            {
                "VOD": vod.drop_attrs(deep=False).assign_attrs(VOD_ATTRS),
                "delta_snr": delta_snr.drop_attrs(deep=False).assign_attrs(
                    DELTA_SNR_ATTRS
                ),
                "phi": self.canopy_ds["phi"],
                "theta": self.canopy_ds["theta"],
                **cell_ids,
            },
            coords=self.canopy_ds.coords,
        )

        duration = time.time() - start_time
        if not _lazy:
            n_valid = int((~vod.isnull()).sum())
            log.info(
                "vod_calculation_complete",
                duration_seconds=round(duration, 2),
                vod_values=vod.size,
                valid_values=n_valid,
                valid_percent=round(100 * n_valid / vod.size, 2),
            )
        else:
            log.info(
                "vod_calculation_complete",
                duration_seconds=round(duration, 2),
                vod_values=vod.size,
                note="lazy graph built; compute deferred to write",
            )

        return vod_ds
