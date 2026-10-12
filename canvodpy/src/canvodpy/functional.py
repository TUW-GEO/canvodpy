"""
Functional API for VOD workflow.

.. deprecated::
    Left over from development and removed with the next major version.
    It is no longer maintained and gives different results than
    ``canvodpy run``: it reads without the configured observables and
    signals, and skips the configured VOD output options.
    Use the terminal command ``canvodpy run`` or ``canvodpy.Site`` instead.

Provides pure functions for Airflow integration and interactive use.
Two versions of each function:
- `func()` - Returns data (xr.Dataset)
- `func_to_file()` - Returns path (str) for Airflow XCom

Examples
--------
Interactive notebook:

    >>> from canvodpy.functional import read_rinex, calculate_vod
    >>> data = read_rinex("data.rnx")
    >>> vod = calculate_vod(canopy_data, sky_data)

Airflow DAG:

    >>> from airflow.decorators import task, dag
    >>> from canvodpy.functional import (
    ...     read_rinex_to_file,
    ...     calculate_vod_to_file,
    ... )
    >>>
    >>> @task
    >>> def process():
    ...     canopy = read_rinex_to_file("canopy.rnx", "/tmp/canopy.nc")
    ...     sky = read_rinex_to_file("sky.rnx", "/tmp/sky.nc")
    ...     vod = calculate_vod_to_file(canopy, sky, "/tmp/vod.nc")
    ...     return vod
"""

from __future__ import annotations

import warnings
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import structlog
import xarray as xr

from canvod.utils.tools import deprecated
from canvodpy.factories import GridFactory, ReaderFactory, VODFactory

log = structlog.get_logger(__name__)


@contextmanager
def _nested_deprecation_silenced() -> Generator[None]:
    """Warn once per call: the *_to_file versions call deprecated functions."""
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", ".*left over from development", FutureWarning)
        yield


# ============================================================================
# Data-returning versions (for notebooks, local scripts)
# ============================================================================


@deprecated(
    "canvodpy.functional.read_rinex() is left over from development and "
    "will be removed with the next major version. It is no longer "
    "maintained and gives different results than `canvodpy run`, because it"
    " reads without the configured observables and signals. Use the "
    "terminal command `canvodpy run` or "
    "canvodpy.Site(<site>).pipeline().process_date(<date>) instead."
)
def read_rinex(
    path: str | Path,
    reader: str = "rinex3",
    **reader_kwargs: Any,
) -> xr.Dataset:
    """
    Read RINEX file using registered reader.

    Parameters
    ----------
    path : str or Path
        Path to RINEX file
    reader : str, default="rinex3"
        Registered reader name from ReaderFactory
    **reader_kwargs : Any
        Additional reader-specific parameters

    Returns
    -------
    xr.Dataset
        RINEX data with variables (SNR, azimuth, elevation, etc.)

    Examples
    --------
    >>> data = read_rinex("ROSA0010.25o")
    >>> print(data.data_vars)
    Data variables: SNR, azimuth, elevation, ...

    With custom reader:

    >>> data = read_rinex("data.rnx", reader="custom_reader")

    Notes
    -----
    Pure function - stateless, no side effects.
    Uses ReaderFactory for extensibility.
    """
    log.info("read_rinex", path=str(path), reader=reader)

    reader_obj = ReaderFactory.create(
        reader,
        fpath=path,
        **reader_kwargs,
    )

    ds = reader_obj.to_ds(write_global_attrs=True)
    log.info("read_rinex_complete", variables=len(ds.data_vars))
    return ds


@deprecated(
    "canvodpy.functional.augment_with_ephemeris() is left over from "
    "development and will be removed with the next major version. It is no "
    "longer maintained. Use the terminal command `canvodpy run` or "
    "canvodpy.Site(<site>).pipeline().process_date(<date>) instead."
)
def augment_with_ephemeris(
    ds: xr.Dataset,
    receiver_position: Any,
    source: str = "final",
    agency: str = "COD",
    date: str | None = None,
    site_config: Any = None,
    aux_data_dir: str | Path | None = None,
    **kwargs: Any,
) -> xr.Dataset:
    """Augment dataset with theta/phi from ephemeris data.

    Parameters
    ----------
    ds : xr.Dataset
        GNSS observation dataset with ``(epoch, sid)`` dims.
    receiver_position
        Receiver ECEF position (``ECEFPosition`` or compatible).
    source : str
        Ephemeris source: ``"final"`` (SP3/CLK), ``"rapid"``,
        ``"broadcast"`` (SBF only).
    agency : str
        Analysis center for SP3/CLK products.
    date : str, optional
        Date in ``YYYYDOY`` format.  Required for ``"final"``/``"rapid"``.
    site_config : optional
        Site configuration for aux data paths.
    aux_data_dir : str or Path, optional
        Directory for cached aux data.
    **kwargs
        Forwarded to the provider.

    Returns
    -------
    xr.Dataset
        Dataset with ``theta`` and ``phi`` added.
    """
    from canvod.auxiliary.ephemeris.provider import (
        AgencyEphemerisProvider,
        SbfBroadcastProvider,
    )

    log.info("augment_with_ephemeris", source=source, agency=agency)

    if source in ("final", "rapid"):
        provider = AgencyEphemerisProvider(
            agency=agency,
            product_type=source,
            aux_data_dir=Path(aux_data_dir) if aux_data_dir else None,
            **kwargs,
        )
        if date is not None:
            provider.preprocess_day(date, site_config)
        return provider.augment_dataset(ds, receiver_position)

    if source == "broadcast":
        provider = SbfBroadcastProvider(**kwargs)
        return provider.augment_dataset(ds, receiver_position)

    raise ValueError(f"Unknown ephemeris source: {source!r}")


@deprecated(
    "canvodpy.functional.create_grid() is left over from development and "
    "will be removed with the next major version. It is no longer "
    "maintained. Use canvod.grids.create_hemigrid() instead."
)
def create_grid(
    grid_type: str = "equal_area",
    **grid_params: Any,
) -> Any:  # Returns GridData
    """
    Create hemisphere grid using registered builder.

    Parameters
    ----------
    grid_type : str, default="equal_area"
        Registered grid type from GridFactory
    **grid_params : Any
        Grid parameters:
        - angular_resolution : float
        - cutoff_theta : float
        - phi_rotation : float

    Returns
    -------
    GridData
        Grid structure with cells, vertices, metadata

    Examples
    --------
    >>> grid = create_grid("equal_area", angular_resolution=5.0)
    >>> print(grid.ncells)
    1296

    With cutoff:

    >>> grid = create_grid(
    ...     "equal_area",
    ...     angular_resolution=10.0,
    ...     cutoff_theta=75.0,
    ... )

    Notes
    -----
    Pure function - stateless, deterministic.
    Uses GridFactory for extensibility.
    """
    log.info("create_grid", grid_type=grid_type, params=grid_params)

    builder = GridFactory.create(grid_type, **grid_params)
    grid = builder.build()

    log.info("create_grid_complete", ncells=grid.ncells)
    return grid


@deprecated(
    "canvodpy.functional.assign_grid_cells() is left over from development "
    "and will be removed with the next major version. It is no longer "
    "maintained. Use canvod.grids.add_cell_ids_to_ds_fast() instead."
)
def assign_grid_cells(
    ds: xr.Dataset,
    grid: Any,  # GridData
    grid_name: str = "equal_area",
) -> xr.Dataset:
    """
    Assign grid cells to observations.

    Parameters
    ----------
    ds : xr.Dataset
        Dataset with phi, theta coordinates
    grid : GridData
        Grid structure from create_grid()
    grid_name : str, default="equal_area"
        Grid identifier for the output coordinate name.

    Returns
    -------
    xr.Dataset
        Dataset with added 'cell' coordinate

    Examples
    --------
    >>> grid = create_grid("equal_area")
    >>> ds_with_cells = assign_grid_cells(data, grid)
    >>> print(ds_with_cells.sizes)
    {'epoch': 2880, 'sv': 32, 'cell': 324}

    Notes
    -----
    Pure function - no side effects on input.
    Each observation gets the cell that contains it.
    """
    log.info("assign_grid_cells")

    from canvod.grids import add_cell_ids_to_ds_fast

    ds_with_cells = add_cell_ids_to_ds_fast(ds, grid, grid_name)

    log.info(
        "assign_grid_cells_complete",
        cells=ds_with_cells.sizes.get("cell", 0),
    )
    return ds_with_cells


@deprecated(
    "canvodpy.functional.calculate_vod() is left over from development and "
    "will be removed with the next major version. It is no longer "
    "maintained and gives different results than `canvodpy run`, because it"
    " skips the configured VOD output options. Use the terminal command "
    "`canvodpy run` or canvodpy.Site(<site>).vod.compute_day(<datasets>, "
    "<analysis>) instead."
)
def calculate_vod(
    canopy_ds: xr.Dataset,
    sky_ds: xr.Dataset,
    calculator: str = "tau_omega",
    **calc_kwargs: Any,
) -> xr.Dataset:
    """
    Calculate VOD from canopy and sky datasets.

    Parameters
    ----------
    canopy_ds : xr.Dataset
        Canopy receiver data with SNR variable
    sky_ds : xr.Dataset
        Sky reference data with SNR variable
    calculator : str, default="tau_omega"
        Registered calculator name from VODFactory
    **calc_kwargs : Any
        Additional calculator-specific parameters

    Returns
    -------
    xr.Dataset
        VOD results with variables:
        - VOD : Vegetation Optical Depth
        - phi : Azimuth angles
        - theta : Elevation angles

    Examples
    --------
    >>> vod = calculate_vod(canopy_data, sky_data)
    >>> print(vod.VOD.mean().item())
    0.42

    With custom calculator:

    >>> vod = calculate_vod(
    ...     canopy_data,
    ...     sky_data,
    ...     calculator="ml_vod",
    ...     model_path="model.pt",
    ... )

    Notes
    -----
    Pure function - deterministic for same inputs.
    Uses VODFactory for extensibility.
    """
    log.info("calculate_vod", calculator=calculator)

    calc = VODFactory.create(
        calculator,
        canopy_ds=canopy_ds,
        sky_ds=sky_ds,
        **calc_kwargs,
    )

    vod_ds = calc.calculate_vod()

    log.info("calculate_vod_complete")
    return vod_ds


# ============================================================================
# Path-returning versions (for Airflow XCom)
# ============================================================================


@deprecated(
    "canvodpy.functional.read_rinex_to_file() is left over from development"
    " and will be removed with the next major version. It is no longer "
    "maintained and gives different results than `canvodpy run`, because it"
    " reads without the configured observables and signals. Use the "
    "terminal command `canvodpy run` or "
    "canvodpy.Site(<site>).pipeline().process_date(<date>) instead."
)
def read_rinex_to_file(
    rinex_path: str | Path,
    output_path: str | Path,
    reader: str = "rinex3",
    **reader_kwargs: Any,
) -> str:
    """
    Read RINEX and save to NetCDF file (Airflow-compatible).

    Parameters
    ----------
    rinex_path : str or Path
        Path to RINEX file
    output_path : str or Path
        Path for output NetCDF file
    reader : str, default="rinex3"
        Registered reader name
    **reader_kwargs : Any
        Additional reader parameters

    Returns
    -------
    str
        Path to output file (for Airflow XCom)

    Examples
    --------
    Airflow task:

        >>> from airflow.decorators import task
        >>>
        >>> @task
        >>> def load_rinex():
        ...     return read_rinex_to_file(
        ...         "ROSA0010.25o",
        ...         "/tmp/rinex.nc"
        ...     )

    Notes
    -----
    Suitable for use in Airflow tasks with @task decorator.
    Returns path string that can be serialized in XCom.
    """
    log.info("read_rinex_to_file", rinex=str(rinex_path), output=str(output_path))

    # Use data-returning version
    with _nested_deprecation_silenced():
        ds = read_rinex(rinex_path, reader, **reader_kwargs)

    # Save to file
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    ds.to_netcdf(output_path)

    log.info("read_rinex_to_file_complete", path=str(output_path))
    return str(output_path)


@deprecated(
    "canvodpy.functional.create_grid_to_file() is left over from "
    "development and will be removed with the next major version. It is no "
    "longer maintained. Use canvod.grids.create_hemigrid() instead."
)
def create_grid_to_file(
    output_path: str | Path,
    grid_type: str = "equal_area",
    **grid_params: Any,
) -> str:
    """
    Create grid and save to file (Airflow-compatible).

    Parameters
    ----------
    output_path : str or Path
        Path for output grid file
    grid_type : str, default="equal_area"
        Registered grid type
    **grid_params : Any
        Grid parameters

    Returns
    -------
    str
        Path to output file (for Airflow XCom)

    Examples
    --------
    Airflow task:

        >>> @task
        >>> def make_grid():
        ...     return create_grid_to_file(
        ...         "/tmp/grid.pkl",
        ...         "equal_area",
        ...         angular_resolution=5.0,
        ...     )

    Notes
    -----
    Grid is saved as pickle for full structure preservation.
    """
    log.info("create_grid_to_file", output=str(output_path))

    # Create grid
    with _nested_deprecation_silenced():
        grid = create_grid(grid_type, **grid_params)

    # Save to file
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Serialize grid to file (pickle for file-based Airflow tasks)
    import pickle

    with open(output_path, "wb") as f:
        pickle.dump(grid, f)

    log.info("create_grid_to_file_complete", path=str(output_path))
    return str(output_path)


@deprecated(
    "canvodpy.functional.assign_grid_cells_to_file() is left over from "
    "development and will be removed with the next major version. It is no "
    "longer maintained. Use canvod.grids.add_cell_ids_to_ds_fast() instead."
)
def assign_grid_cells_to_file(
    data_path: str | Path,
    grid_path: str | Path,
    output_path: str | Path,
) -> str:
    """
    Assign grid cells and save to file (Airflow-compatible).

    Parameters
    ----------
    data_path : str or Path
        Path to input NetCDF file
    grid_path : str or Path
        Path to grid file
    output_path : str or Path
        Path for output file

    Returns
    -------
    str
        Path to output file (for Airflow XCom)

    Examples
    --------
    Airflow task:

        >>> @task
        >>> def assign_cells(data_path, grid_path):
        ...     return assign_grid_cells_to_file(
        ...         data_path,
        ...         grid_path,
        ...         "/tmp/with_cells.nc",
        ...     )

    Notes
    -----
    Chains with other *_to_file functions for Airflow pipelines.
    """
    log.info(
        "assign_grid_cells_to_file",
        data=str(data_path),
        grid=str(grid_path),
        output=str(output_path),
    )

    # Load datasets
    ds = xr.open_dataset(data_path)

    # Load grid from file (pickle for file-based Airflow tasks)
    import pickle

    with open(grid_path, "rb") as f:
        grid = pickle.load(f)

    # Assign cells
    with _nested_deprecation_silenced():
        ds_with_cells = assign_grid_cells(ds, grid)

    # Save to file
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    ds_with_cells.to_netcdf(output_path)

    log.info("assign_grid_cells_to_file_complete", path=str(output_path))
    return str(output_path)


@deprecated(
    "canvodpy.functional.calculate_vod_to_file() is left over from "
    "development and will be removed with the next major version. It is no "
    "longer maintained and gives different results than `canvodpy run`, "
    "because it skips the configured VOD output options. Use the terminal "
    "command `canvodpy run` or "
    "canvodpy.Site(<site>).vod.compute_day(<datasets>, <analysis>) instead."
)
def calculate_vod_to_file(
    canopy_path: str | Path,
    sky_path: str | Path,
    output_path: str | Path,
    calculator: str = "tau_omega",
    **calc_kwargs: Any,
) -> str:
    """
    Calculate VOD and save to file (Airflow-compatible).

    Parameters
    ----------
    canopy_path : str or Path
        Path to canopy NetCDF file
    sky_path : str or Path
        Path to sky NetCDF file
    output_path : str or Path
        Path for output VOD file
    calculator : str, default="tau_omega"
        Registered calculator name
    **calc_kwargs : Any
        Additional calculator parameters

    Returns
    -------
    str
        Path to output file (for Airflow XCom)

    Examples
    --------
    Airflow task:

        >>> @task
        >>> def compute_vod(canopy_path, sky_path):
        ...     return calculate_vod_to_file(
        ...         canopy_path,
        ...         sky_path,
        ...         "/tmp/vod.nc"
        ...     )

    Complete DAG:

        >>> from airflow import DAG
        >>> from airflow.decorators import task
        >>>
        >>> @task
        >>> def pipeline():
        ...     canopy = read_rinex_to_file("c.rnx", "/tmp/c.nc")
        ...     sky = read_rinex_to_file("s.rnx", "/tmp/s.nc")
        ...     vod = calculate_vod_to_file(canopy, sky, "/tmp/vod.nc")
        ...     return vod

    Notes
    -----
    All *_to_file functions return str paths for XCom.
    Chain them in Airflow tasks for complete pipelines.
    """
    log.info(
        "calculate_vod_to_file",
        canopy=str(canopy_path),
        sky=str(sky_path),
        output=str(output_path),
    )

    # Load datasets
    canopy_ds = xr.open_dataset(canopy_path)
    sky_ds = xr.open_dataset(sky_path)

    # Calculate VOD
    with _nested_deprecation_silenced():
        vod_ds = calculate_vod(canopy_ds, sky_ds, calculator, **calc_kwargs)

    # Save to file
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    vod_ds.to_netcdf(output_path)

    log.info("calculate_vod_to_file_complete", path=str(output_path))
    return str(output_path)
