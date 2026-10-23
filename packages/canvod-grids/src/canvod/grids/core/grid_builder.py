"""Base class for hemisphere grid builders."""

from abc import ABC, abstractmethod
from typing import Any

import numpy as np
import polars as pl
import structlog

from canvod.grids.core.grid_data import GridData


class BaseGridBuilder(ABC):
    """Abstract base for hemispherical grid builders.

    Parameters
    ----------
    angular_resolution : float
        Angular resolution in degrees
    cutoff_theta : float
        Maximum polar angle cutoff in degrees
    phi_rotation : float
        Rotation angle in degrees (applied to all phi values)

    """

    def __init__(
        self,
        angular_resolution: float = 2,
        cutoff_theta: float = 0,
        phi_rotation: float = 0,
    ) -> None:
        """Initialize the grid builder.

        Parameters
        ----------
        angular_resolution : float, default 2
            Angular resolution in degrees.
        cutoff_theta : float, default 0
            Maximum polar angle cutoff in degrees.
        phi_rotation : float, default 0
            Rotation angle in degrees.

        """
        self.angular_resolution = angular_resolution
        self.angular_resolution_rad = np.deg2rad(angular_resolution)
        self.cutoff_theta = cutoff_theta
        self.cutoff_theta_rad = np.deg2rad(cutoff_theta)
        self.phi_rotation = phi_rotation
        self.phi_rotation_rad = np.deg2rad(phi_rotation)
        self._logger = structlog.get_logger(__name__)

    @abstractmethod
    def _build_grid(
        self,
    ) -> (
        tuple[pl.DataFrame, np.ndarray, list[np.ndarray], list[np.ndarray]]
        | tuple[
            pl.DataFrame, np.ndarray, list[np.ndarray], list[np.ndarray], dict[str, Any]
        ]
    ):
        """Build grid.

        Returns
        -------
        grid : pl.DataFrame
            Grid cells
        theta_lims : np.ndarray
            Theta band limits
        phi_lims : list[np.ndarray]
            Phi limits per band
        cell_ids : list[np.ndarray]
            Cell IDs per band
        extra_kwargs : dict, optional
            Additional metadata

        """

    @abstractmethod
    def get_grid_type(self) -> str:
        """Get grid type identifier."""

    def build(self) -> GridData:
        """Build hemisphere grid.

        Returns
        -------
        GridData
            Complete grid data structure

        """
        self._logger.info(
            "grid_build_started",
            grid_type=self.get_grid_type(),
            angular_resolution=self.angular_resolution,
        )

        result = self._build_grid()

        if len(result) == 4:
            grid, theta_lims, phi_lims, cell_ids = result
            extra_kwargs = {}
        elif len(result) == 5:
            grid, theta_lims, phi_lims, cell_ids, extra_kwargs = result
        else:
            raise ValueError(f"Invalid grid builder result: {len(result)} elements")

        # Apply phi rotation if specified (vectorized operations)
        if self.phi_rotation_rad != 0:
            grid = grid.with_columns(
                [(pl.col("phi") + self.phi_rotation_rad) % (2 * np.pi)]
            )

            if "phi_min" in grid.columns:
                # Wrap phi_min into [0, 2*pi) but offset phi_max by the same
                # rotation (not re-wrapped independently) so each cell's
                # angular width (phi_max - phi_min) is preserved even when
                # the rotated interval straddles the 0/2*pi seam. Wrapping
                # both bounds independently collapses full-circle cells
                # (e.g. the zenith cap, phi_min=0/phi_max=2*pi) to zero
                # width and flips phi_max < phi_min for any other cell that
                # crosses the seam after rotation, producing negative solid
                # angles downstream. phi_max may end up > 2*pi here, which
                # is fine: consumers use phi_max - phi_min directly (e.g.
                # GridData._geometric_solid_angles, get_patches), and polar
                # axes wrap angles > 2*pi visually.
                grid = grid.with_columns(
                    [(pl.col("phi_max") - pl.col("phi_min")).alias("_phi_width")]
                )
                grid = grid.with_columns(
                    [
                        (
                            (pl.col("phi_min") + self.phi_rotation_rad) % (2 * np.pi)
                        ).alias("phi_min")
                    ]
                )
                grid = grid.with_columns(
                    [(pl.col("phi_min") + pl.col("_phi_width")).alias("phi_max")]
                ).drop("_phi_width")

        self._logger.info("grid_build_complete", ncells=len(grid))

        # Merge builder metadata into any extra_kwargs metadata
        builder_meta = {
            "angular_resolution": self.angular_resolution,
            "cutoff_theta": self.cutoff_theta,
            "phi_rotation": self.phi_rotation,
        }
        if extra_kwargs.get("metadata"):
            extra_kwargs["metadata"] = {**builder_meta, **extra_kwargs["metadata"]}
        else:
            extra_kwargs["metadata"] = builder_meta

        return GridData(
            grid=grid,
            theta_lims=theta_lims,
            phi_lims=phi_lims,
            cell_ids=cell_ids,
            grid_type=self.get_grid_type(),
            **extra_kwargs,
        )
