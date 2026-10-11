"""SP3 orbit file reader with multi-product support."""

from pathlib import Path

import numpy as np
import xarray as xr
from pydantic import ConfigDict
from pydantic.dataclasses import dataclass

from canvod.auxiliary._internal import UREG, get_gps_week_from_filename
from canvod.auxiliary.core.base import DAY_JOIN_MARGIN, AuxFile
from canvod.auxiliary.ephemeris.parser import Sp3Parser
from canvod.auxiliary.ephemeris.validator import Sp3Validator
from canvod.auxiliary.interpolation import (
    Interpolator,
    Sp3Config,
    Sp3InterpolationStrategy,
)
from canvod.auxiliary.products.registry_config import ProductSpec, get_product_spec


@dataclass(config=ConfigDict(arbitrary_types_allowed=True))
class Sp3File(AuxFile):
    """Handler for SP3 orbit files with multi-product support.

    Now supports all IGS analysis centers via product registry:
    COD, GFZ, ESA, JPL, IGS, WHU, GRG, SHA

    Notes
    -----
    This is a Pydantic dataclass with `arbitrary_types_allowed=True`.

    Attributes
    ----------
    date : str
        String in YYYYDOY format.
    agency : str
        Agency code (e.g., "COD", "GFZ", "ESA").
    product_type : str
        Product type ("final", "rapid").
    ftp_server : str
        Base URL for downloads.
    local_dir : Path
        Local storage directory.
    add_velocities : bool | None, default True
        Whether to compute velocities.
    dimensionless : bool | None, default True
        Whether to strip units (store magnitudes only).
    product_spec : ProductSpec | None, optional
        Product specification resolved from the registry.
    """

    date: str
    agency: str
    product_type: str
    ftp_server: str
    local_dir: Path
    add_velocities: bool | None = True
    dimensionless: bool | None = True
    product_spec: ProductSpec | None = None

    def __post_init__(self) -> None:
        """Initialize with product validation."""
        self.file_type = ["orbit"]
        self.local_dir = Path(self.local_dir)
        self.local_dir.mkdir(parents=True, exist_ok=True)

        # Validate product exists in registry
        self.product_spec = get_product_spec(self.agency, self.product_type)

        super().__post_init__()

    def get_interpolation_strategy(self) -> Interpolator:
        """Get appropriate interpolation strategy for SP3 files."""
        config = Sp3Config(
            use_velocities=bool(self.add_velocities),
            fallback_method="linear",
        )
        return Sp3InterpolationStrategy(config=config)

    def candidate_filenames(self) -> list[str]:
        """SP3 file names, one per sampling the product has been published with.

        Pattern: {PREFIX}_{YYYYDOY}0000_01D_{SAMPLING}_ORB.SP3

        Example: COD0MGXFIN_20240150000_01D_05M_ORB.SP3
        """
        assert self.product_spec is not None, (
            "product_spec must be set via \
            __post_init__"
        )
        return self.product_spec.sp3_filenames(self.date)

    def download_aux_file(self, filename: str) -> None:
        """Download one SP3 file, trying all servers from the product registry.

        Servers are tried in priority order from products.toml. Auth-required
        servers are skipped when no credentials are configured. Warnings are
        printed when falling back to alternate servers.

        Parameters
        ----------
        filename : str
            One of :meth:`candidate_filenames`.

        Raises
        ------
        RuntimeError
            If download fails from all available servers.
        ValueError
            If GPS week calculation fails.
        """
        assert self.product_spec is not None, (
            "product_spec must be set via \
            __post_init__"
        )
        orbit_file = Path(filename)
        gps_week = get_gps_week_from_filename(orbit_file)

        ftp_path = self.product_spec.ftp_path_pattern.format(
            gps_week=gps_week,
            file=f"{orbit_file}.gz",
        )
        destination = self.local_dir / orbit_file
        file_info = {
            "gps_week": gps_week,
            "filename": orbit_file,
            "type": "orbit",
            "agency": self.agency,
        }

        self.download_with_fallback(ftp_path, destination, file_info, self.product_spec)
        print(f"Downloaded orbit file for {self.agency} on date {self.date}")

    def read_file(self) -> xr.Dataset:
        """Read and validate SP3 file.

        Returns
        -------
        xr.Dataset
            Dataset with satellite positions (X, Y, Z) in meters.

        Raises
        ------
        FileNotFoundError
            If file does not exist.
        ValueError
            If validation fails.
        """
        # Use dedicated parser
        assert self.fpath is not None, "fpath must be set before calling read_file"
        parser = Sp3Parser(self.fpath, dimensionless=bool(self.dimensionless))
        dataset = parser.parse()

        # Validate format
        validator = Sp3Validator(dataset, self.fpath)
        result = validator.validate()

        if not result.is_valid:
            raise ValueError(f"SP3 validation failed:\n{result.summary()}")

        # Add metadata
        dataset = self._add_metadata(dataset)

        # Compute velocities if requested
        if self.add_velocities:
            dataset = self.compute_velocity(dataset)

        return dataset

    def _add_metadata(self, ds: xr.Dataset) -> xr.Dataset:
        """Add file-level metadata to dataset."""
        assert self.fpath is not None, "fpath must be set before calling _add_metadata"
        assert self.product_spec is not None, (
            "product_spec must be set before \
            calling _add_metadata"
        )
        ds.attrs = {
            "file": str(self.fpath.name),
            "agency": self.agency,
            "agency_name": self.product_spec.agency_name,
            "product_type": self.product_type,
            "ftp_server": self.ftp_server,
            "date": self.date,
            "sampling_rate": self.fpath.name.split("_")[3],
            "duration": self.fpath.name.split("_")[2],
        }
        return ds

    def join_days(
        self,
        previous: AuxFile,
        following: AuxFile,
        margin: np.timedelta64 = DAY_JOIN_MARGIN,
    ) -> xr.Dataset:
        """Like :meth:`AuxFile.join_days`, with the velocities recomputed.

        The velocities of each file have one-sided differences at its first
        and last epoch; recomputed on the joined data, the day's first and
        last epochs get central differences.
        """
        joined = super().join_days(previous, following, margin)
        if self.add_velocities:
            joined = self.compute_velocity(joined)
        return joined

    def compute_velocity(self, ds: xr.Dataset) -> xr.Dataset:
        """Compute satellite velocities from position data.

        Uses central differences for interior points, forward/backward
        differences for endpoints, with the actual epoch spacing (the days
        joined by :meth:`join_days` may come with different samplings).

        Parameters
        ----------
        ds : xr.Dataset
            Dataset with X, Y, Z coordinates.

        Returns
        -------
        xr.Dataset
            Dataset augmented (or updated) with Vx, Vy, Vz velocities.
        """
        epochs = ds["epoch"].values
        t = (epochs - epochs[0]) / np.timedelta64(1, "s")
        dt = float(np.median(np.diff(t)))

        vx, vy, vz = (np.gradient(ds[c].values, t, axis=0, edge_order=1) for c in "XYZ")

        # Add units if needed
        if not self.dimensionless:
            vx = vx * (UREG.meter / UREG.second)
            vy = vy * (UREG.meter / UREG.second)
            vz = vz * (UREG.meter / UREG.second)

        # Add to dataset
        ds = ds.assign(
            Vx=(("epoch", "sv"), vx),
            Vy=(("epoch", "sv"), vy),
            Vz=(("epoch", "sv"), vz),
        )

        # Add velocity attributes
        for var, attrs in self._get_velocity_attributes(dt).items():
            if var in ds:
                ds[var].attrs = attrs

        return ds

    def _get_velocity_attributes(
        self,
        dt: float,
    ) -> dict[str, dict[str, str | float]]:
        """Get standardized attributes for velocity variables."""
        base_attrs = {
            "units": "m/s",
            "computation_method": "central_difference",
            "time_step": float(dt),
            "reference_frame": "ECEF",
        }

        return {
            "Vx": {
                "long_name": "x-component of velocity",
                "short_name": "v_x",
                "axis": "v_x",
                **base_attrs,
            },
            "Vy": {
                "long_name": "y-component of velocity",
                "short_name": "v_y",
                "axis": "v_y",
                **base_attrs,
            },
            "Vz": {
                "long_name": "z-component of velocity",
                "short_name": "v_z",
                "axis": "v_z",
                **base_attrs,
            },
        }
