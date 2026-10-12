"""Cell assignment and vertex extraction for hemisphere grids.

Functions in this module operate on :class:`~canvod.grids.core.GridData`
instances and VOD xarray Datasets.

Cell assignment
---------------
``add_cell_ids_to_ds_fast``    – the cell that contains each observation, eager or dask-lazy

Vertex / grid conversion
------------------------
``extract_grid_vertices``      – flat (x, y, z) arrays for 3-D visualization
``grid_to_dataset``            – xarray Dataset with vertices and solid angles
"""

from __future__ import annotations

from importlib.metadata import version
from typing import TYPE_CHECKING, Any

import numpy as np
import structlog
import xarray as xr

from canvod.grids._internal.cell_lookup import cell_lookup
from canvod.utils.tools import deprecated, deprecated_argument

if TYPE_CHECKING:
    from canvod.grids.core import GridData

log = structlog.get_logger(__name__)

# Per-grid-type description of what ``angular_resolution`` controls.
_RESOLUTION_DESCRIPTIONS: dict[str, str] = {
    "equal_area": (
        "Theta-band width in degrees; phi divisions adjusted so each cell "
        "subtends approximately the same solid angle."
    ),
    "equal_angle": (
        "Uniform spacing in both theta and phi in degrees "
        "(rectangular cells in angle space, unequal solid angles)."
    ),
    "htm": (
        "Approximate edge length of triangular HTM cells in degrees; "
        "mapped to an HTM subdivision level."
    ),
    "geodesic": (
        "Approximate edge length of geodesic triangular cells in degrees; "
        "mapped to an icosahedron subdivision level."
    ),
    "healpix": (
        "Approximate pixel diameter in degrees; "
        "mapped to a HEALPix nside parameter (power of 2)."
    ),
    "fibonacci": (
        "Approximate cell diameter in degrees; "
        "mapped to number of Fibonacci-sphere sample points."
    ),
}


# ==============================================================================
# Cell assignment
# ==============================================================================


@deprecated_argument(
    "data_var",
    "The data_var argument of add_cell_ids_to_ds_fast() is left over "
    "from development and will be removed with the next major version. "
    "Use add_cell_ids_to_ds_fast(ds, grid, grid_name) instead.",
)
def add_cell_ids_to_ds_fast(
    ds: xr.Dataset,
    grid: GridData,
    grid_name: str,
    data_var: str | None = None,
) -> xr.Dataset:
    """Assign every observation to the grid cell that contains it.

    Each grid type is looked up by its own cell boundaries: theta band and
    phi sector for ``equal_area``, ``equal_angle`` and ``equirectangular``;
    the spherical triangle for ``htm`` and ``geodesic``; the pixel for
    ``healpix``; the Voronoi cell for ``fibonacci``. Bands and sectors are
    closed at their inner edge and open at their outer edge; the last band
    also includes its outer edge.

    An observation outside the grid gets NaN: below the outer edge of the
    last band of a ring grid (the horizon, or ``90° - cutoff_theta``), or,
    for the triangle, pixel and Voronoi grids, in a cell the hemisphere
    filter left out (these grids keep a cell when its center lies above
    ``90° - cutoff_theta``, so their edge near the horizon is not a circle).

    ``phi`` and ``theta`` may be data variables (as the runs write them) or
    coordinates, with ``(epoch, sid)`` dimensions in either order. If they
    are dask arrays, the cell IDs are computed lazily, block by block.

    Parameters
    ----------
    ds : xr.Dataset
        Dataset with ``phi(epoch, sid)`` and ``theta(epoch, sid)`` in
        radians.
    grid : GridData
        Hemisphere grid built with ``create_hemigrid()``. A grid loaded with
        ``canvod.store.load_grid()`` works for the ring grids only; the others lose the
        geometry the lookup needs (ValueError).
    grid_name : str
        Grid identifier; the output variable is ``cell_id_<grid_name>``.

    Returns
    -------
    xr.Dataset
        *ds* with a ``cell_id_<grid_name>(epoch, sid)`` float64 data
        variable; NaN where ``phi`` or ``theta`` is not finite or the
        observation lies outside the grid.
    """
    import dask.array as da

    lookup = cell_lookup(grid)

    def _assign_block(phi_block: np.ndarray, theta_block: np.ndarray) -> np.ndarray:
        phi_flat = phi_block.ravel()
        theta_flat = theta_block.ravel()
        valid = np.isfinite(phi_flat) & np.isfinite(theta_flat)
        cell_ids = np.full(len(phi_flat), np.nan, dtype=np.float64)
        if np.any(valid):
            cell_ids[valid] = lookup(phi_flat[valid], theta_flat[valid])
        return cell_ids.reshape(phi_block.shape)

    phi = ds["phi"].transpose("epoch", "sid").data
    theta = ds["theta"].transpose("epoch", "sid").data
    if isinstance(phi, da.Array) or isinstance(theta, da.Array):
        theta = da.asarray(theta).rechunk(da.asarray(phi).chunks)
        cell_ids = da.map_blocks(
            _assign_block, da.asarray(phi), theta, dtype=np.float64
        )
    else:
        cell_ids = _assign_block(np.asarray(phi), np.asarray(theta))

    ds[f"cell_id_{grid_name}"] = (
        ("epoch", "sid"),
        cell_ids,
        {
            "long_name": f"Cell of the {grid_name} grid",
            "coverage_content_type": "referenceInformation",
        },
    )
    log.info(
        "cell_assignment_complete",
        grid_name=grid_name,
        grid_cells=grid.ncells,
        lazy=isinstance(cell_ids, da.Array),
    )
    return ds


@deprecated(
    "add_cell_ids_to_vod_fast() is left over from development and will be "
    "removed with the next major version. Use add_cell_ids_to_ds_fast() instead."
)
def add_cell_ids_to_vod_fast(
    vod_ds: xr.Dataset, grid: GridData, grid_name: str
) -> xr.Dataset:
    """Assign grid cells to a VOD dataset; see :func:`add_cell_ids_to_ds_fast`."""
    return add_cell_ids_to_ds_fast(vod_ds, grid, grid_name)


@deprecated(
    "add_cell_ids_to_vod() is left over from development and will be removed "
    "with the next major version. Use add_cell_ids_to_ds_fast() instead."
)
def add_cell_ids_to_vod(
    vod_ds: xr.Dataset, grid: GridData, grid_name: str
) -> xr.Dataset:
    """Assign grid cells to a VOD dataset; see :func:`add_cell_ids_to_ds_fast`."""
    return add_cell_ids_to_ds_fast(vod_ds, grid, grid_name)


# ==============================================================================
# Vertex extraction
# ==============================================================================


def extract_grid_vertices(grid: GridData) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Extract 3D vertices from hemisphere grid cells.

    Dispatches to a grid-type–specific extractor.  The returned arrays are
    flat (not per-cell); use them directly for 3-D scatter plots.

    Parameters
    ----------
    grid : GridData
        Hemisphere grid instance.

    Returns
    -------
    x_vertices, y_vertices, z_vertices : np.ndarray
        Cartesian vertex coordinates on the unit sphere.

    """
    extractors = {
        "htm": _extract_htm_vertices,
        "geodesic": _extract_geodesic_vertices,
        "equal_area": _extract_rectangular_vertices,
        "equal_angle": _extract_rectangular_vertices,
        "equirectangular": _extract_rectangular_vertices,
        "healpix": _extract_healpix_vertices,
        "fibonacci": _extract_fibonacci_vertices,
    }
    extractor = extractors.get(grid.grid_type)
    if extractor is None:
        raise ValueError(f"Unknown grid type: {grid.grid_type}")
    return extractor(grid)


def _extract_htm_vertices(
    grid: GridData,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Extract vertices from HTM triangular grid."""
    all_x, all_y, all_z = [], [], []

    for row in grid.grid.iter_rows(named=True):
        v0 = np.array(row["htm_vertex_0"])
        v1 = np.array(row["htm_vertex_1"])
        v2 = np.array(row["htm_vertex_2"])

        for vertex in [v0, v1, v2]:
            if vertex[2] >= -0.01:  # Small tolerance for numerical errors
                vertex[2] = max(vertex[2], 0.0)  # Clamp to hemisphere
                all_x.append(vertex[0])
                all_y.append(vertex[1])
                all_z.append(vertex[2])

    return np.array(all_x), np.array(all_y), np.array(all_z)


def _extract_rectangular_vertices(
    grid: GridData,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Extract vertices from rectangular grid cells.

    Supports equal_area, equal_angle, and equirectangular grids.
    """
    all_x, all_y, all_z = [], [], []

    for row in grid.grid.iter_rows(named=True):
        phi_min = row["phi_min"]
        phi_max = row["phi_max"]
        theta_min = row["theta_min"]
        theta_max = row["theta_max"]

        phi_corners = [phi_min, phi_max, phi_max, phi_min]
        theta_corners = [theta_min, theta_min, theta_max, theta_max]

        for phi, theta in zip(phi_corners, theta_corners):
            x = np.sin(theta) * np.cos(phi)
            y = np.sin(theta) * np.sin(phi)
            z = np.cos(theta)
            all_x.append(x)
            all_y.append(y)
            all_z.append(z)

    return np.array(all_x), np.array(all_y), np.array(all_z)


def _extract_geodesic_vertices(
    grid: GridData,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Extract vertices from geodesic grid triangles.

    Uses the shared vertex array and per-cell index column to return
    actual triangle vertices.  Falls back to cell centers if the shared
    vertex data is unavailable.
    """
    shared = grid.vertices  # (n_vertices, 3) from extra_kwargs
    if shared is not None and "geodesic_vertices" in grid.grid.columns:
        all_x, all_y, all_z = [], [], []
        for row in grid.grid.iter_rows(named=True):
            v_indices = np.array(row["geodesic_vertices"], dtype=int)
            for vi in v_indices:
                v = shared[vi]
                if v[2] >= -0.01:
                    all_x.append(v[0])
                    all_y.append(v[1])
                    all_z.append(max(v[2], 0.0))
        return np.array(all_x), np.array(all_y), np.array(all_z)

    # Fallback: cell centers
    phi_vals = grid.grid["phi"].to_numpy()
    theta_vals = grid.grid["theta"].to_numpy()
    x = np.sin(theta_vals) * np.cos(phi_vals)
    y = np.sin(theta_vals) * np.sin(phi_vals)
    z = np.cos(theta_vals)
    return x, y, z


def _extract_healpix_vertices(
    grid: GridData,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Extract vertices from HEALPix grid via healpy boundaries."""
    try:
        import healpy as hp  # type: ignore[unresolved-import]
    except ImportError as e:
        raise ImportError("healpy required for HEALPix vertex extraction") from e

    nside = int(grid.grid["healpix_nside"][0])
    all_x, all_y, all_z = [], [], []

    for row in grid.grid.iter_rows(named=True):
        ipix = int(row["healpix_ipix"])

        vertices = hp.boundaries(nside, ipix, step=1)  # shape (3, n_vertices)

        for j in range(vertices.shape[1]):
            x, y, z = vertices[:, j]
            if z >= -0.01:  # Only upper hemisphere
                all_x.append(x)
                all_y.append(max(y, 0.0))
                all_z.append(max(z, 0.0))

    return np.array(all_x), np.array(all_y), np.array(all_z)


def _extract_fibonacci_vertices(
    grid: GridData,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Extract vertices from Fibonacci grid Voronoi regions.

    Uses per-cell ``voronoi_region`` indices and the
    :class:`~scipy.spatial.SphericalVoronoi` stored on *grid*.
    Falls back to cell centers if Voronoi data is unavailable.
    """
    voronoi = grid.voronoi
    if voronoi is not None and "voronoi_region" in grid.grid.columns:
        all_x, all_y, all_z = [], [], []
        for row in grid.grid.iter_rows(named=True):
            region = row["voronoi_region"]
            if region is None:
                continue
            verts = voronoi.vertices[np.array(region, dtype=int)]
            for v in verts:
                if v[2] >= -0.01:
                    all_x.append(v[0])
                    all_y.append(v[1])
                    all_z.append(max(v[2], 0.0))
        return np.array(all_x), np.array(all_y), np.array(all_z)

    # Fallback: cell centers
    phi_vals = grid.grid["phi"].to_numpy()
    theta_vals = grid.grid["theta"].to_numpy()
    x = np.sin(theta_vals) * np.cos(phi_vals)
    y = np.sin(theta_vals) * np.sin(phi_vals)
    z = np.cos(theta_vals)
    return x, y, z


# ==============================================================================
# Grid → xarray Dataset
# ==============================================================================


def grid_to_dataset(grid: GridData) -> xr.Dataset:
    """Convert a HemiGrid to a unified xarray Dataset with vertices.

    The returned Dataset carries cell centers, NaN-padded vertex arrays,
    vertex counts, and solid angles, all indexed by ``cell_id``.

    Parameters
    ----------
    grid : GridData
        Hemisphere grid instance.

    Returns
    -------
    xr.Dataset
        Dataset with dimensions ``(cell_id, vertex)`` and variables
        ``cell_phi``, ``cell_theta``, ``vertices_phi``, ``vertices_theta``,
        ``n_vertices``, ``solid_angle``.

    """
    # Extract per-cell vertices into (n_cells, max_vertices) arrays.
    n_cells = grid.ncells
    grid_type = grid.grid_type

    if grid_type in ("equal_area", "equal_angle", "equirectangular"):
        max_v = 4
        vertices_phi = np.full((n_cells, max_v), np.nan)
        vertices_theta = np.full((n_cells, max_v), np.nan)
        n_vertices = np.full(n_cells, 4, dtype=np.int32)

        for i, row in enumerate(grid.grid.iter_rows(named=True)):
            phi_min, phi_max = row["phi_min"], row["phi_max"]
            theta_min, theta_max = row["theta_min"], row["theta_max"]
            vertices_phi[i, :] = [phi_min, phi_max, phi_max, phi_min]
            vertices_theta[i, :] = [theta_min, theta_min, theta_max, theta_max]

    elif grid_type == "htm":
        max_v = 4  # padded to 4 for rectangular layout; only 3 used
        vertices_phi = np.full((n_cells, max_v), np.nan)
        vertices_theta = np.full((n_cells, max_v), np.nan)
        n_vertices = np.full(n_cells, 3, dtype=np.int32)

        for i, row in enumerate(grid.grid.iter_rows(named=True)):
            for j, col in enumerate(["htm_vertex_0", "htm_vertex_1", "htm_vertex_2"]):
                v = np.array(row[col], dtype=float)
                r = np.linalg.norm(v)
                if r == 0:
                    continue
                x, y, z = v / r
                vertices_theta[i, j] = np.arccos(np.clip(z, -1, 1))
                vertices_phi[i, j] = np.mod(np.arctan2(y, x), 2 * np.pi)

    elif grid_type == "geodesic":
        max_v = 3
        vertices_phi = np.full((n_cells, max_v), np.nan)
        vertices_theta = np.full((n_cells, max_v), np.nan)
        n_vertices = np.full(n_cells, 3, dtype=np.int32)

        shared = grid.vertices  # shared vertex array from GridData
        if shared is not None and "geodesic_vertices" in grid.grid.columns:
            shared = np.asarray(shared, dtype=float)
            for i, row in enumerate(grid.grid.iter_rows(named=True)):
                indices = row["geodesic_vertices"]
                for j, v_idx in enumerate(indices):
                    v = shared[int(v_idx)]
                    r = np.linalg.norm(v)
                    if r == 0:
                        continue
                    x, y, z = v / r
                    vertices_theta[i, j] = np.arccos(np.clip(z, -1, 1))
                    vertices_phi[i, j] = np.mod(np.arctan2(y, x), 2 * np.pi)
        else:
            # Fallback: use cell centers as single-point "vertices"
            n_vertices[:] = 1
            vertices_phi[:, 0] = grid.grid["phi"].to_numpy()
            vertices_theta[:, 0] = grid.grid["theta"].to_numpy()

    elif grid_type == "healpix":
        max_v = 4
        vertices_phi = np.full((n_cells, max_v), np.nan)
        vertices_theta = np.full((n_cells, max_v), np.nan)
        n_vertices = np.full(n_cells, 4, dtype=np.int32)

        for i, row in enumerate(grid.grid.iter_rows(named=True)):
            phi_min, phi_max = row["phi_min"], row["phi_max"]
            theta_min, theta_max = row["theta_min"], row["theta_max"]
            vertices_phi[i, :] = [phi_min, phi_max, phi_max, phi_min]
            vertices_theta[i, :] = [theta_min, theta_min, theta_max, theta_max]

    elif grid_type == "fibonacci":
        # Point-based: single vertex per cell (the center)
        max_v = 1
        vertices_phi = grid.grid["phi"].to_numpy().reshape(n_cells, 1)
        vertices_theta = grid.grid["theta"].to_numpy().reshape(n_cells, 1)
        n_vertices = np.ones(n_cells, dtype=np.int32)

    else:
        raise ValueError(f"Unknown grid type: {grid_type}")

    # Cell centers
    cell_phi = grid.grid["phi"].to_numpy()
    cell_theta = grid.grid["theta"].to_numpy()
    solid_angles = grid.get_solid_angles()

    ds = xr.Dataset(
        {
            "cell_phi": (["cell_id"], cell_phi),
            "cell_theta": (["cell_id"], cell_theta),
            "vertices_phi": (["cell_id", "vertex"], vertices_phi),
            "vertices_theta": (["cell_id", "vertex"], vertices_theta),
            "n_vertices": (["cell_id"], n_vertices),
            "solid_angle": (["cell_id"], solid_angles),
        },
        coords={
            "cell_id": np.arange(n_cells),
            "vertex": np.arange(max_v),
        },
        attrs={
            "grid_type": grid.grid_type,
            "angular_resolution_deg": float(
                grid.metadata.get("angular_resolution", 0.0) if grid.metadata else 0.0
            ),
            "angular_resolution_description": _RESOLUTION_DESCRIPTIONS.get(
                grid.grid_type, "Angular resolution in degrees"
            ),
            "cutoff_theta_deg": float(
                grid.metadata.get("cutoff_theta", 0.0) if grid.metadata else 0.0
            ),
            "phi_rotation_deg": float(
                grid.metadata.get("phi_rotation", 0.0) if grid.metadata else 0.0
            ),
            "n_cells": n_cells,
        },
    )

    return ds


# ==============================================================================
# Grid storage to Icechunk (moved to canvod-store)
# ==============================================================================


@deprecated(
    "canvod.grids.store_grid() is left over from development and will be "
    "removed with the next major version. Use canvod.store.store_grid() "
    "instead."
)
def store_grid(grid: GridData, store: Any, grid_name: str) -> str:
    """Store a grid in an Icechunk store.

    Calls ``canvod.store.store_grid``. Needs ``canvod-store`` installed.
    """
    from canvod.store.grid_storage import store_grid as _store_grid

    return _store_grid(grid, store, grid_name)


@deprecated(
    "store_dataset_with_cell_ids() is left over from development and will be "
    "removed with the next major version. Use canvod.ops.assign_grid_cells_in_store() "
    "instead."
)
def store_dataset_with_cell_ids(
    ds: xr.Dataset,
    store: Any,
    group_name: str,
) -> str:
    """Add the ``cell_id_*`` variables of a dataset to its store group.

    Only the ``cell_id_*`` variables are written
    (``MyIcechunkStore.add_group_variables``); the group's data, log book
    and other subgroups stay as they are. ``ds`` must cover all epochs and
    signals of the group, in the same order.

    The cells were computed outside canVODpy's preprocessing, so the log
    book records them as an operation no run applies: later writes into
    the group are refused. ``canvod.ops.assign_grid_cells_in_store`` computes the
    cells as a run does, so runs with the same grid assignment can still
    append.

    Parameters
    ----------
    ds : xr.Dataset
        Dataset with cell-ID variables already added.
    store
        Icechunk store instance (``MyIcechunkStore``).
    group_name : str
        Zarr group path, e.g. ``'canopy_01'``.

    Returns
    -------
    str
        The new tip of ``main``.
    """
    cell_id_vars = [str(v) for v in ds.data_vars if str(v).startswith("cell_id_")]
    return store.add_group_variables(
        group_name,
        ds[cell_id_vars],
        step={
            "op": "store_dataset_with_cell_ids",
            "settings": {"variables": cell_id_vars},
            "result": {},
        },
        software={"canvod-grids": version("canvod-grids")},
    )


@deprecated(
    "canvod.grids.load_grid() is left over from development and will be "
    "removed with the next major version. Use canvod.store.load_grid() "
    "instead."
)
def load_grid(store: Any, grid_name: str) -> GridData:
    """Load a grid from an Icechunk store.

    Calls ``canvod.store.load_grid``. Needs ``canvod-store`` installed.
    """
    from canvod.store.grid_storage import load_grid as _load_grid

    return _load_grid(store, grid_name)
