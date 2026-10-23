"""Utility functions for RINEX readers."""

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from canvod.utils import tools
from canvod.utils.tools import deprecated


def get_version_from_pyproject(pyproject_path: Path | None = None) -> str:
    """Get the installed version of canvod-readers.

    Parameters
    ----------
    pyproject_path : Path, optional
        Ignored. Kept for backwards compatibility.

    Returns
    -------
    str
        Version string from installed package metadata, or ``"unknown"``
        if the package is not installed in the active environment.

    """
    try:
        return version("canvod-readers")
    except PackageNotFoundError:
        return "unknown"


@deprecated(
    "`canvod.readers.gnss_specs.utils.file_hash` is left over from development "
    "and will be removed with the next major version. Use "
    "`canvod.utils.tools.file_hash` instead."
)
def file_hash(path: Path, chunk_size: int = 8192) -> str:
    """Compute the file hash (first 16 hex digits of its SHA-256).

    Parameters
    ----------
    path : Path
        Path to GNSS data file.
    chunk_size : int, optional
        Chunk size for reading file in bytes. Default is 8192.

    Returns
    -------
    str
        First 16 characters of SHA256 hex digest.

    """
    return tools.file_hash(path, chunk_size)


@deprecated(
    "`canvod.readers.gnss_specs.utils.isfloat` is left over from development "
    "and will be removed with the next major version. Use "
    "`canvod.utils.tools.isfloat` instead."
)
def isfloat(value: str) -> bool:
    """Check if a string value can be converted to float.

    Parameters
    ----------
    value : str
        String to check for float convertibility.

    Returns
    -------
    bool
        True if convertible to float, False otherwise.

    """
    return tools.isfloat(value)
