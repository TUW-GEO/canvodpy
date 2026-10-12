"""Fibonacci sphere grid implementation."""

from typing import Any

import numpy as np
import polars as pl

from canvod.grids._internal import phi_bbox
from canvod.grids.core.grid_builder import BaseGridBuilder
from canvod.grids.core.grid_types import GridType


class FibonacciBuilder(BaseGridBuilder):
    """Fibonacci sphere grid with spherical Voronoi tessellation.

    Points are distributed on the sphere using the *Fibonacci lattice*
    (golden-spiral method), which provides one of the most uniform
    point distributions achievable on a sphere without iterative
    optimization.  Each point then becomes the center of a *spherical
    Voronoi cell* — the region of the sphere closer to that point than
    to any other.  The resulting tessellation has no polar singularities
    and near-uniform cell areas.

    The tessellation is computed by ``scipy.spatial.SphericalVoronoi``.
    Because Voronoi cells have curvilinear boundaries, the ``phi_min/max``
    and ``theta_min/max`` columns in the grid are axis-aligned *bounding
    boxes*, **not** the true cell boundaries.  They are unreliable for
    spatial queries — use the ``voronoi_region`` column (vertex indices
    into the ``SphericalVoronoi.vertices`` array) for exact geometry.

    Coordinate convention (physics / GNSS)
    ---------------------------------------
    * phi  ∈ [0, 2π)  – azimuthal angle from North, clockwise (navigation convention)
    * theta ∈ [0, π/2] – polar angle from zenith (0 = straight up,
      π/2 = horizon)

    What ``n_points`` (resolution) means
    -------------------------------------
    Resolution is controlled by ``n_points``, the number of Voronoi cells
    in the hemisphere.  When ``n_points`` is not supplied it is estimated
    from ``angular_resolution`` via::

        cell_area  ≈ angular_resolution²   (radians²)
        n_points   = max(10, round(2π / cell_area))

    The approximate cell "diameter" (assuming a circular cell of equal area)
    is::

        d ≈ 2 √(2π / n_points)   (radians)
          ≈ 2 × angular_resolution

    ``angular_resolution`` therefore has **no direct geometric meaning** for
    this grid type — it is only a convenience for the ``n_points`` estimator.

    Mathematical construction
    -------------------------
    1. **Full-sphere Fibonacci lattice** – ``2 × n_points`` points are
       generated on the unit sphere.  Point *i* has::

           θᵢ = arccos(1 − 2(i + 0.5) / N)
           φᵢ = 2π (i + 0.5) / φ_golden   (mod 2π)

       where ``N = 2 × n_points`` and ``φ_golden = (1+√5)/2``.  The
       ``+0.5`` offset avoids placing points exactly at the poles.
    2. **Spherical Voronoi tessellation** –
       ``scipy.spatial.SphericalVoronoi`` computes the Voronoi diagram on
       the *full* sphere (both hemispheres). Regions are sorted so that
       vertices appear in counter-clockwise order around each cell.
       Tessellating the full sphere (rather than hemisphere-only points)
       is required for correctness: with no sites in the southern
       hemisphere, cells along the horizon would have no southern
       neighbor to bound them and would balloon out to cover the entire
       (empty) opposite hemisphere.
    3. **Hemisphere filter** – of the resulting cells, only those whose
       *generating point* has ``θ ≤ π/2 − cutoff_theta`` are kept.
    4. **Bounding boxes** – axis-aligned bounding boxes in (phi, theta)
       are computed from the Voronoi vertex coordinates, using a
       seam-aware min/max so cells straddling ``phi = 0/2π`` get their
       true (narrow) angular extent instead of a near-full-circle span.
       These bounding boxes are still approximations only (see caveat
       above).

    Parameters
    ----------
    angular_resolution : float
        Approximate angular resolution in degrees.  Used only to estimate
        ``n_points`` when that parameter is not given explicitly.
    cutoff_theta : float
        Elevation mask angle in degrees.  Points below this elevation are
        excluded before tessellation.
    n_points : int or None
        Target number of Voronoi cells in the hemisphere.  If ``None``,
        estimated from ``angular_resolution``.
    phi_rotation : float
        Rigid azimuthal rotation applied after construction, in degrees.

    Raises
    ------
    ImportError
        If ``scipy`` is not installed.
    ValueError
        If fewer than 4 points survive the hemisphere filter.

    Notes
    -----
    The ``theta_lims``, ``phi_lims``, and ``cell_ids`` fields of the returned
    ``GridData`` are *synthetic* evenly-spaced arrays kept only for interface
    compatibility with ring-based grids.  They do **not** describe the actual
    Voronoi cell layout.

    """

    def __init__(
        self,
        angular_resolution: float = 2,
        cutoff_theta: float = 0,
        n_points: int | None = None,
        phi_rotation: float = 0,
    ) -> None:
        """Initialize the Fibonacci grid builder.

        Parameters
        ----------
        angular_resolution : float, default 2
            Angular resolution in degrees.
        cutoff_theta : float, default 0
            Maximum polar angle cutoff in degrees.
        n_points : int | None, optional
            Number of points to generate.
        phi_rotation : float, default 0
            Rotation angle in degrees.

        """
        super().__init__(angular_resolution, cutoff_theta, phi_rotation)

        if n_points is None:
            cell_area = self.angular_resolution_rad**2
            hemisphere_area = 2 * np.pi
            self.n_points = max(10, int(hemisphere_area / cell_area))
        else:
            self.n_points = n_points

        self._logger.info(f"Fibonacci: generating {self.n_points} points")

    def get_grid_type(self) -> str:
        """Return the grid-type identifier string.

        Returns
        -------
        str
            ``"fibonacci"``

        """
        return GridType.FIBONACCI.value

    def _build_grid(
        self,
    ) -> tuple[
        pl.DataFrame, np.ndarray, list[np.ndarray], list[np.ndarray], dict[str, Any]
    ]:
        """Build Fibonacci sphere grid with Voronoi tessellation.

        Returns
        -------
        grid : pl.DataFrame
            One row per Voronoi cell.  Contains phi, theta (center),
            bounding-box limits, ``voronoi_region`` (list of vertex indices
            into the Voronoi vertex array), and ``n_vertices``.
        theta_lims : np.ndarray
            Synthetic evenly-spaced theta limits (interface compatibility only).
        phi_lims : list[np.ndarray]
            Synthetic evenly-spaced phi limits (interface compatibility only).
        cell_ids : list[np.ndarray]
            Single-element list containing all cell ids.
        extra_kwargs : dict
            Contains ``voronoi`` (the ``SphericalVoronoi`` object) and
            ``points_xyz`` (the hemisphere point cloud, shape
            ``(n_points, 3)``).

        """
        points_xyz_full = self._generate_fibonacci_sphere(self.n_points * 2)

        # Convert to spherical
        x, y, z = points_xyz_full[:, 0], points_xyz_full[:, 1], points_xyz_full[:, 2]
        theta_full = np.arccos(np.clip(z, -1, 1))
        phi_full = np.mod(np.arctan2(y, x), 2 * np.pi)

        # Tessellate the FULL sphere point set, not just the hemisphere.
        # SphericalVoronoi always tessellates the whole unit sphere; seeding
        # it with hemisphere-only points leaves no sites in the southern
        # hemisphere, so the boundary ring's cells extend uncontested all
        # the way to the south pole (solid angles then sum to 4*pi instead
        # of 2*pi). Keeping the real southern-hemisphere lattice points as
        # Voronoi sites bounds the near-horizon cells correctly -- only
        # which CELLS to keep is filtered by hemisphere, after
        # tessellation, not which points seed the diagram.
        try:
            from scipy.spatial import SphericalVoronoi

            sv = SphericalVoronoi(points_xyz_full, radius=1, threshold=1e-10)
            sv.sort_vertices_of_regions()

        except ImportError as e:
            raise ImportError(
                "scipy required for Fibonacci grid. Install: uv add scipy"
            ) from e

        mask = theta_full <= (np.pi / 2 - self.cutoff_theta_rad)
        kept_indices = np.nonzero(mask)[0]

        if len(kept_indices) < 4:
            raise ValueError("Not enough points in hemisphere for Voronoi tessellation")

        phi = phi_full[mask]
        theta = theta_full[mask]
        points_xyz = points_xyz_full[mask]

        # Create cells
        cells = []
        for point_idx, p_phi, p_theta in zip(kept_indices, phi, theta):
            region_vertices = sv.regions[point_idx]
            region_coords = sv.vertices[region_vertices]

            # Convert region vertices to spherical
            rv_x, rv_y, rv_z = (
                region_coords[:, 0],
                region_coords[:, 1],
                region_coords[:, 2],
            )
            rv_theta = np.arccos(np.clip(rv_z, -1, 1))
            rv_phi = np.arctan2(rv_y, rv_x)

            phi_min, phi_max = phi_bbox(rv_phi)

            cells.append(
                {
                    "phi": p_phi,
                    "theta": p_theta,
                    "phi_min": phi_min,
                    "phi_max": phi_max,
                    "theta_min": np.min(rv_theta),
                    "theta_max": np.max(rv_theta),
                    "voronoi_region": (
                        region_vertices
                        if isinstance(region_vertices, list)
                        else region_vertices.tolist()
                    ),
                    "n_vertices": len(region_vertices),
                }
            )

        grid = pl.DataFrame(cells).with_columns(
            pl.int_range(0, pl.len()).alias("cell_id")
        )

        extra_kwargs: dict[str, Any] = {
            "voronoi": sv,
            "points_xyz": points_xyz,
        }

        theta_lims = np.linspace(0, np.pi / 2, 10)
        phi_lims = [np.linspace(0, 2 * np.pi, 20) for _ in range(len(theta_lims))]
        cell_ids_list = [np.arange(grid.height)]

        return grid, theta_lims, phi_lims, cell_ids_list, extra_kwargs

    def _generate_fibonacci_sphere(self, n: int) -> np.ndarray:
        """Generate points on the unit sphere using the golden-spiral lattice.

        Parameters
        ----------
        n : int
            Total number of points on the full sphere.

        Returns
        -------
        points : np.ndarray
            Shape ``(n, 3)`` – Cartesian (x, y, z) coordinates on the unit
            sphere.

        """
        golden_ratio = (1 + np.sqrt(5)) / 2

        indices = np.arange(0, n, dtype=np.float64) + 0.5

        # Polar angle
        theta = np.arccos(1 - 2 * indices / n)

        # Azimuthal angle
        phi = 2 * np.pi * indices / golden_ratio
        phi = np.mod(phi, 2 * np.pi)

        # Convert to Cartesian
        x = np.sin(theta) * np.cos(phi)
        y = np.sin(theta) * np.sin(phi)
        z = np.cos(theta)

        return np.column_stack([x, y, z])
