"""Spatial analysis of gridded VOD data.

Per-cell statistical aggregation and basic comparative plotting for
VOD datasets with pre-assigned cell IDs.

Classes
-------
``VODSpatialAnalyzer``
    Computes per-cell temporal statistics and provides simple
    histogram-based comparisons between filtering variants.

Notes
-----
* Spatial *visualization* (hemisphere maps, 3-D projections) is
  handled by the ``canvod-viz`` package.  This module is limited to
  the statistical aggregation and lightweight comparison plots that
  do not require a hemisphere renderer.
* ``compute_spatial_statistics`` returns both a *grid-aligned* array
  (length ``grid.ncells``, NaN for empty cells) and a compact
  *patch-aligned* array containing only cells with observations.  Use
  the grid-aligned form for masking / weighting; use the patch-aligned
  form when passing data to ``canvod-viz`` renderers.

"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import structlog
import xarray as xr

if TYPE_CHECKING:
    from canvod.grids.core.grid_data import GridData

logger = structlog.get_logger(__name__)


class VODSpatialAnalyzer:
    """Per-cell spatial analysis of a VOD dataset.

    Parameters
    ----------
    vod_data : xr.Dataset
        Dataset with a ``cell_id_<grid_name>`` variable already
        assigned.
    grid : GridData
        Grid instance (must expose ``.ncells``).
    grid_name : str, optional
        Suffix for the cell-ID variable.

    Raises
    ------
    ValueError
        If the expected cell-ID variable is missing.

    """

    def __init__(
        self,
        vod_data: xr.Dataset,
        grid: GridData,
        grid_name: str = "equal_area_2deg",
    ) -> None:
        """Initialize the spatial analyzer.

        Parameters
        ----------
        vod_data : xr.Dataset
            Dataset with cell IDs.
        grid : GridData
            Grid instance.
        grid_name : str, default "equal_area_2deg"
            Grid name suffix for cell IDs.

        """
        self.vod_data = vod_data
        self.grid = grid
        self.grid_name = grid_name
        self.cell_id_var = f"cell_id_{grid_name}"

        if self.cell_id_var not in vod_data:
            available = [
                str(v) for v in vod_data.data_vars if str(v).startswith("cell_id_")
            ]
            raise ValueError(
                f"Cell ID variable '{self.cell_id_var}' not found. "
                f"Available: {available}"
            )

        logger.info(
            "VODSpatialAnalyzer: grid=%s ncells=%d shape=%s",
            grid_name,
            grid.ncells,
            dict(vod_data.sizes),
        )

    def compute_spatial_statistics(
        self,
        var_name: str = "VOD",
        time_agg: str = "mean",
    ) -> dict:
        """Compute per-cell temporal statistics.

        Parameters
        ----------
        var_name : str, optional
            Data variable to aggregate over time.
        time_agg : {'mean', 'std', 'count', 'median'}
            Aggregation function applied per cell.

        Returns
        -------
        dict
            Keys:

            ``grid_aligned`` : np.ndarray
                Shape ``(grid.ncells,)``.  NaN for cells without data.
                Use for masking, weighting, or any grid-indexed operation.
            ``patch_aligned`` : np.ndarray
                Compact array containing only cells with observations.
                Use when passing data to ``canvod-viz`` renderers.
            ``cell_ids_with_data`` : np.ndarray
                Integer cell IDs corresponding to ``patch_aligned``.
            ``metadata`` : dict
                ``valid_cells``, ``total_cells``, ``coverage_percent``,
                ``variable``, ``aggregation``.

        Raises
        ------
        ValueError
            If *var_name* is not in the dataset or *time_agg* is
            unrecognised.

        """
        if var_name not in self.vod_data:
            raise ValueError(
                f"Variable '{var_name}' not found. "
                f"Available: {list(self.vod_data.data_vars)}"
            )

        _AGG_FUNCS = {"mean", "std", "count", "median"}
        if time_agg not in _AGG_FUNCS:
            raise ValueError(
                f"Unknown aggregation '{time_agg}'; expected one of {_AGG_FUNCS}"
            )

        logger.info("spatial statistics: var=%s agg=%s", var_name, time_agg)

        var_data = self.vod_data[var_name]
        cell_ids = self.vod_data[self.cell_id_var]

        df = pd.DataFrame(
            {
                "cell_id": cell_ids.values.ravel(),
                "value": var_data.values.ravel(),
            }
        )
        df = df.dropna()

        if len(df) == 0:
            logger.warning("no valid data after removing NaN values")
            return {
                "grid_aligned": np.full(self.grid.ncells, np.nan),
                "patch_aligned": np.array([]),
                "cell_ids_with_data": np.array([], dtype=int),
                "metadata": {
                    "valid_cells": 0,
                    "total_cells": self.grid.ncells,
                    "coverage_percent": 0.0,
                    "variable": var_name,
                    "aggregation": time_agg,
                },
            }

        logger.debug(
            "%d valid observations across %d cells",
            len(df),
            df["cell_id"].nunique(),
        )

        cell_stats = getattr(df.groupby("cell_id")["value"], time_agg)()

        grid_aligned = np.full(self.grid.ncells, np.nan)
        patch_aligned: list[float] = []
        cell_ids_with_data: list[int] = []

        for cell_id, value in cell_stats.items():
            cell_id_int = int(cell_id)
            if 0 <= cell_id_int < self.grid.ncells:
                grid_aligned[cell_id_int] = value
                patch_aligned.append(value)
                cell_ids_with_data.append(cell_id_int)

        n_valid = len(patch_aligned)
        logger.info("spatial stats: %d/%d cells with data", n_valid, self.grid.ncells)

        return {
            "grid_aligned": grid_aligned,
            "patch_aligned": np.array(patch_aligned),
            "cell_ids_with_data": np.array(cell_ids_with_data, dtype=int),
            "metadata": {
                "valid_cells": n_valid,
                "total_cells": self.grid.ncells,
                "coverage_percent": (n_valid / self.grid.ncells) * 100,
                "variable": var_name,
                "aggregation": time_agg,
            },
        }

    def compare_filtering_methods(
        self,
        original_var: str = "VOD",
        filtered_var: str = "VOD_filtered",
        figsize: tuple = (16, 6),
        ax: tuple | None = None,
    ) -> tuple[plt.Figure, np.ndarray]:
        """Histogram comparison of original vs filtered VOD distributions.

        Parameters
        ----------
        original_var : str, optional
            Unfiltered variable name.
        filtered_var : str, optional
            Filtered variable name.
        figsize : tuple, optional
            Figure size when *ax* is ``None``.
        ax : tuple of two plt.Axes or None, optional
            Pre-existing axes pair.  Created if ``None``.

        Returns
        -------
        fig, axes : plt.Figure, np.ndarray of plt.Axes

        """
        if ax is None:
            fig, axes = plt.subplots(1, 2, figsize=figsize)
        else:
            axes = ax
            fig = axes[0].figure

        stats_orig = self.compute_spatial_statistics(original_var, "mean")
        stats_filt = self.compute_spatial_statistics(filtered_var, "mean")

        data_orig = stats_orig["grid_aligned"]
        data_filt = stats_filt["grid_aligned"]

        axes[0].hist(
            data_orig[np.isfinite(data_orig)], bins=50, alpha=0.7, label="Original"
        )
        axes[0].set_title("Original VOD Distribution")
        axes[0].set_xlabel("VOD")
        axes[0].set_ylabel("Frequency")

        axes[1].hist(
            data_filt[np.isfinite(data_filt)],
            bins=50,
            alpha=0.7,
            label="Filtered",
            color="green",
        )
        axes[1].set_title("Filtered VOD Distribution")
        axes[1].set_xlabel("VOD")
        axes[1].set_ylabel("Frequency")

        fig.tight_layout()
        return cast(plt.Figure, fig), np.asarray(axes)
