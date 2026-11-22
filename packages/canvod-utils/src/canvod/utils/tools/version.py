"""Version utilities for canVODpy packages."""

import tomllib
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _installed_version
from pathlib import Path

from .deprecation import deprecated


def canvodpy_version() -> str:
    """The version of canvodpy installed, which commit messages, commit
    metadata and the ``Software`` attribute name.

    canvodpy's packages are released separately, so their versions differ;
    this reads the canvodpy distribution's metadata, without importing
    canvodpy. ``"unknown"`` when canvodpy is not installed (a package of it
    used alone).
    """
    try:
        return _installed_version("canvodpy")
    except PackageNotFoundError:
        return "unknown"


@deprecated(
    "`get_version_from_pyproject` returns the version of canvod-utils, not "
    "that of canvodpy, and will be removed with the next major version. "
    "Use `canvodpy_version` instead."
)
def get_version_from_pyproject(pyproject_path: Path | None = None) -> str:
    """
    Get the installed canvod-utils package version.

    Tries `importlib.metadata` first, which resolves correctly for any
    install type (wheel, sdist, or editable). Falls back to walking up
    from this file's location looking for a `pyproject.toml` -- this only
    ever succeeds inside an editable/dev source checkout, since a built
    wheel's site-packages never ships pyproject.toml. Without the
    importlib.metadata path first, every store write from a non-editable
    install (a real PyPI release, or a git-sourced install like the demo
    notebooks use) raised FileNotFoundError here, since callers pass no
    explicit pyproject_path and expect this to just work.

    Parameters
    ----------
    pyproject_path : Path, optional
        Path to pyproject.toml. If None, resolved automatically as
        described above.

    Returns
    -------
    str
        Version string.

    Examples
    --------
    >>> version = get_version_from_pyproject()
    >>> print(version)  # e.g., "0.1.0"
    """
    if pyproject_path is None:
        try:
            return _installed_version("canvod-utils")
        except PackageNotFoundError:
            pass

        # Automatically find pyproject.toml at package root
        # Start from this file and go up until we find pyproject.toml
        current = Path(__file__).resolve()
        for parent in current.parents:
            candidate = parent / "pyproject.toml"
            if candidate.exists():
                pyproject_path = candidate
                break

        if pyproject_path is None:
            msg = "Could not find pyproject.toml"
            raise FileNotFoundError(msg)

    with open(pyproject_path, "rb") as f:
        data = tomllib.load(f)

    return data["project"]["version"]
