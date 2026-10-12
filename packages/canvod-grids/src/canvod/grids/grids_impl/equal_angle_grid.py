"""Equal-angle grid implementation."""

import numpy as np
import polars as pl

from canvod.grids.core.grid_builder import BaseGridBuilder
from canvod.grids.core.grid_types import GridType


class EqualAngleBuilder(BaseGridBuilder):
    """Equal angular spacing in both theta and phi (NOT equal area).

    Every cell is a rectangle of the same angular size Δθ × Δφ in the
    (theta, phi) parameter space.  A cell's solid angle is
    Δφ · (cos θ_min − cos θ_max) ≈ Δφ · Δθ · sin θ, so cells near the zenith
    subtend *less* solid angle than cells near the horizon.  A statistic
    that weights every cell equally therefore gives the sky near the zenith
    more weight than its share of the hemisphere.  **Not recommended for
    scientific analysis** – use ``EqualAreaBuilder`` instead.

    Coordinate convention (physics / GNSS)
    ---------------------------------------
    * phi  ∈ [0, 2π)  – azimuthal angle from North, clockwise (navigation convention)
    * theta ∈ [0, π/2] – polar angle from zenith

    What ``angular_resolution`` means
    ----------------------------------
    ``angular_resolution`` (degrees) is used as **both** the theta-band width
    and the phi-sector width.  The number of phi divisions is the same in
    every band but the zenith cap::

        n_phi = floor(2π / Δθ)

    so the sectors are wider than Δθ when Δθ does not divide 360°.

    Mathematical construction
    -------------------------
    1. A zenith cap cell covers [0, Δθ/2] × [0, 2π).
    2. Theta band edges are placed at Δθ/2, 3Δθ/2, … and a last edge at
       π/2 − cutoff_theta, so the grid reaches the horizon (or the cutoff);
       the last band is usually narrower than Δθ.
    3. Within every band, the full azimuth is split into ``n_phi`` sectors of
       equal width Δφ = 2π / n_phi.
    4. Cell centers are at the midpoint of each (phi, theta) rectangle.

    Parameters
    ----------
    angular_resolution : float
        Angular spacing in degrees, applied identically in both theta and phi.
    cutoff_theta : float
        Elevation mask angle in degrees.  The last band ends at
        θ = 90° − cutoff_theta; the sky below that elevation gets no cells.
    phi_rotation : float
        Rigid azimuthal rotation applied after construction, in degrees.

    """

    def get_grid_type(self) -> str:
        """Return the grid-type identifier string.

        Returns
        -------
        str
            ``"equal_angle"``

        """
        return GridType.EQUAL_ANGLE.value

    def _build_grid(
        self,
    ) -> tuple[pl.DataFrame, np.ndarray, list[np.ndarray], list[np.ndarray]]:
        """Construct the equal-angle hemisphere grid.

        Returns
        -------
        grid : pl.DataFrame
            One row per cell.
        theta_lims : np.ndarray
            Outer theta edge of each band (radians).
        phi_lims : list[np.ndarray]
            Array of phi_min values for each band (identical across bands).
        cell_ids : list[np.ndarray]
            Cell-id arrays, one per band.

        """
        max_theta = np.pi / 2
        theta_edges = np.arange(
            self.angular_resolution_rad / 2,
            max_theta - self.cutoff_theta_rad,
            self.angular_resolution_rad,
        )
        # The last band ends at the outer edge of the grid (the horizon, or
        # 90° - cutoff_theta); it is narrower when the band width does not
        # divide the remaining range.
        if not np.isclose(theta_edges[-1], max_theta - self.cutoff_theta_rad):
            theta_edges = np.append(theta_edges, max_theta - self.cutoff_theta_rad)

        n_phi_divisions = int(2 * np.pi / self.angular_resolution_rad)

        cells = []
        theta_lims = []
        phi_lims = []
        cell_ids = []

        # Zenith
        cells.append(
            pl.DataFrame(
                {
                    "phi": [0.0],
                    "theta": [0.0],
                    "phi_min": [0.0],
                    "phi_max": [2 * np.pi],
                    "theta_min": [0.0],
                    "theta_max": [self.angular_resolution_rad / 2],
                }
            )
        )
        theta_lims.append(self.angular_resolution_rad / 2)
        phi_lims.append(np.array([0.0]))
        cell_ids.append(np.array([0]))
        next_cell_id = 1

        for iband, theta_outer in enumerate(theta_edges[1:]):
            theta_inner = theta_edges[iband]
            phi_span = 2 * np.pi / n_phi_divisions

            cell_id_list = list(range(next_cell_id, next_cell_id + n_phi_divisions))
            next_cell_id = cell_id_list[-1] + 1

            phi_min_arr = np.linspace(0, 2 * np.pi - phi_span, n_phi_divisions)
            phi_max_arr = np.concatenate((phi_min_arr[1:], [2 * np.pi]))

            cells.append(
                pl.DataFrame(
                    {
                        "phi": (phi_min_arr + phi_max_arr) / 2,
                        "theta": np.full(
                            n_phi_divisions,
                            (theta_inner + theta_outer) / 2,
                        ),
                        "phi_min": phi_min_arr,
                        "phi_max": phi_max_arr,
                        "theta_min": np.full(n_phi_divisions, theta_inner),
                        "theta_max": np.full(n_phi_divisions, theta_outer),
                    }
                )
            )

            theta_lims.append(theta_outer)
            phi_lims.append(phi_min_arr)
            cell_ids.append(np.array(cell_id_list))

        grid = pl.concat(cells).with_row_index("cell_id")
        return grid, np.array(theta_lims), phi_lims, cell_ids
