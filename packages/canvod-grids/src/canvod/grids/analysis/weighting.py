"""Weighting strategies for spatial aggregation of hemispherical grid data.

Provides tools to calculate and combine different weighting schemes for
computing weighted means across grid cells.  Critical for unbiased spatial
statistics when cells have different sizes or data quality.

Classes
-------
WeightCalculator        – builder for combined spatial weights.

Convenience functions
---------------------
``compute_uniform_weights``  – equal weight per cell.
``compute_area_weights``     – solid-angle-only weights.

Notes
-----
* Supported weight types: ``solid_angle``, ``observation_count``,
  ``snr``, ``sin_elevation``, ``inverse_variance``, ``custom``.
* Multiple weights are combined element-wise (multiply or add) and
  optionally normalized to sum to 1.
* Dask-backed datasets are handled efficiently: only scalar statistics
  are computed eagerly; masks stay lazy.

"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

import dask.array as da
import numpy as np
import structlog
import xarray as xr

if TYPE_CHECKING:
    from canvod.grids.core.grid_data import GridData

logger = structlog.get_logger(__name__)


class WeightCalculator:
    """Calculate and combine weights for spatial aggregation.

    Parameters
    ----------
    grid : GridData
        Grid instance.
    ds : xr.Dataset or None
        Dataset with data variables (required for data-dependent weights
        such as ``observation_count``, ``snr``, ``inverse_variance``).

    Examples
    --------
    >>> weights = WeightCalculator(grid, vod_ds)
    >>> weights.add_weight('solid_angle')
    >>> weights.add_weight('observation_count', normalize=True)
    >>> total_weights = weights.compute()

    """

    def __init__(self, grid: GridData, ds: xr.Dataset | None = None) -> None:
        """Initialize the weight calculator.

        Parameters
        ----------
        grid : GridData
            Grid instance.
        ds : xr.Dataset | None, optional
            Dataset with data variables for data-dependent weights.

        """
        self.grid = grid
        self.ds = ds
        self.weights: dict[str, np.ndarray] = {}
        self.weight_params: dict[str, dict] = {}
        self._grid_df = grid.grid

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_weight(
        self,
        weight_type: str,
        normalize: bool = True,
        **kwargs: Any,
    ) -> WeightCalculator:
        """Add a weight component.

        Parameters
        ----------
        weight_type : str
            One of ``'solid_angle'``, ``'observation_count'``,
            ``'snr'``, ``'sin_elevation'``, ``'inverse_variance'``,
            ``'custom'``.
        normalize : bool
            If ``True``, normalize this component to sum to 1.0 before
            combination.
        **kwargs
            Weight-specific parameters (see individual ``_compute_*``
            methods).

        Returns
        -------
        WeightCalculator
            Self for chaining.

        Examples
        --------
        >>> calc.add_weight('solid_angle')
        >>> calc.add_weight('observation_count', var_name='VOD', normalize=True)
        >>> calc.add_weight('custom', values=my_weights, normalize=False)

        """
        if weight_type in self.weights:
            logger.warning(f"Weight '{weight_type}' already exists, overwriting")

        _DISPATCH = {
            "solid_angle": self._compute_solid_angle_weight,
            "observation_count": self._compute_observation_count_weight,
            "snr": self._compute_snr_weight,
            "sin_elevation": self._compute_sin_elevation_weight,
            "inverse_variance": self._compute_inverse_variance_weight,
            "custom": self._compute_custom_weight,
        }

        if weight_type not in _DISPATCH:
            raise ValueError(
                f"Unknown weight_type: {weight_type}. Valid: {list(_DISPATCH.keys())}"
            )

        weight = _DISPATCH[weight_type](**kwargs)

        if normalize:
            weight = self._normalize_weights(weight)

        self.weights[weight_type] = weight
        self.weight_params[weight_type] = {"normalize": normalize, **kwargs}
        return self

    def compute(
        self,
        combination: Literal["multiply", "add"] = "multiply",
        normalize_final: bool = True,
    ) -> np.ndarray:
        """Compute final combined weights.

        Parameters
        ----------
        combination : str
            ``'multiply'`` – element-wise product (default).
            ``'add'``      – element-wise sum.
        normalize_final : bool
            If ``True``, normalize the final array to sum to 1.0.

        Returns
        -------
        np.ndarray
            Weight array of shape ``(ncells,)``.

        Raises
        ------
        ValueError
            If no weights have been added or *combination* is unknown.

        """
        if not self.weights:
            raise ValueError("No weights added. Use add_weight() before compute()")

        if combination == "multiply":
            combined = np.ones(self.grid.ncells)
            for w in self.weights.values():
                combined = combined * w
        elif combination == "add":
            combined = np.zeros(self.grid.ncells)
            for w in self.weights.values():
                combined = combined + w
        else:
            raise ValueError(f"Unknown combination: {combination}")

        if normalize_final:
            combined = self._normalize_weights(combined)

        n_nonzero = int(np.sum(combined > 0))
        nonzero_vals = combined[combined > 0]
        logger.info(
            f"Computed weights: {n_nonzero}/{self.grid.ncells} cells with "
            f"non-zero weight, min={nonzero_vals.min():.6f}, max={combined.max():.6f}"
        )
        return combined

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def get_weight_summary(self) -> dict:
        """Summary statistics for each weight component.

        Returns
        -------
        dict
            Nested dict keyed by weight type.

        """
        summary: dict = {"components": {}}
        for wtype, weight in self.weights.items():
            nonzero = weight > 0
            summary["components"][wtype] = {
                "n_nonzero": int(nonzero.sum()),
                "fraction_nonzero": float(nonzero.sum() / self.grid.ncells),
                "min": float(weight[nonzero].min()) if nonzero.any() else 0.0,
                "max": float(weight.max()),
                "mean": float(weight[nonzero].mean()) if nonzero.any() else 0.0,
                "params": self.weight_params[wtype],
            }
        return summary

    def remove_weight(self, weight_type: str) -> WeightCalculator:
        """Remove a weight component.

        Parameters
        ----------
        weight_type : str
            Weight type to remove.

        Returns
        -------
        WeightCalculator
            Self for chaining.

        """
        if weight_type in self.weights:
            del self.weights[weight_type]
            del self.weight_params[weight_type]
            logger.debug(f"Removed weight: {weight_type}")
        else:
            logger.warning(f"Weight '{weight_type}' not found")
        return self

    def clear(self) -> WeightCalculator:
        """Clear all weights.

        Returns
        -------
        WeightCalculator
            Self for chaining.

        """
        self.weights = {}
        self.weight_params = {}
        return self

    def __repr__(self) -> str:
        """Return the developer-facing representation.

        Returns
        -------
        str
            Representation string.

        """
        return (
            f"WeightCalculator(grid={self.grid.grid_type}, "
            f"weights={list(self.weights.keys())})"
        )

    # ------------------------------------------------------------------
    # Weight computation (private)
    # ------------------------------------------------------------------

    def _compute_solid_angle_weight(self, **kwargs: Any) -> np.ndarray:
        """Weights based on cell solid angles (geometric fairness)."""
        if "solid_angle" in self._grid_df.columns:
            solid_angles = self._grid_df["solid_angle"].to_numpy()
        else:
            logger.debug("Computing solid angles from grid geometry")
            solid_angles = self._compute_solid_angles_from_geometry()

        if np.any(solid_angles <= 0):
            logger.warning("Found non-positive solid angles, setting to small value")
            solid_angles = np.maximum(solid_angles, 1e-10)

        return solid_angles

    def _compute_solid_angles_from_geometry(self) -> np.ndarray:
        """Compute solid angles for each cell from grid geometry.

        Returns
        -------
        np.ndarray
            Solid angles in steradians.

        Notes
        -----
        The sum of solid angles should equal the hemisphere area
        (2π steradians) for a complete hemisphere.

        """
        grid_type = self.grid.grid_type

        if grid_type in ("equal_area", "equal_angle", "equirectangular"):
            return self._compute_rectangular_solid_angles()
        if grid_type == "htm":
            return self._compute_htm_solid_angles()
        if grid_type == "geodesic":
            return self._compute_geodesic_solid_angles()
        if grid_type in ("healpix", "fibonacci"):
            # Both are (approximately) equal-area
            theta = self._grid_df["theta"].to_numpy()
            hemisphere_cells = int(np.sum(theta <= np.pi / 2))
            if hemisphere_cells > 0:
                cell_area = (2 * np.pi) / hemisphere_cells
                return np.full(self.grid.ncells, cell_area)
            return np.zeros(self.grid.ncells)
        logger.warning(f"Unknown grid type: {grid_type}, using uniform weights")
        return np.full(self.grid.ncells, (2 * np.pi) / self.grid.ncells)

    def _compute_rectangular_solid_angles(self) -> np.ndarray:
        """Solid angle = Δφ × [cos(θ_min) − cos(θ_max)]."""
        phi_min = self._grid_df["phi_min"].to_numpy()
        phi_max = self._grid_df["phi_max"].to_numpy()
        theta_min = self._grid_df["theta_min"].to_numpy()
        theta_max = self._grid_df["theta_max"].to_numpy()

        delta_phi = phi_max - phi_min
        return delta_phi * (np.cos(theta_min) - np.cos(theta_max))

    def _compute_htm_solid_angles(self) -> np.ndarray:
        """Solid angles for HTM triangular cells via L'Huilier's theorem.

        For each spherical triangle with vertices on the unit sphere the
        solid angle is computed as:

            Ω = 4 arctan √(tan(s/2) tan((s−a)/2) tan((s−b)/2) tan((s−c)/2))

        where *a*, *b*, *c* are arc-lengths between vertex pairs and
        *s* = (a+b+c)/2.
        """
        solid_angles = np.zeros(self.grid.ncells)

        for i, row in enumerate(self._grid_df.iter_rows(named=True)):
            try:
                v0 = np.array(row["htm_vertex_0"], dtype=float)
                v1 = np.array(row["htm_vertex_1"], dtype=float)
                v2 = np.array(row["htm_vertex_2"], dtype=float)

                # Skip cells significantly below the horizon
                if v0[2] < -0.01 or v1[2] < -0.01 or v2[2] < -0.01:
                    continue

                # Normalize to unit sphere
                v0 = v0 / np.linalg.norm(v0)
                v1 = v1 / np.linalg.norm(v1)
                v2 = v2 / np.linalg.norm(v2)

                # Arc lengths between vertex pairs
                a = np.arccos(np.clip(np.dot(v1, v2), -1, 1))
                b = np.arccos(np.clip(np.dot(v0, v2), -1, 1))
                c = np.arccos(np.clip(np.dot(v0, v1), -1, 1))

                s = (a + b + c) / 2  # semi-perimeter

                product = (
                    np.tan(s / 2)
                    * np.tan((s - a) / 2)
                    * np.tan((s - b) / 2)
                    * np.tan((s - c) / 2)
                )

                solid_angles[i] = (
                    4 * np.arctan(np.sqrt(product)) if product > 0 else 0.0
                )

            except Exception as e:
                logger.warning(f"Error computing HTM solid angle {i}: {e}")

        return solid_angles

    def _compute_geodesic_solid_angles(self) -> np.ndarray:
        """Solid angles for geodesic cells from vertex data.

        ``GridData.vertices`` for geodesic grids is a plain ``(n, 3)``
        ndarray of unit-sphere vertex coordinates (see
        ``GeodesicBuilder._build_grid``); each grid row's
        ``geodesic_vertices`` column holds the 3 indices into it for that
        cell's triangle.
        """
        solid_angles = np.zeros(self.grid.ncells)

        vertices = self.grid.vertices
        if vertices is None or "geodesic_vertices" not in self._grid_df.columns:
            # Approximate: equal area
            return np.full(self.grid.ncells, (2 * np.pi) / self.grid.ncells)

        for cell_id, v_indices in enumerate(
            self._grid_df["geodesic_vertices"].to_list()
        ):
            try:
                v0, v1, v2 = vertices[v_indices]

                v0 = v0 / np.linalg.norm(v0)
                v1 = v1 / np.linalg.norm(v1)
                v2 = v2 / np.linalg.norm(v2)

                numerator = np.abs(np.dot(v0, np.cross(v1, v2)))
                denominator = 1 + np.dot(v0, v1) + np.dot(v1, v2) + np.dot(v2, v0)

                solid_angles[cell_id] = 2 * np.arctan2(numerator, denominator)

            except Exception as e:
                logger.warning(f"Error computing geodesic solid angle {cell_id}: {e}")

        return solid_angles

    def _compute_observation_count_weight(
        self,
        var_name: str = "VOD",
        cell_id_var: str | None = None,
        min_count: int = 1,
        **kwargs: Any,
    ) -> np.ndarray:
        """Weights based on number of observations per cell.

        Parameters
        ----------
        var_name : str
            Variable to count observations for.
        cell_id_var : str, optional
            Cell-ID variable name (auto-detected if ``None``).
        min_count : int
            Cells with fewer observations get weight 0.

        """
        if self.ds is None:
            raise ValueError("Dataset required for observation_count weights.")

        cell_id_var = self._resolve_cell_id_var(cell_id_var)

        if var_name not in self.ds:
            raise ValueError(f"Variable '{var_name}' not found in dataset")

        logger.info("Computing observation counts (this may take 30-60 seconds)...")

        cell_ids_da = self.ds[cell_id_var].data.ravel()
        var_values_da = self.ds[var_name].data.ravel()

        valid_mask = da.isfinite(cell_ids_da) & da.isfinite(var_values_da)
        valid_cell_ids = da.where(valid_mask, cell_ids_da, -1).astype(np.int32)

        counts, _ = da.histogram(
            valid_cell_ids[valid_cell_ids >= 0],
            bins=np.arange(-0.5, self.grid.ncells + 0.5),
        )
        counts = counts.compute()

        weights = counts.astype(float)
        weights[counts < min_count] = 0.0

        logger.info(
            f"Observation counts: min={counts.min()}, max={counts.max()}, "
            f"mean={counts[counts > 0].mean():.1f}, "
            f"cells_with_data={np.sum(counts > 0)}"
        )
        return weights

    def _compute_snr_weight(
        self,
        snr_var: str = "SNR",
        cell_id_var: str | None = None,
        aggregation: Literal["mean", "median", "max"] = "mean",
        **kwargs: Any,
    ) -> np.ndarray:
        """Weights based on signal-to-noise ratio.

        Parameters
        ----------
        snr_var : str
            SNR variable name in the dataset.
        cell_id_var : str, optional
            Cell-ID variable name.
        aggregation : str
            Per-cell aggregation: ``'mean'``, ``'median'``, or ``'max'``.

        """
        if self.ds is None:
            raise ValueError("Dataset required for SNR weights")

        # Use pre-aggregated column if available
        if "mean_snr" in self._grid_df.columns:
            logger.info("Using pre-computed mean_snr from grid")
            return self._grid_df["mean_snr"].to_numpy()

        if snr_var not in self.ds:
            raise ValueError(f"SNR variable '{snr_var}' not found in dataset")

        cell_id_var = self._resolve_cell_id_var(cell_id_var)

        cell_ids = self.ds[cell_id_var].values.ravel()
        snr_values = self.ds[snr_var].values.ravel()

        valid = np.isfinite(cell_ids) & np.isfinite(snr_values)
        cell_ids_valid = cell_ids[valid].astype(int)
        snr_valid = snr_values[valid]

        _AGG = {"mean": np.mean, "median": np.median, "max": np.max}
        if aggregation not in _AGG:
            raise ValueError(f"Unknown aggregation: {aggregation}")
        agg_fn = _AGG[aggregation]

        snr_per_cell = np.zeros(self.grid.ncells)
        for cell_id in range(self.grid.ncells):
            cell_mask = cell_ids_valid == cell_id
            if np.any(cell_mask):
                snr_per_cell[cell_id] = agg_fn(snr_valid[cell_mask])

        return snr_per_cell

    def _compute_sin_elevation_weight(self, **kwargs: Any) -> np.ndarray:
        """Geometric correction: weight = sin(elevation) = cos(θ).

        Higher elevation → shorter atmospheric path → higher weight.
        """
        theta = self._grid_df["theta"].to_numpy()
        return np.maximum(np.cos(theta), 0.0)

    def _compute_inverse_variance_weight(
        self,
        var_name: str = "VOD",
        cell_id_var: str | None = None,
        min_observations: int = 2,
        regularization: float = 0.0,
        **kwargs: Any,
    ) -> np.ndarray:
        """Precision weighting: weight = 1 / (variance + regularization).

        Parameters
        ----------
        var_name : str
            Variable to compute per-cell variance for.
        cell_id_var : str, optional
            Cell-ID variable name.
        min_observations : int
            Minimum observations to compute variance.
        regularization : float
            Added to variance to avoid division by zero.

        """
        if self.ds is None:
            raise ValueError("Dataset required for inverse_variance weights")
        if var_name not in self.ds:
            raise ValueError(f"Variable '{var_name}' not found in dataset")

        cell_id_var = self._resolve_cell_id_var(cell_id_var)

        cell_ids = self.ds[cell_id_var].values.ravel()
        var_values = self.ds[var_name].values.ravel()

        valid = np.isfinite(cell_ids) & np.isfinite(var_values)
        cell_ids_valid = cell_ids[valid].astype(int)
        var_valid = var_values[valid]

        variances = np.full(self.grid.ncells, np.nan)
        for cell_id in range(self.grid.ncells):
            cell_mask = cell_ids_valid == cell_id
            if np.sum(cell_mask) >= min_observations:
                variances[cell_id] = np.var(var_valid[cell_mask], ddof=1)

        weights = np.zeros(self.grid.ncells)
        valid_var = np.isfinite(variances) & (variances > 0)
        if np.any(valid_var):
            weights[valid_var] = 1.0 / (variances[valid_var] + regularization)

        return weights

    def _compute_custom_weight(
        self,
        values: np.ndarray,
        **kwargs: Any,
    ) -> np.ndarray:
        """User-provided weight array.

        Parameters
        ----------
        values : np.ndarray
            Must have shape ``(ncells,)``.

        """
        if not isinstance(values, np.ndarray):
            raise TypeError("Custom weights must be numpy array")
        if values.shape != (self.grid.ncells,):
            raise ValueError(
                f"Custom weights shape {values.shape} doesn't match "
                f"grid size ({self.grid.ncells},)"
            )
        return values.copy()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve_cell_id_var(self, cell_id_var: str | None) -> str:
        """Auto-detect cell-ID variable if not specified.

        Parameters
        ----------
        cell_id_var : str or None
            Explicit name, or ``None`` for auto-detection.

        Returns
        -------
        str
            Resolved variable name.

        Raises
        ------
        ValueError
            If no ``cell_id_*`` variable is found.

        """
        if cell_id_var is not None:
            return cell_id_var

        if not isinstance(self.ds, xr.Dataset):
            raise ValueError("No dataset available for cell_id variable detection")

        candidate = f"cell_id_{self.grid.grid_type}"
        if candidate in self.ds.data_vars:
            return candidate

        cell_vars = [str(v) for v in self.ds.data_vars if str(v).startswith("cell_id_")]
        if cell_vars:
            logger.info(f"Auto-detected cell_id variable: {cell_vars[0]}")
            return cell_vars[0]

        raise ValueError("No cell_id variable found in dataset.")

    @staticmethod
    def _normalize_weights(weights: np.ndarray) -> np.ndarray:
        """Normalize weights to sum to 1.0, handling NaN and zeros."""
        weights = np.nan_to_num(weights, nan=0.0)
        weight_sum = weights.sum()
        if weight_sum > 0:
            return weights / weight_sum
        logger.warning("All weights are zero, returning uniform weights")
        return np.ones_like(weights) / len(weights)


# ----------------------------------------------------------------------
# Convenience functions
# ----------------------------------------------------------------------


def compute_uniform_weights(grid: GridData) -> np.ndarray:
    """Uniform weights (all cells equal).

    Parameters
    ----------
    grid : GridData
        Grid instance.

    Returns
    -------
    np.ndarray
        Array of ``1 / ncells`` for each cell.

    """
    return np.ones(grid.ncells) / grid.ncells


def compute_area_weights(grid: GridData, normalize: bool = True) -> np.ndarray:
    """Weights based on cell solid angles only.

    Parameters
    ----------
    grid : GridData
        Grid instance.
    normalize : bool
        If ``True``, normalize to sum to 1.0.

    Returns
    -------
    np.ndarray
        Area-based weights.

    """
    calc = WeightCalculator(grid)
    calc.add_weight("solid_angle", normalize=normalize)
    return calc.compute(normalize_final=normalize)
