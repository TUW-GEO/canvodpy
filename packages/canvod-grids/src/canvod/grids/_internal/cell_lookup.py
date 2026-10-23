"""Find the grid cell that contains a direction.

Each grid type is looked up by its own cell boundaries:

* ``equal_area``, ``equal_angle``, ``equirectangular``: the theta band
  ``[theta_min, theta_max)`` and, inside it, the phi sector
  ``[phi_min, phi_max)``. The last band includes its outer edge.
* ``htm``, ``geodesic``: the spherical triangle the direction lies in.
* ``healpix``: the HEALPix pixel (``healpy.ang2pix``).
* ``fibonacci``: the Voronoi cell, i.e. the nearest lattice point of the
  full sphere.

A direction that lies in no cell of the grid (below the grid's lowest band,
or in a triangle, pixel or Voronoi cell the hemisphere filter left out) gets
no cell: NaN.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

import numpy as np
from scipy.spatial import cKDTree  # type: ignore[unresolved-import]

if TYPE_CHECKING:
    from canvod.grids.core import GridData

TWO_PI = 2 * np.pi
_RING_TYPES = ("equal_area", "equal_angle", "equirectangular")
# Tolerance of the point-in-triangle test for directions on a cell edge.
_EDGE_TOL = 1e-12
# Triangles tested per direction before testing all of them.
_CANDIDATES = 8

CellLookup = Callable[[np.ndarray, np.ndarray], np.ndarray]


def _xyz(phi: np.ndarray, theta: np.ndarray) -> np.ndarray:
    return np.column_stack(
        [np.sin(theta) * np.cos(phi), np.sin(theta) * np.sin(phi), np.cos(theta)]
    )


def _phi_rotation_rad(grid: GridData) -> float:
    """Rotation the builder applied to the cell table but not to the vertices."""
    return float(np.deg2rad((grid.metadata or {}).get("phi_rotation", 0.0)))


def _missing(grid: GridData, what: str) -> ValueError:
    return ValueError(
        f"The {grid.grid_type} grid has no {what}, so the cell that contains "
        "an observation cannot be found. Build the grid with create_hemigrid() "
        "instead of loading it from a store."
    )


def _ring_lookup(grid: GridData) -> CellLookup:
    """Theta band, then phi sector, from the cell bounds."""
    table = grid.grid
    theta_min = table["theta_min"].to_numpy()
    theta_max = table["theta_max"].to_numpy()
    phi_min = table["phi_min"].to_numpy() % TWO_PI
    phi_width = table["phi_max"].to_numpy() - table["phi_min"].to_numpy()
    cell_id = table["cell_id"].to_numpy()

    band_inner = np.unique(theta_min)
    bands = []
    for inner in band_inner:
        in_band = theta_min == inner
        order = np.argsort(phi_min[in_band])
        start = phi_min[in_band][order]
        bands.append(
            (
                theta_max[in_band].max(),
                start[0],
                (start - start[0]) % TWO_PI,
                phi_width[in_band][order],
                cell_id[in_band][order],
            )
        )
    outermost = bands[-1][0]

    def lookup(phi: np.ndarray, theta: np.ndarray) -> np.ndarray:
        out = np.full(len(phi), np.nan)
        band = np.searchsorted(band_inner, theta, side="right") - 1
        inside = (band >= 0) & (theta <= outermost)
        for b, (outer, start, offsets, widths, ids) in enumerate(bands):
            sel = inside & (band == b) & (theta <= outer)
            if not sel.any():
                continue
            d = (phi[sel] - start) % TWO_PI
            k = np.searchsorted(offsets, d, side="right") - 1
            hit = d < offsets[k] + widths[k]
            out[np.flatnonzero(sel)[hit]] = ids[k[hit]]
        return out

    return lookup


def _triangle_lookup(grid: GridData, vertices: np.ndarray) -> CellLookup:
    """Spherical triangle containing the direction; ``vertices`` (n, 3, 3)."""
    v0, v1, v2 = vertices[:, 0], vertices[:, 1], vertices[:, 2]
    normals = np.stack(
        [np.cross(v0, v1), np.cross(v1, v2), np.cross(v2, v0)], axis=1
    )  # (n, 3 edges, xyz)
    # Orient every edge normal to point into its triangle.
    side = np.sign(np.einsum("ij,ij->i", normals[:, 0], v2))
    normals *= side[:, None, None]
    centers = vertices.sum(axis=1)
    centers /= np.linalg.norm(centers, axis=1, keepdims=True)
    tree = cKDTree(centers)
    cell_id = grid.grid["cell_id"].to_numpy().astype(np.float64)
    k = min(_CANDIDATES, len(centers))
    rotation = _phi_rotation_rad(grid)

    def contains(p: np.ndarray, tri: np.ndarray) -> np.ndarray:
        # p (m, 3), tri (m, ...) -> (m, ...) bool
        dots = np.einsum("m...ej,mj->m...e", normals[tri], p)
        return (dots >= -_EDGE_TOL).all(axis=-1) & (
            np.einsum("m...j,mj->m...", centers[tri], p) > 0
        )

    def lookup(phi: np.ndarray, theta: np.ndarray) -> np.ndarray:
        p = _xyz(phi - rotation, theta)
        out = np.full(len(p), np.nan)
        _, cand = tree.query(p, k=k, workers=-1)
        cand = cand.reshape(len(p), k)
        hit = contains(p, cand)
        found = hit.any(axis=1)
        out[found] = cell_id[cand[found, hit[found].argmax(axis=1)]]
        # Directions none of the nearest triangles contains: test all.
        for i in np.flatnonzero(~found):
            inside = contains(
                np.broadcast_to(p[i], (len(centers), 3)), np.arange(len(centers))
            )
            if inside.any():
                out[i] = cell_id[inside.argmax()]
        return out

    return lookup


def _htm_lookup(grid: GridData) -> CellLookup:
    columns = ("htm_vertex_0", "htm_vertex_1", "htm_vertex_2")
    if not all(c in grid.grid.columns for c in columns):
        raise _missing(grid, "triangle vertices")
    vertices = np.stack(
        [np.asarray(grid.grid[c].to_list(), dtype=np.float64) for c in columns],
        axis=1,
    )
    return _triangle_lookup(grid, vertices)


def _geodesic_lookup(grid: GridData) -> CellLookup:
    if grid.vertices is None or "geodesic_vertices" not in grid.grid.columns:
        raise _missing(grid, "triangle vertices")
    indices = np.asarray(grid.grid["geodesic_vertices"].to_list(), dtype=np.int64)
    return _triangle_lookup(grid, np.asarray(grid.vertices)[indices])


def _healpix_lookup(grid: GridData) -> CellLookup:
    if not {"healpix_ipix", "healpix_nside"} <= set(grid.grid.columns):
        raise _missing(grid, "HEALPix pixel numbers")
    import healpy as hp  # type: ignore[unresolved-import]

    nside = int(grid.grid["healpix_nside"][0])
    pixel_to_cell = np.full(hp.nside2npix(nside), np.nan)
    pixel_to_cell[grid.grid["healpix_ipix"].to_numpy()] = grid.grid[
        "cell_id"
    ].to_numpy()
    rotation = _phi_rotation_rad(grid)

    def lookup(phi: np.ndarray, theta: np.ndarray) -> np.ndarray:
        return pixel_to_cell[hp.ang2pix(nside, theta, (phi - rotation) % TWO_PI)]

    return lookup


def _fibonacci_lookup(grid: GridData) -> CellLookup:
    if grid.voronoi is None:
        raise _missing(grid, "Voronoi tessellation")
    if grid.points_xyz is None:
        raise _missing(grid, "lattice points")
    tree = cKDTree(np.asarray(grid.voronoi.points))
    # The grid's cells are the hemisphere's lattice points, in cell order.
    _, kept = tree.query(np.asarray(grid.points_xyz))
    site_to_cell = np.full(len(grid.voronoi.points), np.nan)
    site_to_cell[kept] = grid.grid["cell_id"].to_numpy()
    rotation = _phi_rotation_rad(grid)

    def lookup(phi: np.ndarray, theta: np.ndarray) -> np.ndarray:
        _, site = tree.query(_xyz(phi - rotation, theta), workers=-1)
        return site_to_cell[site]

    return lookup


def cell_lookup(grid: GridData) -> CellLookup:
    """Return a function ``(phi, theta) -> cell_id`` (NaN outside the grid).

    ``phi`` and ``theta`` are 1-D arrays of finite angles in radians.
    """
    if grid.grid_type in _RING_TYPES:
        return _ring_lookup(grid)
    builders = {
        "htm": _htm_lookup,
        "geodesic": _geodesic_lookup,
        "healpix": _healpix_lookup,
        "fibonacci": _fibonacci_lookup,
    }
    if grid.grid_type not in builders:
        raise ValueError(f"Unknown grid type: {grid.grid_type}")
    return builders[grid.grid_type](grid)
