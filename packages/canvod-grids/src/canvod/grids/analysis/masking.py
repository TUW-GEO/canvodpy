"""Spatial masking for hemispherical grid cells.

Provides tools to create boolean masks for selecting subsets of grid cells
based on geometric constraints, data quality, or custom criteria.

Classes
-------
SpatialMask             – builder for boolean cell-selection masks.

Convenience functions
---------------------
``create_hemisphere_mask``  – north / south / east / west mask.
``create_elevation_mask``   – elevation-angle-based mask.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, cast

import numpy as np

if TYPE_CHECKING:
    from canvod.grids.core.grid_data import GridData


class SpatialMask:
    """Create spatial masks for grid cells.

    Masks are boolean arrays where ``True`` = include cell,
    ``False`` = exclude cell.  Multiple constraints can be combined
    with AND or OR logic.

    Parameters
    ----------
    grid : GridData
        Grid instance.

    Examples
    --------
    >>> mask = SpatialMask(grid)
    >>> mask.add_phi_range(0, np.pi)          # Northern hemisphere
    >>> mask.add_theta_range(0, np.pi / 3)    # Exclude low elevations
    >>> mask.add_quality_threshold('mean_snr', min_value=40)
    >>> spatial_mask = mask.compute()          # Returns boolean array

    """

    def __init__(self, grid: GridData) -> None:
        """Initialize the spatial mask builder.

        Parameters
        ----------
        grid : GridData
            Grid instance.

        """
        self.grid = grid
        self.masks: list[tuple[str, np.ndarray]] = []
        self._grid_df = grid.grid

    # ------------------------------------------------------------------
    # Constraint builders
    # ------------------------------------------------------------------

    def add_phi_range(
        self, phi_min: float, phi_max: float, degrees: bool = False
    ) -> SpatialMask:
        """Add azimuth angle constraint.

        Parameters
        ----------
        phi_min : float
            Minimum azimuth angle.
        phi_max : float
            Maximum azimuth angle.
        degrees : bool
            If ``True``, angles are in degrees; otherwise radians.

        Returns
        -------
        SpatialMask
            Self for chaining.

        Notes
        -----
        Handles wraparound at 0°/360° correctly.
        Example: ``phi_range(350, 10)`` includes both 350°–360° and 0°–10°.

        """
        if degrees:
            phi_min = np.radians(phi_min)
            phi_max = np.radians(phi_max)

        phi = self._grid_df["phi"].to_numpy()

        # Normalize to [0, 2π)
        phi = np.mod(phi, 2 * np.pi)
        phi_min = np.mod(phi_min, 2 * np.pi)
        phi_max = np.mod(phi_max, 2 * np.pi)

        if phi_min <= phi_max:
            mask = (phi >= phi_min) & (phi <= phi_max)
        else:
            # Wraparound: e.g. 350° to 10°
            mask = (phi >= phi_min) | (phi <= phi_max)

        self.masks.append(("phi_range", mask))
        return self

    def add_theta_range(
        self, theta_min: float, theta_max: float, degrees: bool = False
    ) -> SpatialMask:
        """Add polar angle constraint.

        Parameters
        ----------
        theta_min : float
            Minimum polar angle (0 = zenith).
        theta_max : float
            Maximum polar angle (π/2 = horizon).
        degrees : bool
            If ``True``, angles are in degrees; otherwise radians.

        Returns
        -------
        SpatialMask
            Self for chaining.

        Notes
        -----
        ``theta = 0°`` is zenith (straight up), ``theta = 90°`` is horizon.
        To exclude low elevations, use ``theta_max < 90°``.

        """
        if degrees:
            theta_min = np.radians(theta_min)
            theta_max = np.radians(theta_max)

        theta = self._grid_df["theta"].to_numpy()
        mask = (theta >= theta_min) & (theta <= theta_max)

        self.masks.append(("theta_range", mask))
        return self

    def add_elevation_range(
        self, elev_min: float, elev_max: float, degrees: bool = True
    ) -> SpatialMask:
        """Add elevation angle constraint (complementary to theta).

        Parameters
        ----------
        elev_min : float
            Minimum elevation angle (0 = horizon, 90 = zenith).
        elev_max : float
            Maximum elevation angle.
        degrees : bool
            If ``True``, angles are in degrees; otherwise radians.
            Default: ``True``.

        Returns
        -------
        SpatialMask
            Self for chaining.

        Notes
        -----
        ``elevation = 90° − theta``.  This is more intuitive for users
        who think in elevation angles.

        """
        if degrees:
            elev_min_rad = np.radians(elev_min)
            elev_max_rad = np.radians(elev_max)
        else:
            elev_min_rad = elev_min
            elev_max_rad = elev_max

        # Convert elevation → theta: theta = π/2 − elevation
        theta_max = np.pi / 2 - elev_min_rad
        theta_min = np.pi / 2 - elev_max_rad

        return self.add_theta_range(theta_min, theta_max, degrees=False)

    def add_cell_ids(self, cell_ids: list[int] | np.ndarray) -> SpatialMask:
        """Include specific cell IDs.

        Parameters
        ----------
        cell_ids : list[int] or np.ndarray
            Cell IDs to include.

        Returns
        -------
        SpatialMask
            Self for chaining.

        """
        mask = np.zeros(self.grid.ncells, dtype=bool)
        mask[cell_ids] = True

        self.masks.append(("cell_ids", mask))
        return self

    def add_exclude_cell_ids(self, cell_ids: list[int] | np.ndarray) -> SpatialMask:
        """Exclude specific cell IDs.

        Parameters
        ----------
        cell_ids : list[int] or np.ndarray
            Cell IDs to exclude.

        Returns
        -------
        SpatialMask
            Self for chaining.

        """
        mask = np.ones(self.grid.ncells, dtype=bool)
        mask[cell_ids] = False

        self.masks.append(("exclude_cell_ids", mask))
        return self

    def add_quality_threshold(
        self,
        var_name: str,
        min_value: float | None = None,
        max_value: float | None = None,
    ) -> SpatialMask:
        """Add data quality threshold based on grid cell properties.

        Parameters
        ----------
        var_name : str
            Variable name in grid (e.g. ``'mean_snr'``,
            ``'n_observations'``).
        min_value : float, optional
            Minimum allowed value.
        max_value : float, optional
            Maximum allowed value.

        Returns
        -------
        SpatialMask
            Self for chaining.

        Raises
        ------
        ValueError
            If *var_name* doesn't exist in the grid DataFrame.

        """
        if var_name not in self._grid_df.columns:
            available = list(self._grid_df.columns)
            raise ValueError(
                f"Variable '{var_name}' not found in grid. Available: {available}"
            )

        values = self._grid_df[var_name].to_numpy()
        mask = np.ones(self.grid.ncells, dtype=bool)

        if min_value is not None:
            mask = mask & (values >= min_value)
        if max_value is not None:
            mask = mask & (values <= max_value)

        self.masks.append((f"{var_name}_threshold", mask))
        return self

    def add_boundary_cells(self, exclude: bool = True) -> SpatialMask:
        """Include or exclude boundary cells.

        Parameters
        ----------
        exclude : bool
            If ``True``, exclude boundary cells; if ``False``, include
            only boundary cells.

        Returns
        -------
        SpatialMask
            Self for chaining.

        Raises
        ------
        ValueError
            If the grid does not have an ``'is_boundary'`` column.

        Notes
        -----
        Only works if the grid DataFrame contains an ``'is_boundary'``
        column.

        """
        if "is_boundary" not in self._grid_df.columns:
            raise ValueError("Grid does not have 'is_boundary' information")

        is_boundary = self._grid_df["is_boundary"].to_numpy()
        mask = ~is_boundary if exclude else is_boundary

        self.masks.append(("boundary_cells", mask))
        return self

    def add_custom_mask(
        self,
        mask: np.ndarray | Callable,
        name: str = "custom",
    ) -> SpatialMask:
        """Add custom mask or mask-generating callable.

        Parameters
        ----------
        mask : np.ndarray or callable
            * If array: boolean mask of shape ``(ncells,)``.
            * If callable: function ``(grid: GridData) -> np.ndarray``.
        name : str
            Label for this mask (used in summary).

        Returns
        -------
        SpatialMask
            Self for chaining.

        Raises
        ------
        ValueError
            If the resulting array has wrong shape or dtype.

        Examples
        --------
        >>> custom = np.array([True, False, True, ...])
        >>> mask.add_custom_mask(custom)

        >>> def high_snr_north(grid):
        ...     snr   = grid.grid['mean_snr'].to_numpy()
        ...     phi   = grid.grid['phi'].to_numpy()
        ...     return (snr > 40) & (phi < np.pi)
        >>> mask.add_custom_mask(high_snr_north)

        """
        if callable(mask):
            mask_fn = cast(Callable[[Any], np.ndarray], mask)
            mask_array = mask_fn(self.grid)
        else:
            mask_array = mask

        if not isinstance(mask_array, np.ndarray):
            raise ValueError("Custom mask must be numpy array or return numpy array")
        if mask_array.shape != (self.grid.ncells,):
            raise ValueError(
                f"Custom mask shape {mask_array.shape} doesn't match "
                f"grid size ({self.grid.ncells},)"
            )
        if mask_array.dtype != bool:
            raise ValueError("Custom mask must be boolean dtype")

        self.masks.append((name, mask_array))
        return self

    def add_radial_sector(
        self,
        center_phi: float,
        sector_width: float,
        theta_min: float = 0.0,
        theta_max: float = np.pi / 2,
        degrees: bool = True,
    ) -> SpatialMask:
        """Add radial sector (wedge) mask.

        Parameters
        ----------
        center_phi : float
            Center azimuth of sector.
        sector_width : float
            Full angular width of sector.
        theta_min : float
            Minimum polar angle (radial inner bound).
        theta_max : float
            Maximum polar angle (radial outer bound).
        degrees : bool
            If ``True``, all angles in degrees; otherwise radians.

        Returns
        -------
        SpatialMask
            Self for chaining.

        Examples
        --------
        >>> # Northern sector, 30° wide, excluding low elevations
        >>> mask.add_radial_sector(center_phi=0, sector_width=30,
        ...                        theta_max=60, degrees=True)

        """
        if degrees:
            center_phi = np.radians(center_phi)
            sector_width = np.radians(sector_width)
            theta_min = np.radians(theta_min)
            theta_max = np.radians(theta_max)

        half_width = sector_width / 2
        self.add_phi_range(
            center_phi - half_width,
            center_phi + half_width,
            degrees=False,
        )
        self.add_theta_range(theta_min, theta_max, degrees=False)

        return self

    # ------------------------------------------------------------------
    # Computation & introspection
    # ------------------------------------------------------------------

    def compute(self, mode: str = "AND") -> np.ndarray:
        """Compute final combined boolean mask.

        Parameters
        ----------
        mode : str
            Combination mode:

            * ``'AND'`` – all constraints must be satisfied (intersection).
            * ``'OR'``  – at least one constraint must be satisfied (union).

        Returns
        -------
        np.ndarray
            Boolean array of shape ``(ncells,)`` where ``True`` = include.

        Raises
        ------
        ValueError
            If no masks have been added or *mode* is unknown.

        """
        if not self.masks:
            raise ValueError("No masks added. Use add_* methods before compute()")

        if mode.upper() == "AND":
            combined = np.ones(self.grid.ncells, dtype=bool)
            for _name, mask in self.masks:
                combined = combined & mask
        elif mode.upper() == "OR":
            combined = np.zeros(self.grid.ncells, dtype=bool)
            for _name, mask in self.masks:
                combined = combined | mask
        else:
            raise ValueError(f"Unknown mode: {mode}. Use 'AND' or 'OR'")

        return combined

    def get_mask_summary(self) -> dict:
        """Get summary of all added masks.

        Returns
        -------
        dict
            Dictionary with mask names and per-mask / combined cell counts.

        """
        summary: dict = {"total_cells": self.grid.ncells, "masks": []}

        for name, mask in self.masks:
            n_included = int(mask.sum())
            summary["masks"].append(
                {
                    "name": name,
                    "n_cells_included": n_included,
                    "fraction_included": n_included / self.grid.ncells,
                }
            )

        if self.masks:
            combined_and = self.compute(mode="AND")
            combined_or = self.compute(mode="OR")
            summary["combined"] = {
                "AND": {
                    "n_cells": int(combined_and.sum()),
                    "fraction": float(combined_and.sum() / self.grid.ncells),
                },
                "OR": {
                    "n_cells": int(combined_or.sum()),
                    "fraction": float(combined_or.sum() / self.grid.ncells),
                },
            }

        return summary

    def clear(self) -> SpatialMask:
        """Clear all masks.

        Returns
        -------
        SpatialMask
            Self for chaining.

        """
        self.masks = []
        return self

    def __repr__(self) -> str:
        """Return the developer-facing representation.

        Returns
        -------
        str
            Representation string.

        """
        mask_names = [name for name, _ in self.masks]
        return (
            f"SpatialMask(grid={self.grid.grid_type}, "
            f"n_masks={len(self.masks)}, masks={mask_names})"
        )


# ----------------------------------------------------------------------
# Convenience functions
# ----------------------------------------------------------------------


def create_hemisphere_mask(grid: GridData, hemisphere: str = "north") -> np.ndarray:
    """Create mask for a cardinal hemisphere.

    Parameters
    ----------
    grid : GridData
        Grid instance.
    hemisphere : str
        One of ``'north'``, ``'south'``, ``'east'``, ``'west'``.

    Returns
    -------
    np.ndarray
        Boolean mask.

    Raises
    ------
    ValueError
        If *hemisphere* is not recognized.

    """
    _RANGES = {
        "north": (315, 45),
        "south": (135, 225),
        "east": (45, 135),
        "west": (225, 315),
    }

    key = hemisphere.lower()
    if key not in _RANGES:
        raise ValueError(
            f"Unknown hemisphere: {hemisphere}. Choose from {list(_RANGES.keys())}"
        )

    mask = SpatialMask(grid)
    mask.add_phi_range(*_RANGES[key], degrees=True)
    return mask.compute()


def create_elevation_mask(
    grid: GridData, min_elevation: float = 30.0, max_elevation: float = 90.0
) -> np.ndarray:
    """Create mask based on elevation angle.

    Parameters
    ----------
    grid : GridData
        Grid instance.
    min_elevation : float
        Minimum elevation angle in degrees (default: 30°).
    max_elevation : float
        Maximum elevation angle in degrees (default: 90°).

    Returns
    -------
    np.ndarray
        Boolean mask.

    """
    mask = SpatialMask(grid)
    mask.add_elevation_range(min_elevation, max_elevation, degrees=True)
    return mask.compute()
