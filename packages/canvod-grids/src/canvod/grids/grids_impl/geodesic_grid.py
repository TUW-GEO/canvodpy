"""Geodesic grid implementation."""

from typing import Any

import numpy as np
import polars as pl

from canvod.grids._internal import phi_bbox
from canvod.grids.core.grid_builder import BaseGridBuilder
from canvod.grids.core.grid_types import GridType


class GeodesicBuilder(BaseGridBuilder):
    """Geodesic grid based on a subdivided icosahedron.

    The sphere is tessellated into triangular cells by starting with an
    icosahedron (20 equilateral triangles) and recursively subdividing each
    triangle into four smaller triangles.  All vertices are projected back
    onto the unit sphere after each subdivision step, so the final cells are
    *spherical* triangles.  The grid has no polar singularity and provides
    near-uniform cell areas, though strict equal-area is *not* guaranteed —
    cell areas vary by a few percent depending on how they inherit the
    icosahedral symmetry axes.

    Coordinate convention (physics / GNSS)
    ---------------------------------------
    * phi  ∈ [0, 2π)  – azimuthal angle from North, clockwise (navigation convention)
    * theta ∈ [0, π/2] – polar angle from zenith (0 = straight up,
      π/2 = horizon)

    Cell centers are computed as the 3D Cartesian mean of the three vertices,
    re-normalized onto the unit sphere.

    What ``angular_resolution`` means
    ----------------------------------
    ``angular_resolution`` is **not** used directly as a cell size.  Instead it
    is used only when ``subdivision_level`` is *not* explicitly supplied, to
    *estimate* an appropriate subdivision level.  The heuristic targets an
    approximate triangle edge length of ``2 × angular_resolution``::

        target_edge ≈ 2 × angular_resolution   (degrees)
        subdivision_level = ceil(log₂(63.4 / target_edge))

    The number 63.4° is the edge length of a regular icosahedron inscribed in
    a unit sphere.  Each subdivision halves the edge length, so the actual
    edge length at level *n* is approximately::

        edge ≈ 63.4° / 2ⁿ   (degrees)

    The total number of triangles on the **full sphere** is ``20 × 4ⁿ``.
    Roughly half fall in the northern hemisphere (exact count depends on
    the hemisphere boundary).

    Mathematical construction
    -------------------------
    1. **Icosahedron** – 12 vertices placed at the intersections of three
       mutually perpendicular golden-ratio rectangles, normalized to the
       unit sphere.  20 triangular faces connect them.
    2. **Subdivision** – each triangle is split into 4 by inserting edge
       midpoints.  Each midpoint is projected onto the unit sphere
       (re-normalized) before the next subdivision.  This is repeated
       ``subdivision_level`` times.
    3. **Hemisphere filter** – faces are kept if their *centroid* (the
       3D Cartesian mean of the three vertices, renormalised to the unit
       sphere) satisfies ``theta ≤ π/2 − cutoff_theta``.  Filtering on
       centroid rather than "any vertex above" avoids keeping boundary
       triangles that are mostly below the horizon; kept triangles may
       still extend slightly across the horizon since cells are not
       clipped to an exact circle.
    4. **Phi wrapping** – for triangles that straddle the 0/2π azimuthal
       boundary, bounding-box limits are computed with a seam-aware
       min/max (see ``phi_bbox``) rather than naive ``min``/``max``.

    Parameters
    ----------
    angular_resolution : float
        Approximate angular resolution in degrees.  Used only to derive
        ``subdivision_level`` when that parameter is not given explicitly.
    cutoff_theta : float
        Elevation mask angle in degrees.  Triangles are excluded if their
        centroid is below this elevation.
    subdivision_level : int or None
        Number of icosahedral subdivisions.  If ``None``, estimated from
        ``angular_resolution``.  Typical range 0–5.
    phi_rotation : float
        Rigid azimuthal rotation applied after construction, in degrees.

    Notes
    -----
    The ``theta_lims``, ``phi_lims``, and ``cell_ids`` fields of the returned
    ``GridData`` are *synthetic* evenly-spaced arrays kept only for interface
    compatibility with ring-based grids.  They do **not** describe the actual
    triangular cell layout.  Use the ``geodesic_vertices`` column and the
    ``vertices`` array in ``GridData.vertices`` for the true geometry.

    """

    def __init__(
        self,
        angular_resolution: float = 2,
        cutoff_theta: float = 0,
        subdivision_level: int | None = None,
        phi_rotation: float = 0,
    ) -> None:
        """Initialize the geodesic grid builder.

        Parameters
        ----------
        angular_resolution : float, default 2
            Angular resolution in degrees.
        cutoff_theta : float, default 0
            Maximum polar angle cutoff in degrees.
        subdivision_level : int | None, optional
            Subdivision level override.
        phi_rotation : float, default 0
            Rotation angle in degrees.

        """
        super().__init__(angular_resolution, cutoff_theta, phi_rotation)
        self._triangles: np.ndarray | None = None

        if subdivision_level is None:
            target_edge_deg = angular_resolution * 2
            self.subdivision_level = max(
                0,
                int(np.ceil(np.log2(63.4 / target_edge_deg))),
            )
        else:
            self.subdivision_level = subdivision_level

        self._logger.info(
            f"Geodesic: subdivision_level={self.subdivision_level}, "
            f"~{20 * 4**self.subdivision_level} triangles"
        )

    def get_triangles(self) -> np.ndarray | None:
        """Return triangle vertex coordinates for visualization.

        Returns
        -------
        triangles : np.ndarray or None
            Array of shape ``(n_faces, 3, 3)`` where ``triangles[i]`` contains
            the three 3D unit-sphere vertices of triangle *i*.  ``None`` if
            the grid has not been built yet.

        """
        return self._triangles

    def get_grid_type(self) -> str:
        """Return the grid-type identifier string.

        Returns
        -------
        str
            ``"geodesic"``

        """
        return GridType.GEODESIC.value

    def _extract_triangle_vertices(
        self, vertices: np.ndarray, faces: np.ndarray
    ) -> np.ndarray:
        """Extract 3D vertex coordinates for each face.

        Parameters
        ----------
        vertices : np.ndarray
            All sphere vertices, shape ``(n_vertices, 3)``.
        faces : np.ndarray
            Face index array, shape ``(n_faces, 3)``.

        Returns
        -------
        triangles : np.ndarray
            Shape ``(n_faces, 3, 3)`` – three 3D vertices per face.

        """
        # Vectorized: use NumPy advanced indexing instead of loop
        return vertices[faces]

    def _build_grid(
        self,
    ) -> tuple[
        pl.DataFrame, np.ndarray, list[np.ndarray], list[np.ndarray], dict[str, Any]
    ]:
        """Build geodesic grid from subdivided icosahedron.

        Returns
        -------
        grid : pl.DataFrame
            One row per triangular cell.  Columns include phi, theta (center),
            bounding-box limits, ``geodesic_vertices`` (3 vertex indices into
            the ``vertices`` array), and ``geodesic_subdivision``.
        theta_lims : np.ndarray
            Synthetic evenly-spaced theta limits (interface compatibility only).
        phi_lims : list[np.ndarray]
            Synthetic evenly-spaced phi limits (interface compatibility only).
        cell_ids : list[np.ndarray]
            Single-element list containing all cell ids.
        extra_kwargs : dict
            Contains ``vertices`` (shape ``(n_vertices, 3)``),
            ``vertex_phi``, and ``vertex_theta`` arrays for the full
            subdivided icosahedron.

        """
        vertices, faces = self._create_icosahedron()

        # Subdivide
        for _ in range(self.subdivision_level):
            vertices, faces = self._subdivide_mesh(vertices, faces)

        # Project to unit sphere
        vertices = vertices / np.linalg.norm(vertices, axis=1, keepdims=True)

        # Convert to spherical
        x, y, z = vertices[:, 0], vertices[:, 1], vertices[:, 2]
        theta = np.arccos(np.clip(z, -1, 1))
        phi = np.arctan2(y, x)
        phi = np.mod(phi, 2 * np.pi)

        max_theta = np.pi / 2 - self.cutoff_theta_rad

        # Build cells for every face, then keep only those whose centroid is
        # above the horizon. Filtering on the centroid (rather than "any
        # vertex above horizon") avoids keeping boundary triangles that are
        # mostly below the horizon.
        cells = []
        valid_faces = []
        for face in faces:
            v_indices = face
            face_phi = phi[v_indices]
            face_theta = theta[v_indices]

            # Cell center - 3D Cartesian mean
            face_vertices_3d = vertices[v_indices]
            center_3d = np.mean(face_vertices_3d, axis=0)
            center_3d = center_3d / np.linalg.norm(center_3d)

            center_theta = np.arccos(np.clip(center_3d[2], -1, 1))

            if center_theta > max_theta:
                continue

            center_phi = np.arctan2(center_3d[1], center_3d[0])
            center_phi = np.mod(center_phi, 2 * np.pi)

            phi_min, phi_max = phi_bbox(face_phi)

            # Cell bounds (theta from vertices, phi already computed above)
            theta_min = float(np.min(face_theta))
            theta_max = float(np.max(face_theta))

            cells.append(
                {
                    "phi": center_phi,
                    "theta": center_theta,
                    "phi_min": phi_min,
                    "phi_max": phi_max,
                    "theta_min": theta_min,
                    "theta_max": theta_max,
                    "geodesic_vertices": v_indices.tolist(),
                    "geodesic_subdivision": self.subdivision_level,
                }
            )
            valid_faces.append(face)

        if len(cells) == 0:
            raise ValueError("No valid faces in hemisphere")

        grid = pl.DataFrame(cells).with_columns(
            pl.int_range(0, pl.len()).alias("cell_id")
        )

        extra_kwargs: dict[str, Any] = {
            "vertices": vertices,
            "vertex_phi": phi,
            "vertex_theta": theta,
        }

        theta_lims = np.linspace(0, np.pi / 2, 10)
        phi_lims = [np.linspace(0, 2 * np.pi, 20) for _ in range(len(theta_lims))]
        cell_ids_list = [np.arange(grid.height)]

        # Align with the kept (hemisphere-filtered) faces, not the full
        # sphere's, so get_triangles() zips 1:1 with the grid's rows.
        self._triangles = self._extract_triangle_vertices(
            vertices, np.array(valid_faces)
        )

        return grid, theta_lims, phi_lims, cell_ids_list, extra_kwargs

    def _create_icosahedron(self) -> tuple[np.ndarray, np.ndarray]:
        """Create a unit-sphere icosahedron.

        Returns
        -------
        vertices : np.ndarray
            Shape ``(12, 3)`` – vertices on the unit sphere.
        faces : np.ndarray
            Shape ``(20, 3)`` – integer vertex indices per triangular face.

        """
        phi_golden = (1 + np.sqrt(5)) / 2

        vertices = np.array(
            [
                [-1, phi_golden, 0],
                [1, phi_golden, 0],
                [-1, -phi_golden, 0],
                [1, -phi_golden, 0],
                [0, -1, phi_golden],
                [0, 1, phi_golden],
                [0, -1, -phi_golden],
                [0, 1, -phi_golden],
                [phi_golden, 0, -1],
                [phi_golden, 0, 1],
                [-phi_golden, 0, -1],
                [-phi_golden, 0, 1],
            ],
            dtype=np.float64,
        )

        vertices = vertices / np.linalg.norm(vertices, axis=1, keepdims=True)

        faces = np.array(
            [
                [0, 11, 5],
                [0, 5, 1],
                [0, 1, 7],
                [0, 7, 10],
                [0, 10, 11],
                [1, 5, 9],
                [5, 11, 4],
                [11, 10, 2],
                [10, 7, 6],
                [7, 1, 8],
                [3, 9, 4],
                [3, 4, 2],
                [3, 2, 6],
                [3, 6, 8],
                [3, 8, 9],
                [4, 9, 5],
                [2, 4, 11],
                [6, 2, 10],
                [8, 6, 7],
                [9, 8, 1],
            ],
            dtype=np.int64,
        )

        return vertices, faces

    def _subdivide_mesh(
        self, vertices: np.ndarray, faces: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray]:
        """Subdivide each triangle into 4 smaller triangles.

        Each edge midpoint is computed, normalized onto the unit sphere, and
        cached so that shared edges produce only one new vertex.

        Parameters
        ----------
        vertices : np.ndarray
            Current vertex array, shape ``(n_vertices, 3)``.
        faces : np.ndarray
            Current face array, shape ``(n_faces, 3)``.

        Returns
        -------
        new_vertices : np.ndarray
            Expanded vertex array, shape ``(n_vertices + n_new_midpoints, 3)``.
        new_faces : np.ndarray
            New face array, shape ``(4 × n_faces, 3)``.

        """
        new_faces = []
        edge_midpoints: dict[tuple[int, int], int] = {}

        def get_midpoint(v1: int, v2: int) -> int:
            """Return midpoint vertex index for an edge.

            Parameters
            ----------
            v1 : int
                First vertex index.
            v2 : int
                Second vertex index.

            Returns
            -------
            int
                Index of the midpoint vertex.

            """
            a, b = sorted((v1, v2))
            edge = (a, b)
            if edge not in edge_midpoints:
                edge_midpoints[edge] = len(vertices) + len(edge_midpoints)
            return edge_midpoints[edge]

        for face in faces:
            v0, v1, v2 = face

            m01 = get_midpoint(v0, v1)
            m12 = get_midpoint(v1, v2)
            m20 = get_midpoint(v2, v0)

            new_faces.extend(
                [
                    [v0, m01, m20],
                    [v1, m12, m01],
                    [v2, m20, m12],
                    [m01, m12, m20],
                ]
            )

        n_original = len(vertices)
        n_new = len(edge_midpoints)
        final_vertices = np.zeros((n_original + n_new, 3))
        final_vertices[:n_original] = vertices

        for edge, idx in edge_midpoints.items():
            v1, v2 = edge
            midpoint = (vertices[v1] + vertices[v2]) / 2
            midpoint = midpoint / np.linalg.norm(midpoint)
            final_vertices[idx] = midpoint

        return final_vertices, np.array(new_faces)
