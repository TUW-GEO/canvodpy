"""Equal-area grid implementation."""

import numpy as np
import polars as pl

from canvod.grids.core.grid_builder import BaseGridBuilder
from canvod.grids.core.grid_types import GridType


class EqualAreaBuilder(BaseGridBuilder):
    """Equal solid angle tessellation using concentric theta bands.

    The hemisphere is divided into annular bands of constant width in theta.
    Within each band the number of azimuthal (phi) sectors is chosen so that
    every cell subtends approximately the same solid angle.  This is the only
    grid type that has been validated for scientific use in this codebase.

    Coordinate convention (physics / GNSS)
    ---------------------------------------
    * phi  ∈ [0, 2π)  – azimuthal angle from North, clockwise (navigation convention)
    * theta ∈ [0, π/2] – polar angle measured from zenith (0 = straight up,
      π/2 = horizon)

    What ``angular_resolution`` means
    ----------------------------------
    ``angular_resolution`` (degrees) sets the **width of each theta band**.
    All bands have this same width Δθ.  The *azimuthal* width of cells varies
    by band: near the zenith cells are wide in phi; near the horizon they are
    narrow, so that the solid angle stays constant.

    Mathematical construction
    -------------------------
    1. **Target solid angle** per cell is chosen equal to the solid angle of a
       cap of half-angle Δθ/2::

           Ω_target = 2π (1 − cos(Δθ/2))

    2. **Zenith cap** – a single cell covers [0, Δθ/2] in theta and the full
       azimuth [0, 2π).

    3. **Theta bands** – edges are placed at Δθ/2, 3Δθ/2, 5Δθ/2, … and a
       last edge at π/2 − cutoff_theta, so the grid reaches the horizon (or
       the cutoff).  With the zenith cap of half width the last band is
       usually narrower than Δθ (half as wide when the cutoff is a multiple
       of Δθ); its phi divisions follow from its solid angle like any other
       band's.  For each band [θ_inner, θ_outer] the band's total solid
       angle is::

           Ω_band = 2π (cos θ_inner − cos θ_outer)

    4. **Phi divisions** – the number of sectors in the band is::

           n_phi = round(Ω_band / Ω_target)

       Each sector spans Δφ = 2π / n_phi.  The cell center is placed at the
       geometric midpoint of its (phi, theta) rectangle.

    Parameters
    ----------
    angular_resolution : float
        Theta-band width in degrees.  Controls both the radial resolution and
        (indirectly, via the equal-area constraint) the azimuthal resolution.
    cutoff_theta : float
        Minimum elevation above the horizon in degrees.  The last band ends
        at θ = 90° − cutoff_theta; the sky below that elevation gets no
        cells.  In GNSS terms this is the satellite elevation mask angle.
    phi_rotation : float
        Rigid rotation applied to all phi coordinates after grid construction,
        in degrees.

    """

    def get_grid_type(self) -> str:
        """Return the grid-type identifier string.

        Returns
        -------
        str
            ``"equal_area"``

        """
        return GridType.EQUAL_AREA.value

    def _build_grid(
        self,
    ) -> tuple[pl.DataFrame, np.ndarray, list[np.ndarray], list[np.ndarray]]:
        """Construct the equal-area hemisphere grid.

        Returns
        -------
        grid : pl.DataFrame
            One row per cell with columns: phi, theta, phi_min, phi_max,
            theta_min, theta_max, cell_id.
        theta_lims : np.ndarray
            Outer theta edge of each band (radians).
        phi_lims : list[np.ndarray]
            Array of phi_min values for each band.
        cell_ids : list[np.ndarray]
            Cell-id arrays, one per band.

        """
        # Theta band edges (from zenith to horizon)
        max_theta = np.pi / 2  # horizon
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

        # Target solid angle per cell
        target_omega = 2 * np.pi * (1 - np.cos(self.angular_resolution_rad / 2))

        cells = []
        theta_lims = []
        phi_lims = []
        cell_ids = []

        # Zenith cell (special case). cutoff_theta is an elevation mask: it
        # only moves the outer edge (above), never the zenith.
        zenith_theta_max = self.angular_resolution_rad / 2
        cells.append(
            pl.DataFrame(
                {
                    "phi": [0.0],
                    "theta": [0.0],
                    "phi_min": [0.0],
                    "phi_max": [2 * np.pi],
                    "theta_min": [0.0],
                    "theta_max": [zenith_theta_max],
                }
            )
        )
        theta_lims.append(zenith_theta_max)
        phi_lims.append(np.array([0.0]))
        cell_ids.append(np.array([0]))
        next_cell_id = 1

        # Build theta bands
        for iband, theta_outer in enumerate(theta_edges[1:]):
            theta_inner = theta_edges[iband]

            # Solid angle of this band
            band_omega = 2 * np.pi * (np.cos(theta_inner) - np.cos(theta_outer))

            # Number of phi divisions
            n_phi = max(1, round(band_omega / target_omega))
            phi_span = 2 * np.pi / n_phi

            cell_id_list = list(range(next_cell_id, next_cell_id + n_phi))
            next_cell_id = cell_id_list[-1] + 1

            # Use arange for better precision than linspace
            phi_min_arr = np.arange(n_phi) * phi_span
            phi_max_arr = (np.arange(n_phi) + 1) * phi_span
            phi_max_arr[-1] = 2 * np.pi  # Force exact closure

            cells.append(
                pl.DataFrame(
                    {
                        "phi": (phi_min_arr + phi_max_arr) / 2,
                        "theta": np.full(n_phi, (theta_inner + theta_outer) / 2),
                        "phi_min": phi_min_arr,
                        "phi_max": phi_max_arr,
                        "theta_min": np.full(n_phi, theta_inner),
                        "theta_max": np.full(n_phi, theta_outer),
                    }
                )
            )

            theta_lims.append(theta_outer)
            phi_lims.append(phi_min_arr)
            cell_ids.append(np.array(cell_id_list))

        if len(cells) == 0:
            raise ValueError(
                "No cells generated - check cutoff_theta and angular_resolution"
            )

        grid = pl.concat(cells).with_columns(pl.int_range(0, pl.len()).alias("cell_id"))

        return grid, np.array(theta_lims), phi_lims, cell_ids
