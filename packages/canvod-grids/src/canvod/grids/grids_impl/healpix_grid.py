"""HEALPix grid implementation."""

import numpy as np
import polars as pl

from canvod.grids.core.grid_builder import BaseGridBuilder
from canvod.grids.core.grid_types import GridType


class HEALPixBuilder(BaseGridBuilder):
    """HEALPix tessellation (Hierarchical Equal Area isoLatitude Pixelization).

    HEALPix partitions the sphere into 12 base pixels arranged at equal
    latitudes.  Each base pixel is recursively subdivided into 4 children,
    producing ``12 × nside²`` pixels on the full sphere, all with *exactly*
    the same solid angle.  This strict equal-area property makes HEALPix
    the gold standard for pixelisations that must be unbiased under
    solid-angle weighting.

    This builder delegates the pixel geometry entirely to the ``healpy``
    library.  It filters the full-sphere pixelisation down to the northern
    hemisphere and stores approximate bounding boxes (``phi_min/max``,
    ``theta_min/max``) derived from the pixel resolution.  The bounding
    boxes are **not** the true pixel boundaries (which are curvilinear);
    they are only approximations suitable for quick spatial queries.  For
    exact pixel membership use ``healpy.ang2pix`` directly.

    Coordinate convention
    ---------------------
    HEALPix natively uses colatitude ``theta ∈ [0, π]`` (0 = North Pole)
    and longitude ``phi ∈ [0, 2π)``.  This matches the GNSS convention used
    elsewhere in canvodpy: theta = 0 is the zenith, theta = π/2 is the
    horizon.  **No coordinate transform is applied.**

    What ``nside`` (resolution) means
    ----------------------------------
    ``nside`` is the single resolution parameter of HEALPix.  It must be a
    power of 2.  The key derived quantities are::

        n_pixels   = 12 × nside²           (full sphere)
        pixel_area = 4π / n_pixels          (steradians, exact)
        resolution ≈ √(pixel_area)          (approximate angular diameter)
                   ≈ 58.6° / nside         (degrees)

    | nside | Pixels (full) | Approx resolution | Pixel area (sr) |
    |-------|---------------|-------------------|-----------------|
    | 1     | 12            | 58.6°             | 1.049           |
    | 2     | 48            | 29.3°             | 0.262           |
    | 4     | 192           | 14.7°             | 0.065           |
    | 8     | 768           | 7.3°              | 0.016           |
    | 16    | 3 072         | 3.7°              | 0.004           |
    | 32    | 12 288        | 1.8°              | 0.001           |

    When ``nside`` is not provided, it is estimated from ``angular_resolution``
    and rounded to the nearest power of 2::

        nside_estimate = round_to_pow2( √(3/π) × 60 / angular_resolution )

    Mathematical construction
    -------------------------
    HEALPix construction is performed entirely by ``healpy``.  At a high
    level:

    1. The sphere is divided into 12 congruent base pixels (a curvilinear
       quadrilateral arrangement at three latitude zones: polar caps and
       equatorial belt).
    2. Each base pixel is subdivided into ``nside²`` equal-area children
       using a hierarchical quadtree.
    3. Pixel centers are returned by ``healpy.pix2ang(nside, ipix)`` in
       RING ordering (pixels ordered by increasing colatitude).
    4. This builder keeps only pixels with ``theta ≤ π/2 − cutoff_theta``
       (northern hemisphere above the elevation mask).

    Parameters
    ----------
    angular_resolution : float
        Approximate angular resolution in degrees.  Used only to derive
        ``nside`` when that parameter is not given explicitly.
    cutoff_theta : float
        Elevation mask angle in degrees.  Pixels with colatitude
        ``theta > π/2 − cutoff_theta`` (i.e. below the mask) are excluded.
    nside : int or None
        HEALPix resolution parameter.  Must be a power of 2.  If ``None``,
        estimated from ``angular_resolution``.
    phi_rotation : float
        Rigid azimuthal rotation applied after construction, in degrees.

    Raises
    ------
    ImportError
        If ``healpy`` is not installed.
    ValueError
        If ``nside`` is not a power of 2.

    """

    def __init__(
        self,
        angular_resolution: float = 2,
        cutoff_theta: float = 0,
        nside: int | None = None,
        phi_rotation: float = 0,
    ) -> None:
        """Initialize the HEALPix grid builder.

        Parameters
        ----------
        angular_resolution : float, default 2
            Angular resolution in degrees.
        cutoff_theta : float, default 0
            Maximum polar angle cutoff in degrees.
        nside : int | None, optional
            HEALPix nside parameter.
        phi_rotation : float, default 0
            Rotation angle in degrees.

        """
        super().__init__(angular_resolution, cutoff_theta, phi_rotation)

        # Determine nside
        if nside is None:
            nside_estimate = int(np.sqrt(3 / np.pi) * 60 / angular_resolution)
            self.nside = 2 ** max(0, int(np.round(np.log2(nside_estimate))))
        else:
            if nside < 1 or (nside & (nside - 1)) != 0:
                raise ValueError(f"nside must be a power of 2, got {nside}")
            self.nside = nside

        # Import healpy
        try:
            import healpy as hp  # type: ignore[unresolved-import]

            self.hp = hp
        except ImportError as e:
            raise ImportError(
                "healpy is required for HEALPix grid. Install with: uv add healpy"
            ) from e

        pixel_size_arcmin = self.hp.nside2resol(self.nside, arcmin=True)
        self.actual_angular_resolution = pixel_size_arcmin / 60.0

        self._logger.info(
            f"HEALPix: nside={self.nside}, "
            f"requested_res={angular_resolution:.2f}°, "
            f"actual_res={self.actual_angular_resolution:.2f}°"
        )

    def get_grid_type(self) -> str:
        """Return the grid-type identifier string.

        Returns
        -------
        str
            ``"healpix"``

        """
        return GridType.HEALPIX.value

    def _build_grid(
        self,
    ) -> tuple[pl.DataFrame, np.ndarray, list[np.ndarray], list[np.ndarray]]:
        """Build HEALPix grid for the northern hemisphere.

        Iterates over all ``12 × nside²`` pixels, retains those with
        ``theta ≤ π/2 − cutoff_theta``, and constructs approximate
        bounding boxes from the pixel resolution.

        Returns
        -------
        grid : pl.DataFrame
            One row per pixel.  Contains phi, theta (center), approximate
            bounding-box limits, ``healpix_ipix`` (RING-ordered pixel index),
            and ``healpix_nside``.
        theta_lims : np.ndarray
            Synthetic evenly-spaced theta limits (interface compatibility only).
        phi_lims : list[np.ndarray]
            Synthetic evenly-spaced phi limits (interface compatibility only).
        cell_ids : list[np.ndarray]
            Single-element list containing the valid pixel indices.

        """
        npix = self.hp.nside2npix(self.nside)

        cells = []
        valid_pixels = []

        for ipix in range(npix):
            theta, phi = self.hp.pix2ang(self.nside, ipix)

            # Keep only northern hemisphere above the elevation mask
            if theta > (np.pi / 2 - self.cutoff_theta_rad):
                continue

            pixel_radius = self.hp.nside2resol(self.nside)

            cells.append(
                {
                    "phi": float(phi),
                    "theta": float(theta),
                    "phi_min": float(max(0, phi - pixel_radius / 2)),
                    "phi_max": float(min(2 * np.pi, phi + pixel_radius / 2)),
                    "theta_min": float(max(0, theta - pixel_radius / 2)),
                    "theta_max": float(min(np.pi / 2, theta + pixel_radius / 2)),
                    "healpix_ipix": int(ipix),
                    "healpix_nside": int(self.nside),
                }
            )
            valid_pixels.append(int(ipix))

        if len(cells) == 0:
            raise ValueError("No valid HEALPix pixels found in hemisphere")

        grid = pl.DataFrame(cells)

        grid = grid.with_columns(
            [
                pl.col("healpix_ipix").cast(pl.Int64),
                pl.col("healpix_nside").cast(pl.Int64),
            ]
        ).with_columns(pl.int_range(0, pl.len()).alias("cell_id"))

        theta_unique = sorted(grid["theta"].unique())
        n_theta_bands = len(theta_unique)

        # NOTE: These limits are SYNTHETIC and do NOT correspond to actual
        # HEALPix pixel boundaries. They exist only for interface
        # compatibility with ring-based grids. For spatial queries, use the
        # per-pixel theta_min/max and phi_min/max columns instead.
        theta_lims = np.linspace(0, np.pi / 2, min(n_theta_bands, 20))
        phi_lims = [np.linspace(0, 2 * np.pi, 20) for _ in range(len(theta_lims))]

        cell_ids_list = [np.array(valid_pixels, dtype=np.int64)]

        return grid, theta_lims, phi_lims, cell_ids_list

    def get_healpix_info(self) -> dict:
        """Get HEALPix-specific information.

        Returns
        -------
        info : dict
            Keys: ``nside``, ``npix_total``, ``pixel_area_sr``,
            ``pixel_area_arcmin2``, ``resolution_arcmin``,
            ``resolution_deg``, ``max_pixel_radius_deg``.

        """
        return {
            "nside": self.nside,
            "npix_total": self.hp.nside2npix(self.nside),
            "pixel_area_sr": self.hp.nside2pixarea(self.nside),
            "pixel_area_arcmin2": (
                self.hp.nside2pixarea(self.nside, degrees=True) * 3600
            ),
            "resolution_arcmin": self.hp.nside2resol(self.nside, arcmin=True),
            "resolution_deg": self.actual_angular_resolution,
            "max_pixel_radius_deg": np.rad2deg(self.hp.max_pixrad(self.nside)),
        }
