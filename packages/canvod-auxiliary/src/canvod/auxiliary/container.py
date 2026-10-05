"""Container classes for GNSS data."""

from pathlib import Path

import pandas as pd
import xarray as xr
from pydantic import ConfigDict
from pydantic.dataclasses import dataclass


@dataclass(config=ConfigDict(arbitrary_types_allowed=True))
class GnssData:
    """Container for GNSS data with optional tabular representation.

    Notes
    -----
    This is a Pydantic dataclass with `arbitrary_types_allowed=True`.

    Attributes
    ----------
    dataset : xr.Dataset
        Primary dataset.
    dataframe : pd.DataFrame, optional
        Optional tabular representation of the dataset.
    """

    dataset: xr.Dataset
    dataframe: pd.DataFrame | None = None


@dataclass
class FileMetadata:
    """Metadata required for GNSS auxiliary files.

    Notes
    -----
    This is a standard dataclass.

    Attributes
    ----------
    date : str
        Date in YYYYDOY format.
    agency : str
        Agency identifier (e.g., "COD", "IGS").
    product_type : str
        Product type ("final" or "rapid").
    local_dir : Path
        Local directory for storage.
    ftp_server : str
        FTP base URL.
    """

    date: str  # Format: YYYYDOY
    agency: str  # e.g., 'COD', 'IGS'
    product_type: str  # 'final' or 'rapid'
    local_dir: Path
    ftp_server: str
