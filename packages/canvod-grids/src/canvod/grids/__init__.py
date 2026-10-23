"""HEALPix and hemispheric grid operations.

Provides hemisphere grid structures for GNSS signal observation analysis.
"""

from importlib.metadata import version as _version
from typing import Any, Literal

from canvod.grids.aggregation import (
    CellAggregator,
    aggregate_data_to_grid,
    analyze_diurnal_patterns,
    analyze_spatial_patterns,
    compute_global_average,
    compute_hemisphere_percell,
    compute_percell_timeseries,
    compute_regional_average,
    compute_zenith_percell,
)
from canvod.grids.core import BaseGridBuilder, GridData, GridType
from canvod.grids.grids_impl import (
    EqualAngleBuilder,
    EqualAreaBuilder,
    EquirectangularBuilder,
    FibonacciBuilder,
    GeodesicBuilder,
    HEALPixBuilder,
    HTMBuilder,
)
from canvod.grids.operations import (
    add_cell_ids_to_ds_fast,
    add_cell_ids_to_vod,
    add_cell_ids_to_vod_fast,
    extract_grid_vertices,
    grid_to_dataset,
    load_grid,
    store_dataset_with_cell_ids,
    store_grid,
)

__version__ = _version("canvod-grids")

__all__ = [
    "GRID_BUILDERS",
    # Core
    "BaseGridBuilder",
    # Aggregation
    "CellAggregator",
    # Builders
    "EqualAngleBuilder",
    "EqualAreaBuilder",
    "EquirectangularBuilder",
    "FibonacciBuilder",
    "GeodesicBuilder",
    "GridData",
    "GridType",
    "HEALPixBuilder",
    "HTMBuilder",
    # Version
    "__version__",
    # Operations
    "add_cell_ids_to_ds_fast",
    "add_cell_ids_to_vod",
    "add_cell_ids_to_vod_fast",
    "aggregate_data_to_grid",
    "analyze_diurnal_patterns",
    "analyze_spatial_patterns",
    "compute_global_average",
    "compute_hemisphere_percell",
    "compute_percell_timeseries",
    "compute_regional_average",
    "compute_zenith_percell",
    "create_hemigrid",
    "extract_grid_vertices",
    "grid_to_dataset",
    "load_grid",
    "store_dataset_with_cell_ids",
    "store_grid",
]

#: The builder of each grid type. :func:`create_hemigrid` and canvodpy's
#: ``GridFactory`` both take the builders from here.
GRID_BUILDERS: dict[GridType, type[BaseGridBuilder]] = {
    GridType.EQUAL_AREA: EqualAreaBuilder,
    GridType.EQUAL_ANGLE: EqualAngleBuilder,
    GridType.EQUIRECTANGULAR: EquirectangularBuilder,
    GridType.HTM: HTMBuilder,
    GridType.GEODESIC: GeodesicBuilder,
    GridType.HEALPIX: HEALPixBuilder,
    GridType.FIBONACCI: FibonacciBuilder,
}


def create_hemigrid(
    grid_type: Literal[
        "equal_area",
        "equal_angle",
        "rectangular",
        "equirectangular",
        "HTM",
        "geodesic",
        "healpix",
        "fibonacci",
    ],
    angular_resolution: float = 10.0,
    **kwargs: Any,
) -> GridData:
    """Create hemisphere grid of specified type.

    Factory function for creating various hemisphere grid types commonly
    used in GNSS analysis.

    Parameters
    ----------
    grid_type : str
        Type of grid to create:
        - 'equal_area': Regular lat/lon grid with equal solid angle cells
        - 'equal_angle': Regular angular spacing (not recommended)
        - 'rectangular' or 'equirectangular': Simple rectangular grid
        - 'HTM': Hierarchical Triangular Mesh
        - 'geodesic': Geodesic sphere subdivision (icosahedron-based)
        - 'healpix': HEALPix grid (requires healpy)
        - 'fibonacci': Fibonacci sphere (requires scipy)
    angular_resolution : float, default 10.0
        Angular resolution in degrees
    **kwargs
        Additional grid-specific parameters:
        - cutoff_theta : float - Maximum theta angle cutoff (degrees)
        - phi_rotation : float - Rotation angle (degrees)
        - subdivision_level : int - For geodesic/HTM grids
        - htm_level : int - For HTM grids specifically
        - nside : int - For HEALPix grids
        - n_points : int - For Fibonacci grids

    Returns
    -------
    GridData
        Complete hemisphere grid data structure

    Examples
    --------
    >>> # Equal area grid with 10° resolution
    >>> grid = create_hemigrid('equal_area', angular_resolution=10.0)
    >>>
    >>> # HTM grid with subdivision level 3
    >>> grid = create_hemigrid('HTM', angular_resolution=5.0, htm_level=3)
    >>>
    >>> # Geodesic grid
    >>> grid = create_hemigrid('geodesic', angular_resolution=5.0, subdivision_level=2)

    Notes
    -----
    Grid coordinates use navigation convention:
    - phi: azimuth angle, 0 to 2π (0 = North, π/2 = East, clockwise)
    - theta: polar angle from zenith, 0 to π/2 (0 = zenith, π/2 = horizon)

    """
    name = grid_type.lower()
    if name == "rectangular":
        name = GridType.EQUIRECTANGULAR.value
    try:
        builder_class = GRID_BUILDERS[GridType(name)]
    except ValueError:
        available = ", ".join(t.value for t in GRID_BUILDERS)
        msg = (
            f"Unknown grid type: {grid_type}. "
            f"Available types: {available} (and rectangular for equirectangular)"
        )
        raise ValueError(msg) from None
    builder = builder_class(angular_resolution=angular_resolution, **kwargs)

    return builder.build()
