"""Equirectangular grid implementation."""

import numpy as np
import polars as pl

from canvod.grids.core.grid_builder import BaseGridBuilder
from canvod.grids.core.grid_types import GridType


class EquirectangularBuilder(BaseGridBuilder):
    """Simple rectangular grid in (theta, phi) space.

    The hemisphere is divided into a regular rectangular array: a constant
    number of theta bands, each containing the same constant number of phi
    sectors.  Every cell is a rectangle of the same angular size in
    (theta, phi), except the last band and the last sector, which are
    narrower when Δθ does not divide their range.  It differs from
    ``EqualAngleBuilder`` at the zenith: ``EqualAngleBuilder`` makes the
    innermost half band a single zenith cap and puts its band edges half a
    band off, while this builder starts the first band at the zenith with
    the same number of sectors as every other band.

    A cell's solid angle is Δφ · (cos θ_min − cos θ_max) ≈ Δφ · Δθ · sin θ,
    so cells near the zenith subtend *less* solid angle than cells near the
    horizon.  A statistic that weights every cell equally therefore gives
    the sky near the zenith more weight than its share of the hemisphere.
    **Not recommended for scientific analysis** – use ``EqualAreaBuilder``
    instead.

    Coordinate convention (physics / GNSS)
    ---------------------------------------
    * phi  ∈ [0, 2π)  – azimuthal angle from North, clockwise (navigation convention)
    * theta ∈ [0, π/2] – polar angle from zenith (0 = straight up,
      π/2 = horizon)

    What ``angular_resolution`` means
    ----------------------------------
    ``angular_resolution`` (degrees) is used as **both** the theta-band width
    *and* the phi-sector width::

        n_theta = ceil((π/2 − cutoff) / Δθ)
        n_phi   = ceil(2π / Δθ)
        total cells = n_theta × n_phi

    Mathematical construction
    -------------------------
    1. Theta edges are placed at ``0``, ``Δθ``, ``2Δθ``, … up to
       ``π/2 − cutoff_theta`` (the last edge is clamped exactly to
       ``π/2 − cutoff_theta`` rather than overshooting it).
    2. Phi edges are placed at 0, Δθ, 2Δθ, … and a last edge at 2π; the
       last sector is narrower when Δθ does not divide 360°.
    3. Every (theta_band, phi_sector) combination produces one cell.  The
       cell center is the midpoint of the rectangle.
    4. No special zenith cap is created; the band nearest the zenith has
       the same number of phi sectors as all other bands.

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
            ``"equirectangular"``

        """
        return GridType.EQUIRECTANGULAR.value

    def _build_grid(
        self,
    ) -> tuple[pl.DataFrame, np.ndarray, list[np.ndarray], list[np.ndarray]]:
        """Construct the equirectangular hemisphere grid.

        Returns
        -------
        grid : pl.DataFrame
            One row per cell with columns: phi, theta, phi_min, phi_max,
            theta_min, theta_max, cell_id.
        theta_lims : np.ndarray
            Outer theta edge of each band (radians).
        phi_lims : list[np.ndarray]
            Array of phi_min values for each band (identical across bands).
        cell_ids : list[np.ndarray]
            Cell-id arrays, one per band.

        """
        # Elevation mask: keep bands from the zenith (theta=0) out to
        # (pi/2 - cutoff_theta), i.e. drop the near-horizon band(s) --
        # matching EqualAreaBuilder/EqualAngleBuilder convention. Anchor the
        # last edge exactly at max_theta (rather than letting arange's step
        # overshoot it) so no band extends past the horizon or past the
        # cutoff when angular_resolution doesn't evenly divide it.
        max_theta = np.pi / 2 - self.cutoff_theta_rad

        theta_edges = np.arange(0, max_theta, self.angular_resolution_rad)
        theta_edges = np.append(theta_edges, max_theta)
        if len(theta_edges) > 1 and np.isclose(theta_edges[-1], theta_edges[-2]):
            theta_edges = theta_edges[:-1]

        # The same for the sectors: the last edge is exactly 2*pi, so the last
        # sector (narrower when angular_resolution doesn't divide 360 deg)
        # has its center inside it, and rounding in arange adds no
        # zero-width sector at 2*pi.
        phi_edges = np.arange(0, 2 * np.pi, self.angular_resolution_rad)
        phi_edges = np.append(phi_edges, 2 * np.pi)
        if np.isclose(phi_edges[-1], phi_edges[-2]):
            phi_edges = np.delete(phi_edges, -2)

        cells = []

        for i in range(len(theta_edges) - 1):
            theta_min, theta_max = theta_edges[i], theta_edges[i + 1]

            for j in range(len(phi_edges) - 1):
                phi_min, phi_max = phi_edges[j], phi_edges[j + 1]

                cells.append(
                    {
                        "phi": (phi_min + phi_max) / 2,
                        "theta": (theta_min + theta_max) / 2,
                        "phi_min": phi_min,
                        "phi_max": phi_max,
                        "theta_min": theta_min,
                        "theta_max": theta_max,
                    }
                )

        grid = pl.DataFrame(cells).with_columns(
            pl.int_range(0, pl.len()).alias("cell_id")
        )

        theta_lims = theta_edges[1:]
        phi_lims = [phi_edges[:-1] for _ in range(len(theta_edges) - 1)]
        cell_ids_list = [
            np.arange(i * (len(phi_edges) - 1), (i + 1) * (len(phi_edges) - 1))
            for i in range(len(theta_edges) - 1)
        ]

        return grid, theta_lims, phi_lims, cell_ids_list
