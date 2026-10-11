"""CLK format reader.

This module provides the main ClkFile class for handling GNSS clock files
in CLK format, integrated with the product registry for multi-agency support.
"""

from pathlib import Path

import numpy as np
import xarray as xr
from canvod.utils.tools import get_gps_week_from_filename
from pydantic import ConfigDict
from pydantic.dataclasses import dataclass

from canvod.auxiliary._internal.units import UREG
from canvod.auxiliary.clock.parser import parse_clk_file
from canvod.auxiliary.clock.validator import validate_clk_dataset
from canvod.auxiliary.core.base import AuxFile
from canvod.auxiliary.interpolation import (
    ClockConfig,
    ClockInterpolationStrategy,
    Interpolator,
)
from canvod.auxiliary.products.registry_config import get_product_spec


@dataclass(config=ConfigDict(arbitrary_types_allowed=True))
class ClkFile(AuxFile):
    """Handler for GNSS clock files in CLK format.

    This class reads and processes clock offset files containing satellite clock
    corrections. It handles the parsing of CLK format files and provides the data
    in xarray Dataset format.

    Supports multiple analysis centers via product registry with proper FTP paths
    and filename conventions.

    Notes
    -----
    This is a Pydantic dataclass with `arbitrary_types_allowed=True`.

    Attributes
    ----------
    date : str
        String in YYYYDOY format representing the start date.
    agency : str
        Analysis center identifier (e.g., "COD", "GFZ").
    product_type : str
        Product type ("final" or "rapid").
    ftp_server : str
        Base URL for file downloads.
    local_dir : Path
        Local storage directory.
    dimensionless : bool | None, default True
        If True, outputs magnitude-only values (no units attached).
    """

    date: str
    agency: str
    product_type: str
    ftp_server: str
    local_dir: Path
    dimensionless: bool | None = True

    def __post_init__(self) -> None:
        """Initialize CLK file handler."""
        self.file_type = ["clock"]
        self.local_dir = Path(self.local_dir)
        self.local_dir.mkdir(parents=True, exist_ok=True)
        super().__post_init__()

    def get_interpolation_strategy(self) -> Interpolator:
        """Get appropriate interpolation strategy for CLK files."""
        config = ClockConfig(
            window_size=9,
            jump_threshold=1e-6,
        )
        return ClockInterpolationStrategy(config=config)

    def candidate_filenames(self) -> list[str]:
        """CLK file names, one per sampling the product has been published with.

        Filename format: {PREFIX}_{YYYYDOY}0000_01D_{SAMPLING}_CLK.CLK

        Raises
        ------
        UnknownProductError
            If agency/product combination not in registry.
        ValueError
            If the product publishes no clock files.
        """
        spec = get_product_spec(self.agency, self.product_type)
        if not spec.has_clock:
            msg = (
                f"{self.agency}/{self.product_type} publishes no clock files. "
                "Set processing.aux_data.fetch_clock to false, or choose a "
                "product with clocks."
            )
            raise ValueError(msg)
        return spec.clk_filenames(self.date)

    def download_aux_file(self, filename: str) -> None:
        """Download one CLK file, trying all servers from the product registry.

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
            If file cannot be downloaded from any available server.
        ValueError
            If GPS week calculation fails.
        """
        clock_file = Path(filename)
        gps_week = get_gps_week_from_filename(clock_file)

        spec = get_product_spec(self.agency, self.product_type)
        ftp_path = spec.ftp_path_pattern.format(
            gps_week=gps_week,
            file=f"{clock_file}.gz",
        )
        destination = self.local_dir / clock_file
        file_info = {
            "gps_week": gps_week,
            "filename": clock_file,
            "type": "clock",
            "agency": self.agency,
        }

        self.download_with_fallback(ftp_path, destination, file_info, spec)
        print(f"Downloaded clock file for {self.agency} on date {self.date}")

    def read_file(self) -> xr.Dataset:
        """Read and parse CLK file into xarray Dataset.

        Uses modular parser for data extraction and validator for quality checks.
        The clock bias is in seconds (RINEX clock 3.04, Table A16).

        Returns
        -------
        xr.Dataset
            Clock offsets with dimensions (epoch, sv). Values are in seconds
            (or dimensionless if specified).
        """
        # Parse file using modular parser
        assert self.fpath is not None, "fpath must be set before calling read_file"
        epochs, satellites, clock_offsets = parse_clk_file(self.fpath)

        clock_offsets = UREG.second * clock_offsets

        if self.dimensionless:
            clock_offsets = clock_offsets.magnitude

        # Create dataset
        ds = xr.Dataset(
            data_vars={"clock_offset": (("epoch", "sv"), clock_offsets)},
            coords={
                "epoch": np.array(epochs, dtype="datetime64[ns]"),
                "sv": np.array(satellites),
            },
        )

        # Validate and add metadata
        validation = validate_clk_dataset(ds)
        ds = self._prepare_dataset(ds, validation)

        return ds

    def _prepare_dataset(self, ds: xr.Dataset, validation: dict) -> xr.Dataset:
        """Add metadata and attributes to dataset.

        Parameters
        ----------
        ds : xr.Dataset
            Dataset from parsing.
        validation : dict
            Validation results dictionary.

        Returns
        -------
        xr.Dataset
            Dataset with complete metadata.
        """
        assert self.fpath is not None, (
            "fpath must be set \
            before calling _prepare_dataset"
        )
        ds.attrs = {
            "file": str(self.fpath.name),
            "agency": self.agency,
            "product_type": self.product_type,
            "ftp_server": self.ftp_server,
            "date": self.date,
            "valid_data_percent": validation["valid_data_percent"],
            "num_epochs": validation["num_epochs"],
            "num_satellites": validation["num_satellites"],
        }

        # Add variable attributes
        ds.clock_offset.attrs = {
            "long_name": "Satellite clock offset",
            "units": "seconds",
            "description": "Clock correction for each satellite",
        }

        return ds
