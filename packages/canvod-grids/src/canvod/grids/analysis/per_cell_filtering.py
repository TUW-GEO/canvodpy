"""Per-cell outlier filters for gridded VOD data.

Unlike the global filters in :mod:`~canvod.grids.analysis.filtering`, these
operate **independently on each grid cell**, preserving spatial structure
while removing temporal outliers *within* cells.

Classes
-------
PerCellFilter               – abstract base with auto cell-id detection.
PerCellIQRFilter            – per-cell IQR rejection.
PerCellZScoreFilter         – per-cell z-score rejection.
PerCellRangeFilter          – per-cell hard bounds.
PerCellPercentileFilter     – per-cell percentile bounds.
PerCellFilterPipeline       – sequential or combined multi-filter application.

Convenience functions
---------------------
``create_per_cell_iqr_filter``     – one-liner per-cell IQR.
``create_per_cell_zscore_filter``  – one-liner per-cell z-score.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import numpy as np
import structlog
import xarray as xr

logger = structlog.get_logger(__name__)


# ==============================================================================
# Abstract base
# ==============================================================================


class PerCellFilter(ABC):
    """Base class for per-cell filtering operations.

    Sub-classes implement :meth:`compute_cell_mask` for a single cell's
    1-D data array; the base class handles iteration over cells,
    auto-detection of the ``cell_id_*`` variable, and output assembly.
    """

    def __init__(self, filter_name: str) -> None:
        """Initialize the per-cell filter.

        Parameters
        ----------
        filter_name : str
            Filter name.

        """
        self.filter_name = filter_name

    @abstractmethod
    def compute_cell_mask(
        self,
        cell_data: np.ndarray,
        **kwargs: Any,
    ) -> np.ndarray:
        """Return a boolean keep-mask for one cell's data.

        Parameters
        ----------
        cell_data : np.ndarray
            1-D array of values for one cell across time.

        Returns
        -------
        np.ndarray
            Boolean mask (True = keep).

        """

    def apply(
        self,
        ds: xr.Dataset,
        var_name: str = "VOD",
        cell_id_var: str | None = None,
        output_suffix: str | None = None,
        min_observations: int = 5,
        **kwargs: Any,
    ) -> xr.Dataset:
        """Apply per-cell filtering to *ds*.

        Parameters
        ----------
        ds : xr.Dataset
            Input dataset (must contain a ``cell_id_*`` variable).
        var_name : str
            Variable to filter.
        cell_id_var : str, optional
            Cell-ID variable name.  Auto-detected from ``cell_id_*`` if *None*.
        output_suffix : str, optional
            Suffix for output variables (default: ``filter_name``).
        min_observations : int
            Minimum observations per cell required for filtering.
        **kwargs
            Forwarded to :meth:`compute_cell_mask`.

        Returns
        -------
        xr.Dataset
            Copy of *ds* with ``<var>_filtered_<suffix>`` and
            ``mask_<suffix>`` appended.

        """
        if output_suffix is None:
            output_suffix = self.filter_name

        # Auto-detect cell_id variable
        if cell_id_var is None:
            cell_id_vars = [
                str(v) for v in ds.data_vars if str(v).startswith("cell_id_")
            ]
            if not cell_id_vars:
                raise ValueError("No cell_id variable found in dataset")
            cell_id_var = cell_id_vars[0]
            logger.info("Auto-detected cell_id variable: %s", cell_id_var)

        if var_name not in ds:
            raise ValueError(f"Variable '{var_name}' not found in dataset")
        if cell_id_var not in ds:
            raise ValueError(f"Cell ID variable '{cell_id_var}' not found in dataset")

        logger.info("Applying %s filter per-cell to '%s'", self.filter_name, var_name)

        var_data = ds[var_name]
        cell_ids = ds[cell_id_var]

        filtered_data, mask = self._apply_per_cell_filtering(
            var_data, cell_ids, min_observations, **kwargs
        )

        result = ds.copy()
        result[f"{var_name}_filtered_{output_suffix}"] = filtered_data
        result[f"mask_{output_suffix}"] = mask

        result[f"{var_name}_filtered_{output_suffix}"].attrs.update(
            {
                "filter_type": self.filter_name,
                "filter_params": str(kwargs),
                "min_observations": min_observations,
                "source_variable": var_name,
            }
        )

        return result

    def _apply_per_cell_filtering(
        self,
        var_data: xr.DataArray,
        cell_ids: xr.DataArray,
        min_observations: int,
        **kwargs: Any,
    ) -> tuple[xr.DataArray, xr.DataArray]:
        """Iterate over unique cells and apply the mask function.

        Parameters
        ----------
        var_data : xr.DataArray
            Data to filter.
        cell_ids : xr.DataArray
            Cell ID assignments.
        min_observations : int
            Minimum observations per cell.
        **kwargs : Any
            Forwarded to ``compute_cell_mask``.

        Returns
        -------
        Tuple[xr.DataArray, xr.DataArray]
            Filtered values and mask arrays.

        """
        values = var_data.values
        cells = cell_ids.values

        filtered_values = values.copy()
        mask_values = np.ones_like(values, dtype=bool)

        unique_cells = np.unique(cells[np.isfinite(cells)])
        logger.info("Processing %d unique cells", len(unique_cells))

        cells_processed = 0
        cells_filtered = 0
        total_filtered = 0

        for cell_id in unique_cells:
            cell_mask = (cells == cell_id) & np.isfinite(values) & np.isfinite(cells)
            cell_indices = np.where(cell_mask)

            if len(cell_indices[0]) < min_observations:
                continue

            cell_data = values[cell_mask]
            cell_filter_mask = self.compute_cell_mask(cell_data, **kwargs)

            mask_values[cell_mask] = cell_filter_mask
            filtered_values[cell_mask] = np.where(cell_filter_mask, cell_data, np.nan)

            cells_processed += 1
            if not np.all(cell_filter_mask):
                cells_filtered += 1
                total_filtered += int(np.sum(~cell_filter_mask))

        logger.info(
            "Processed %d cells, filtered %d cells, removed %d observations",
            cells_processed,
            cells_filtered,
            total_filtered,
        )

        filtered_da = xr.DataArray(
            filtered_values,
            dims=var_data.dims,
            coords=var_data.coords,
            attrs=var_data.attrs,
        )
        mask_da = xr.DataArray(mask_values, dims=var_data.dims, coords=var_data.coords)

        return filtered_da, mask_da


# ==============================================================================
# Concrete per-cell filters
# ==============================================================================


class PerCellIQRFilter(PerCellFilter):
    """Per-cell IQR outlier rejection.

    Values outside ``[Q1 − factor·IQR, Q3 + factor·IQR]`` are removed
    independently within each cell.
    """

    def __init__(self) -> None:
        """Initialize the filter."""
        super().__init__("iqr")

    def compute_cell_mask(
        self,
        cell_data: np.ndarray,
        factor: float = 1.5,
        **kwargs: Any,
    ) -> np.ndarray:
        """IQR mask for a single cell.

        Parameters
        ----------
        cell_data : np.ndarray
            1-D cell data.
        factor : float
            IQR multiplier (default 1.5).

        Returns
        -------
        np.ndarray
            Boolean mask.

        """
        valid_data = cell_data[np.isfinite(cell_data)]
        if len(valid_data) < 4:
            return np.ones_like(cell_data, dtype=bool)

        q1 = np.percentile(valid_data, 25)
        q3 = np.percentile(valid_data, 75)
        iqr = q3 - q1

        if iqr == 0:
            return np.ones_like(cell_data, dtype=bool)

        lower_bound = q1 - factor * iqr
        upper_bound = q3 + factor * iqr

        return (cell_data >= lower_bound) & (cell_data <= upper_bound)


class PerCellZScoreFilter(PerCellFilter):
    """Per-cell z-score outlier rejection.

    Values with ``|z| > threshold`` are removed independently within each cell.
    """

    def __init__(self) -> None:
        """Initialize the filter."""
        super().__init__("zscore")

    def compute_cell_mask(
        self,
        cell_data: np.ndarray,
        threshold: float = 3.0,
        **kwargs: Any,
    ) -> np.ndarray:
        """Z-score mask for a single cell.

        Parameters
        ----------
        cell_data : np.ndarray
            1-D cell data.
        threshold : float
            Z-score threshold (default 3.0).

        Returns
        -------
        np.ndarray
            Boolean mask.

        """
        if len(cell_data) < 3:
            return np.ones_like(cell_data, dtype=bool)

        mean = np.nanmean(cell_data)
        std = np.nanstd(cell_data)

        if std == 0:
            return np.ones_like(cell_data, dtype=bool)

        z_scores = np.abs((cell_data - mean) / std)
        return z_scores <= threshold


class PerCellRangeFilter(PerCellFilter):
    """Per-cell hard-bound range filter.

    Identical bounds applied to every cell.
    """

    def __init__(self) -> None:
        """Initialize the filter."""
        super().__init__("range")

    def compute_cell_mask(
        self,
        cell_data: np.ndarray,
        min_value: float | None = None,
        max_value: float | None = None,
        **kwargs: Any,
    ) -> np.ndarray:
        """Range mask for a single cell.

        Parameters
        ----------
        cell_data : np.ndarray
            1-D cell data.
        min_value : float, optional
            Minimum allowed value.
        max_value : float, optional
            Maximum allowed value.

        Returns
        -------
        np.ndarray
            Boolean mask.

        """
        mask = np.ones_like(cell_data, dtype=bool)
        if min_value is not None:
            mask = mask & (cell_data >= min_value)
        if max_value is not None:
            mask = mask & (cell_data <= max_value)
        return mask


class PerCellPercentileFilter(PerCellFilter):
    """Per-cell percentile-bound filter.

    Bounds are computed independently within each cell.
    """

    def __init__(self) -> None:
        """Initialize the filter."""
        super().__init__("percentile")

    def compute_cell_mask(
        self,
        cell_data: np.ndarray,
        lower: float = 5.0,
        upper: float = 95.0,
        **kwargs: Any,
    ) -> np.ndarray:
        """Percentile mask for a single cell.

        Parameters
        ----------
        cell_data : np.ndarray
            1-D cell data.
        lower : float
            Lower percentile (0–100).
        upper : float
            Upper percentile (0–100).

        Returns
        -------
        np.ndarray
            Boolean mask.

        """
        valid_data = cell_data[np.isfinite(cell_data)]
        if len(valid_data) < 5:
            return np.ones_like(cell_data, dtype=bool)

        lower_val = np.percentile(valid_data, lower)
        upper_val = np.percentile(valid_data, upper)

        return (cell_data >= lower_val) & (cell_data <= upper_val)


# ==============================================================================
# Pipeline
# ==============================================================================


class PerCellFilterPipeline:
    """Sequential or combined multi-filter pipeline for per-cell filtering.

    Parameters
    ----------
    ds : xr.Dataset
        Input dataset.
    var_name : str
        Variable to filter (default: ``'VOD'``).

    """

    def __init__(self, ds: xr.Dataset, var_name: str = "VOD") -> None:
        """Initialize the filter pipeline.

        Parameters
        ----------
        ds : xr.Dataset
            Input dataset.
        var_name : str, default "VOD"
            Variable to filter.

        """
        self.ds = ds
        self.var_name = var_name
        self.filters: list[tuple[PerCellFilter, dict]] = []

    def add_filter(
        self,
        filter_obj: PerCellFilter | str,
        **kwargs: Any,
    ) -> PerCellFilterPipeline:
        """Add a filter.

        Parameters
        ----------
        filter_obj : PerCellFilter or str
            Filter instance or short name
            (``'iqr'``, ``'zscore'``, ``'range'``, ``'percentile'``).
        **kwargs
            Parameters forwarded to the filter.

        Returns
        -------
        PerCellFilterPipeline
            Self (for chaining).

        """
        if isinstance(filter_obj, str):
            _filter_map = {
                "iqr": PerCellIQRFilter,
                "zscore": PerCellZScoreFilter,
                "range": PerCellRangeFilter,
                "percentile": PerCellPercentileFilter,
            }
            if filter_obj not in _filter_map:
                raise ValueError(f"Unknown filter: {filter_obj}")
            filter_obj = _filter_map[filter_obj]()

        self.filters.append((filter_obj, kwargs))
        return self

    def apply(
        self, mode: str = "sequential", output_name: str | None = None
    ) -> xr.Dataset:
        """Apply all filters.

        Parameters
        ----------
        mode : {'sequential', 'combined'}
            ``'sequential'`` – each filter operates on the previous output.
            ``'combined'``   – all masks computed on the original, then AND-ed.
        output_name : str, optional
            Alias for the final filtered variable.

        Returns
        -------
        xr.Dataset
            Dataset with filtered results.

        """
        if not self.filters:
            raise ValueError("No filters added to pipeline")

        result = self.ds.copy()
        current_var = self.var_name

        if mode == "sequential":
            for i, (filter_obj, kwargs) in enumerate(self.filters):
                suffix = (
                    f"{filter_obj.filter_name}_{i}" if i > 0 else filter_obj.filter_name
                )
                result = filter_obj.apply(
                    result, current_var, output_suffix=suffix, **kwargs
                )
                current_var = f"{self.var_name}_filtered_{suffix}"

        elif mode == "combined":
            combined_mask = None
            filter_names: list[str] = []

            for filter_obj, kwargs in self.filters:
                filtered = filter_obj.apply(result, self.var_name, **kwargs)
                mask = filtered[f"mask_{filter_obj.filter_name}"]

                if combined_mask is None:
                    combined_mask = mask
                else:
                    combined_mask = combined_mask & mask

                filter_names.append(filter_obj.filter_name)

            final_name = output_name or "_".join(filter_names)
            result[f"{self.var_name}_filtered_{final_name}"] = result[
                self.var_name
            ].where(combined_mask)
            result[f"mask_{final_name}"] = combined_mask

        else:
            raise ValueError(f"Unknown mode: {mode}")

        return result


# ==============================================================================
# Convenience functions
# ==============================================================================


def create_per_cell_iqr_filter(
    ds: xr.Dataset,
    var_name: str = "VOD",
    factor: float = 1.5,
    cell_id_var: str | None = None,
    min_observations: int = 5,
) -> xr.Dataset:
    """One-liner per-cell IQR filter."""
    return PerCellIQRFilter().apply(
        ds,
        var_name,
        cell_id_var=cell_id_var,
        factor=factor,
        min_observations=min_observations,
    )


def create_per_cell_zscore_filter(
    ds: xr.Dataset,
    var_name: str = "VOD",
    threshold: float = 3.0,
    cell_id_var: str | None = None,
    min_observations: int = 5,
) -> xr.Dataset:
    """One-liner per-cell z-score filter."""
    return PerCellZScoreFilter().apply(
        ds,
        var_name,
        cell_id_var=cell_id_var,
        threshold=threshold,
        min_observations=min_observations,
    )
