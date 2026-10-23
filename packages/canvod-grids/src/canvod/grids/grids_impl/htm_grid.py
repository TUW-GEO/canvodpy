"""HTM (Hierarchical Triangular Mesh) grid implementation."""

import numpy as np
import polars as pl

from canvod.grids._internal import phi_bbox
from canvod.grids.core.grid_builder import BaseGridBuilder
from canvod.grids.core.grid_types import GridType


class HTMBuilder(BaseGridBuilder):
    """Hierarchical Triangular Mesh (HTM) grid.

    HTM divides the sphere into an octahedron (8 triangular faces), then
    recursively subdivides each face into 4 smaller triangles by inserting
    edge-midpoint vertices projected onto the unit sphere.  The recursion
    depth is controlled by ``htm_level``.  This produces a strictly
    hierarchical triangulation: every triangle at level *n* is the union of
    exactly 4 triangles at level *n* + 1.

    Cell areas are *approximately* equal but not strictly so — area
    uniformity improves with level because the icosahedral edge-length
    asymmetry averages out over many subdivisions.

    Coordinate convention (physics / GNSS)
    ---------------------------------------
    * phi  ∈ [0, 2π)  – azimuthal angle from North, clockwise (navigation convention)
    * theta ∈ [0, π/2] – polar angle from zenith (0 = straight up,
      π/2 = horizon)

    Cell centers are the 3D Cartesian mean of the three triangle vertices,
    re-normalized onto the unit sphere.

    What ``htm_level`` (resolution) means
    --------------------------------------
    The resolution is set by ``htm_level``, **not** by ``angular_resolution``.
    ``angular_resolution`` is used only to *estimate* an appropriate level
    when ``htm_level`` is not supplied explicitly.  The heuristic is::

        target_edge ≈ 2 × angular_resolution   (degrees)
        htm_level   = min(15, ceil(log₂(90 / target_edge)))

    The approximate triangle edge length at level *n* is::

        edge ≈ 90° / 2ⁿ

    | Level | Triangles (full sphere) | Approx edge |
    |-------|-------------------------|-------------|
    | 0     | 8                       | 90°         |
    | 1     | 32                      | 45°         |
    | 2     | 128                     | 22.5°       |
    | 3     | 512                     | 11.25°      |
    | 4     | 2 048                   | 5.6°        |
    | n     | 8 × 4ⁿ                  | 90° / 2ⁿ   |

    Mathematical construction
    -------------------------
    1. **Octahedron** – 6 vertices at ±x, ±y, ±z on the unit sphere, forming
       8 triangular faces (4 northern, 4 southern).
    2. **Subdivision** – for each triangle [v₀, v₁, v₂], three edge
       midpoints are computed and projected onto the unit sphere::

           m₀ = normalize((v₀ + v₁) / 2)
           m₁ = normalize((v₁ + v₂) / 2)
           m₂ = normalize((v₂ + v₀) / 2)

       The four children are [v₀, m₀, m₂], [v₁, m₁, m₀], [v₂, m₂, m₁],
       and [m₀, m₁, m₂].  This is repeated ``htm_level`` times.
    3. **Hemisphere filter** – a triangle is kept if its *centroid* (the
       3D Cartesian mean of the three vertices, renormalised to the unit
       sphere) satisfies ``theta ≤ π/2 − cutoff_theta``.  Filtering on
       centroid rather than "any vertex above" avoids keeping boundary
       triangles that are mostly below the horizon; kept triangles may
       still extend slightly across the horizon since cells are not
       clipped to an exact circle.
    4. Each leaf triangle becomes one cell; its center, bounding box, and
       three vertex coordinates are stored.

    Parameters
    ----------
    angular_resolution : float
        Approximate angular resolution in degrees.  Used only to derive
        ``htm_level`` when that parameter is not given explicitly.
    cutoff_theta : float
        Elevation mask angle in degrees.  Triangles are excluded if their
        centroid is below this elevation.
    htm_level : int or None
        HTM subdivision depth.  If ``None``, estimated from
        ``angular_resolution``.  Practical range 0–15.
    phi_rotation : float
        Rigid azimuthal rotation applied after construction, in degrees.

    Notes
    -----
    The ``theta_lims``, ``phi_lims``, and ``cell_ids`` fields of the returned
    ``GridData`` are *synthetic* evenly-spaced arrays kept only for interface
    compatibility with ring-based grids.  They do **not** describe the actual
    triangular cell layout.

    HTM IDs in this implementation use a decimal-digit scheme
    (``parent_id × 10 + child_index``) which diverges from the original
    SDSS HTM binary-coded ID scheme.  This is adequate for indexing but
    should not be compared with external HTM catalogs.

    References
    ----------
    Kunszt et al. (2001): "The Hierarchical Triangular Mesh"
    https://www.sdss.org/dr12/algorithms/htm/

    """

    def __init__(
        self,
        angular_resolution: float = 2,
        cutoff_theta: float = 0,
        htm_level: int | None = None,
        phi_rotation: float = 0,
    ) -> None:
        """Initialize the HTM grid builder.

        Parameters
        ----------
        angular_resolution : float, default 2
            Angular resolution in degrees.
        cutoff_theta : float, default 0
            Maximum polar angle cutoff in degrees.
        htm_level : int | None, optional
            HTM subdivision level.
        phi_rotation : float, default 0
            Rotation angle in degrees.

        """
        super().__init__(angular_resolution, cutoff_theta, phi_rotation)

        if htm_level is None:
            target_edge_deg = angular_resolution * 2
            self.htm_level = max(
                0,
                int(np.ceil(np.log2(90 / target_edge_deg))),
            )
            self.htm_level = min(self.htm_level, 15)
        else:
            self.htm_level = htm_level

        self._logger.info(
            f"HTM: level={self.htm_level}, ~{8 * 4**self.htm_level} triangles"
        )

    def get_grid_type(self) -> str:
        """Return the grid-type identifier string.

        Returns
        -------
        str
            ``"htm"``

        """
        return GridType.HTM.value

    def _build_grid(
        self,
    ) -> tuple[pl.DataFrame, np.ndarray, list[np.ndarray], list[np.ndarray]]:
        """Build HTM grid by recursive octahedron subdivision.

        Returns
        -------
        grid : pl.DataFrame
            One row per triangular cell.  Contains phi, theta (center),
            bounding-box limits, ``htm_id``, ``htm_level``, and the three
            vertex coordinate columns ``htm_vertex_0/1/2`` (each a list of
            3 floats in Cartesian xyz).
        theta_lims : np.ndarray
            Synthetic evenly-spaced theta limits (interface compatibility only).
        phi_lims : list[np.ndarray]
            Synthetic evenly-spaced phi limits (interface compatibility only).
        cell_ids : list[np.ndarray]
            Single-element list containing all cell ids.

        """
        base_vertices = np.array(
            [
                [0, 0, 1],  # 0: North pole
                [1, 0, 0],  # 1: +X
                [0, 1, 0],  # 2: +Y
                [-1, 0, 0],  # 3: -X
                [0, -1, 0],  # 4: -Y
                [0, 0, -1],  # 5: South pole
            ],
            dtype=np.float64,
        )

        base_faces = [
            [0, 1, 2],
            [0, 2, 3],
            [0, 3, 4],
            [0, 4, 1],  # Northern
            [5, 2, 1],
            [5, 3, 2],
            [5, 4, 3],
            [5, 1, 4],  # Southern
        ]

        all_triangles = []
        all_htm_ids = []

        for base_idx, base_face in enumerate(base_faces):
            v0 = base_vertices[base_face[0]]
            v1 = base_vertices[base_face[1]]
            v2 = base_vertices[base_face[2]]

            triangles, ids = self._subdivide_htm([v0, v1, v2], base_idx, self.htm_level)
            all_triangles.extend(triangles)
            all_htm_ids.extend(ids)

        max_theta = np.pi / 2 - self.cutoff_theta_rad

        # Convert to cells
        cells = []
        for tri, htm_id in zip(all_triangles, all_htm_ids):
            v0, v1, v2 = tri

            # Center
            center = (v0 + v1 + v2) / 3
            center = center / np.linalg.norm(center)

            theta_center = np.arccos(np.clip(center[2], -1, 1))

            # Filter hemisphere on the centroid, not "any vertex above" --
            # the latter keeps boundary triangles that are mostly below the
            # horizon.
            if theta_center > max_theta:
                continue

            phi_center = np.arctan2(center[1], center[0])
            phi_center = np.mod(phi_center, 2 * np.pi)

            # Vertex coords
            thetas, phis = [], []
            for v in [v0, v1, v2]:
                t = np.arccos(np.clip(v[2], -1, 1))
                p = np.arctan2(v[1], v[0])
                p = np.mod(p, 2 * np.pi)
                thetas.append(t)
                phis.append(p)

            phi_min, phi_max = phi_bbox(np.array(phis))

            cells.append(
                {
                    "phi": phi_center,
                    "theta": theta_center,
                    "phi_min": phi_min,
                    "phi_max": phi_max,
                    "theta_min": min(thetas),
                    "theta_max": max(thetas),
                    "htm_id": htm_id,
                    "htm_level": self.htm_level,
                    "htm_vertex_0": v0.tolist(),
                    "htm_vertex_1": v1.tolist(),
                    "htm_vertex_2": v2.tolist(),
                }
            )

        grid = pl.DataFrame(cells).with_columns(
            pl.int_range(0, pl.len()).alias("cell_id")
        )

        theta_lims = np.linspace(0, np.pi / 2, 10)
        phi_lims = [np.linspace(0, 2 * np.pi, 20) for _ in range(len(theta_lims))]
        cell_ids_list = [grid["cell_id"].to_numpy()]

        return grid, theta_lims, phi_lims, cell_ids_list

    def _subdivide_htm(
        self,
        tri: list,
        htm_id: int,
        target_level: int,
        current_level: int = 0,
    ) -> tuple[list, list]:
        """Recursively subdivide a single triangle.

        Parameters
        ----------
        tri : list of np.ndarray
            Three vertex arrays [v₀, v₁, v₂], each shape ``(3,)``.
        htm_id : int
            Current HTM identifier for this triangle.
        target_level : int
            Recursion depth to reach.
        current_level : int
            Current recursion depth.

        Returns
        -------
        triangles : list of list
            Leaf triangles at ``target_level``.
        ids : list of int
            Corresponding HTM identifiers.

        """
        if current_level == target_level:
            return [tri], [htm_id]

        v0, v1, v2 = tri

        # Midpoints on sphere
        m0 = (v0 + v1) / 2
        m0 = m0 / np.linalg.norm(m0)
        m1 = (v1 + v2) / 2
        m1 = m1 / np.linalg.norm(m1)
        m2 = (v2 + v0) / 2
        m2 = m2 / np.linalg.norm(m2)

        # 4 children
        children = [[v0, m0, m2], [v1, m1, m0], [v2, m2, m1], [m0, m1, m2]]

        all_tris = []
        all_ids = []

        for child_idx, child in enumerate(children):
            child_id = htm_id * 10 + child_idx
            tris, ids = self._subdivide_htm(
                child,
                child_id,
                target_level,
                current_level + 1,
            )
            all_tris.extend(tris)
            all_ids.extend(ids)

        return all_tris, all_ids

    def get_htm_info(self) -> dict:
        """Get HTM-specific information.

        Returns
        -------
        info : dict
            Keys: ``htm_level``, ``n_triangles_full_sphere``,
            ``approx_edge_length_deg``, ``approx_edge_length_arcmin``.

        """
        n_triangles = 8 * 4**self.htm_level
        approx_edge_deg = 90 / (2**self.htm_level)

        return {
            "htm_level": self.htm_level,
            "n_triangles_full_sphere": n_triangles,
            "approx_edge_length_deg": approx_edge_deg,
            "approx_edge_length_arcmin": approx_edge_deg * 60,
        }
