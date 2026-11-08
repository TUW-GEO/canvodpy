"""Global (dataset-wide) outlier filters for gridded VOD data.

Classes
-------
Filter                  – abstract base; ``compute_mask`` / ``apply`` contract.
ZScoreFilter            – mean ± k·σ rejection.
IQRFilter               – Q1 – f·IQR / Q3 + f·IQR rejection.
RangeFilter             – hard min/max bounds.
PercentileFilter        – lower/upper percentile bounds.
CustomFilter            – user-supplied callable mask.
FilterPipeline          – sequential or combined multi-filter application.

Convenience functions
---------------------
``create_zscore_filter``   – one-liner z-score filter.
``create_range_filter``    – one-liner range filter.

Notes
-----
* Filters **never** modify original data.  ``apply`` returns a new
  ``xr.Dataset`` with ``<var>_filtered_<n>`` and ``mask_<n>``
  variables appended.
* Both numpy and dask-backed arrays are supported; dask paths compute
  only the scalar statistics eagerly while the mask itself stays lazy.

"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import datetime
from typing import Any

import dask.array as da
import numpy as np
import xarray as xr

# ==============================================================================
# Abstract base
# ==============================================================================


class Filter(ABC):
    """Base class for all filters.  Filters NEVER modify original data."""

    def __init__(self, name: str) -> None:
        """Initialize the filter.

        Parameters
        ----------
        name : str
            Filter name.

        """
        self.name = name
        self.metadata: dict = {
            "filter_type": self.__class__.__name__,
            "timestamp": datetime.now().isoformat(),
        }

    @abstractmethod
    def compute_mask(
        self,
        data: xr.DataArray,
        **kwargs: Any,
    ) -> xr.DataArray:
        """Compute boolean mask (True = keep, False = remove)."""

    def apply(
        self,
        ds: xr.Dataset,
        var_name: str,
        output_suffix: str | None = None,
        **kwargs: Any,
    ) -> xr.Dataset:
        """Apply filter to *ds*, returning a copy with filtered variable added.

        New variables
        -------------
        ``<var_name>_filtered_<suffix>`` : filtered data (NaN where masked).
        ``mask_<suffix>``               : boolean keep-mask.
        """
        suffix = output_suffix or self.name

        data = ds[var_name]
        mask = self.compute_mask(data, **kwargs)
        filtered_data = data.where(mask)

        n_total = int(mask.size)
        n_removed = int((~mask).sum().values)

        metadata = {
            **self.metadata,
            **kwargs,
            "applied_to": var_name,
            "n_total": n_total,
            "n_removed": n_removed,
            "fraction_removed": float(n_removed / n_total),
            "filter_chain": [self.name],
        }

        ds_out = ds.copy()

        filtered_var_name = f"{var_name}_filtered_{suffix}"
        mask_var_name = f"mask_{suffix}"

        ds_out[filtered_var_name] = filtered_data
        ds_out[filtered_var_name].attrs = metadata

        ds_out[mask_var_name] = mask
        ds_out[mask_var_name].attrs = {
            "description": f"Boolean mask for {self.name} filter",
            "True": "keep",
            "False": "filtered out",
            **metadata,
        }

        return ds_out


# ==============================================================================
# Concrete filters
# ==============================================================================


class ZScoreFilter(Filter):
    """Remove statistical outliers using z-score method."""

    def __init__(self) -> None:
        """Initialize the filter."""
        super().__init__("zscore")

    def compute_mask(
        self,
        data: xr.DataArray,
        threshold: float = 3.0,
        **kwargs: Any,
    ) -> xr.DataArray:
        """Compute z-score mask.

        Parameters
        ----------
        data : xr.DataArray
            Input data.
        threshold : float
            Z-score threshold (default: 3.0).

        Returns
        -------
        xr.DataArray
            Boolean mask (True = keep).

        """
        if isinstance(data.data, da.Array):
            mean = da.nanmean(data.data).compute()
            std = da.nanstd(data.data).compute()
            z_scores = da.fabs((data.data - mean) / std)
            mask_data = z_scores <= threshold
            mask = xr.DataArray(mask_data, dims=data.dims, coords=data.coords)
        else:
            mean = data.mean(skipna=True)
            std = data.std(skipna=True)
            z_scores = np.abs((data - mean) / std)
            mask = xr.DataArray(
                z_scores <= threshold,
                dims=data.dims,
                coords=data.coords,
            )

        return mask


class IQRFilter(Filter):
    """Remove outliers using Interquartile Range method."""

    def __init__(self) -> None:
        """Initialize the filter."""
        super().__init__("iqr")

    def compute_mask(
        self,
        data: xr.DataArray,
        factor: float = 1.5,
        **kwargs: Any,
    ) -> xr.DataArray:
        """Compute IQR mask.

        Parameters
        ----------
        data : xr.DataArray
            Input data.
        factor : float
            IQR factor (default: 1.5).

        Returns
        -------
        xr.DataArray
            Boolean mask (True = keep).

        """
        if isinstance(data.data, da.Array):
            flat_data = data.data.ravel()
            q1_val = da.percentile(flat_data, 25, method="linear").compute()
            q3_val = da.percentile(flat_data, 75, method="linear").compute()

            iqr = q3_val - q1_val
            lower_bound = q1_val - factor * iqr
            upper_bound = q3_val + factor * iqr

            mask_data = (data.data >= lower_bound) & (data.data <= upper_bound)
            mask = xr.DataArray(mask_data, dims=data.dims, coords=data.coords)
        else:
            q1 = data.quantile(0.25, skipna=True)
            q3 = data.quantile(0.75, skipna=True)
            iqr = q3 - q1

            lower_bound = q1 - factor * iqr
            upper_bound = q3 + factor * iqr

            mask = (data >= lower_bound) & (data <= upper_bound)

        return mask


class RangeFilter(Filter):
    """Filter values outside specified range."""

    def __init__(self) -> None:
        """Initialize the filter."""
        super().__init__("range")

    def compute_mask(
        self,
        data: xr.DataArray,
        min_value: float | None = None,
        max_value: float | None = None,
        **kwargs: Any,
    ) -> xr.DataArray:
        """Compute range mask.

        Parameters
        ----------
        data : xr.DataArray
            Input data.
        min_value : float, optional
            Minimum allowed value.
        max_value : float, optional
            Maximum allowed value.

        Returns
        -------
        xr.DataArray
            Boolean mask (True = keep).

        """
        mask = xr.ones_like(data, dtype=bool)

        if min_value is not None:
            mask = mask & (data >= min_value)
        if max_value is not None:
            mask = mask & (data <= max_value)

        return mask


class PercentileFilter(Filter):
    """Filter values outside percentile range."""

    def __init__(self) -> None:
        """Initialize the filter."""
        super().__init__("percentile")

    def compute_mask(
        self,
        data: xr.DataArray,
        lower: float = 5.0,
        upper: float = 95.0,
        **kwargs: Any,
    ) -> xr.DataArray:
        """Compute percentile mask.

        Parameters
        ----------
        data : xr.DataArray
            Input data.
        lower : float
            Lower percentile (0–100).
        upper : float
            Upper percentile (0–100).

        Returns
        -------
        xr.DataArray
            Boolean mask (True = keep).

        """
        lower_val = data.quantile(lower / 100.0, skipna=True)
        upper_val = data.quantile(upper / 100.0, skipna=True)

        mask = (data >= lower_val) & (data <= upper_val)

        return mask


class CustomFilter(Filter):
    """Apply a user-supplied callable as filter.

    Parameters
    ----------
    name : str
        Filter identifier.
    func : callable
        ``(xr.DataArray, **kwargs) -> xr.DataArray`` returning a boolean mask.

    """

    def __init__(self, name: str, func: Callable[..., xr.DataArray]) -> None:
        """Initialize the custom filter.

        Parameters
        ----------
        name : str
            Filter identifier.
        func : Callable[..., xr.DataArray]
            Callable returning a boolean mask.

        """
        super().__init__(name)
        self.func = func

    def compute_mask(
        self,
        data: xr.DataArray,
        **kwargs: Any,
    ) -> xr.DataArray:
        """Apply custom function."""
        return self.func(data, **kwargs)


class SIDPatternFilter(Filter):
    """Filter dataset by GNSS system, frequency band, and tracking code.

    Operates on the ``sid`` dimension of a dataset, where SIDs have the
    format ``SV|Band|Code`` (e.g. ``G01|L1|C``).

    Parameters
    ----------
    system : str or None
        GNSS system prefix to keep (e.g. ``'G'``, ``'E'``, ``'R'``, ``'C'``).
        ``None`` keeps all systems.
    band : str or None
        Frequency band to keep (e.g. ``'L1'``, ``'E1'``, ``'L5'``).
        ``None`` keeps all bands.
    code : str or None
        Tracking code to keep (e.g. ``'C'``, ``'L'``, ``'W'``).
        ``None`` keeps all codes.

    Examples
    --------
    >>> filt = SIDPatternFilter(system="G", band="L1", code="C")
    >>> ds_gps_l1c = filt.filter_dataset(ds)

    """

    def __init__(
        self,
        system: str | None = None,
        band: str | None = None,
        code: str | None = None,
    ) -> None:
        parts = [p for p in [system, band, code] if p is not None]
        name = f"sid_{'_'.join(parts)}" if parts else "sid_all"
        super().__init__(name)
        self.system = system
        self.band = band
        self.code = code

    def _sid_matches(self, sid: str) -> bool:
        """Check whether a single SID string matches the pattern."""
        parts = str(sid).split("|")
        if len(parts) != 3:
            return False
        sv, sid_band, sid_code = parts
        if self.system is not None and not sv.startswith(self.system):
            return False
        if self.band is not None and sid_band != self.band:
            return False
        if self.code is not None and sid_code != self.code:
            return False
        return True

    def compute_mask(
        self,
        data: xr.DataArray,
        **kwargs: Any,
    ) -> xr.DataArray:
        """Compute boolean mask along the ``sid`` dimension.

        Parameters
        ----------
        data : xr.DataArray
            Input data with a ``sid`` dimension.

        Returns
        -------
        xr.DataArray
            Boolean mask (True = keep) broadcast to data shape.

        """
        if "sid" not in data.dims:
            raise ValueError("Data must have a 'sid' dimension for SID filtering")

        sid_values = data.coords["sid"].values
        sid_mask = np.array([self._sid_matches(s) for s in sid_values])
        mask_da = xr.DataArray(sid_mask, dims=["sid"], coords={"sid": sid_values})
        return mask_da.broadcast_like(data)

    def filter_dataset(self, ds: xr.Dataset) -> xr.Dataset | None:
        """Filter dataset to matching SIDs by slicing the ``sid`` dimension.

        Unlike ``apply`` (which masks values with NaN), this method drops
        non-matching SIDs entirely — reducing the dataset size.

        Parameters
        ----------
        ds : xr.Dataset
            Dataset with a ``sid`` dimension.

        Returns
        -------
        xr.Dataset or None
            Filtered dataset, or ``None`` if no SIDs match.

        """
        if "sid" not in ds.dims:
            raise ValueError("Dataset must have a 'sid' dimension")

        sid_values = ds.coords["sid"].values
        matching = [s for s in sid_values if self._sid_matches(s)]

        if not matching:
            return None

        return ds.sel(sid=matching)


# ==============================================================================
# Pipeline
# ==============================================================================


class FilterPipeline:
    """Manage multiple filters applied sequentially or combined.

    Non-destructive: creates new DataArrays, never modifies originals.

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
        self.filters: list[tuple[Filter, dict]] = []

    def add_filter(self, filter_obj: Filter | str, **kwargs: Any) -> FilterPipeline:
        """Add filter to pipeline.

        Parameters
        ----------
        filter_obj : Filter or str
            Filter instance or short name
            (``'zscore'``, ``'iqr'``, ``'range'``, ``'percentile'``).
        **kwargs
            Parameters forwarded to ``compute_mask``.

        Returns
        -------
        FilterPipeline
            Self (for chaining).

        """
        if isinstance(filter_obj, str):
            _filter_map = {
                "zscore": ZScoreFilter,
                "iqr": IQRFilter,
                "range": RangeFilter,
                "percentile": PercentileFilter,
            }
            if filter_obj not in _filter_map:
                raise ValueError(f"Unknown filter: {filter_obj}")
            filter_obj = _filter_map[filter_obj]()

        self.filters.append((filter_obj, kwargs))
        return self

    def apply(
        self, mode: str = "sequential", output_name: str | None = None
    ) -> xr.Dataset:
        """Apply all filters in the pipeline.

        Parameters
        ----------
        mode : {'sequential', 'combined'}
            ``'sequential'`` – masks accumulate (AND) after each filter;
            intermediate filtered variables are written.
            ``'combined'``   – all masks computed independently on the
            original data, then AND-ed once.
        output_name : str, optional
            Alias for the final filtered variable.

        Returns
        -------
        xr.Dataset
            Dataset with filtered variables appended.

        """
        if not self.filters:
            raise ValueError("No filters in pipeline")

        ds_out = self.ds.copy()

        if mode == "sequential":
            masks: list[xr.DataArray] = []
            filter_names: list[str] = []
            all_params: list[dict] = []

            for filter_obj, kwargs in self.filters:
                mask = filter_obj.compute_mask(ds_out[self.var_name], **kwargs)
                masks.append(mask)
                filter_names.append(filter_obj.name)
                all_params.append(kwargs)

                # Store individual mask
                mask_name = f"mask_{filter_obj.name}"
                if mask_name not in ds_out:
                    ds_out[mask_name] = mask
                    ds_out[mask_name].attrs = {
                        "filter_type": filter_obj.name,
                        **kwargs,
                    }

                # Accumulate masks (AND)
                cumulative_mask = masks[0]
                for m in masks[1:]:
                    cumulative_mask = cumulative_mask & m

                cumulative_suffix = "_".join(filter_names)
                filtered_data = ds_out[self.var_name].where(cumulative_mask)

                filtered_var_name = f"{self.var_name}_filtered_{cumulative_suffix}"
                cumulative_mask_name = f"mask_{cumulative_suffix}"

                ds_out[filtered_var_name] = filtered_data
                ds_out[cumulative_mask_name] = cumulative_mask

                n_total = int(cumulative_mask.size)
                n_removed = int((~cumulative_mask).sum().values)

                metadata: dict = {
                    "filter_chain": filter_names.copy(),
                    "mode": "sequential",
                    "applied_to": self.var_name,
                    "n_total": n_total,
                    "n_removed": n_removed,
                    "fraction_removed": float(n_removed / n_total),
                    "timestamp": datetime.now().isoformat(),
                    "filters": {
                        fname: params for fname, params in zip(filter_names, all_params)
                    },
                }

                ds_out[filtered_var_name].attrs = metadata
                ds_out[cumulative_mask_name].attrs = metadata

            if output_name:
                final_var = f"{self.var_name}_filtered_{'_'.join(filter_names)}"
                final_mask = f"mask_{'_'.join(filter_names)}"

                ds_out[f"{self.var_name}_filtered_{output_name}"] = ds_out[final_var]
                ds_out[f"mask_{output_name}"] = ds_out[final_mask]
                ds_out[f"{self.var_name}_filtered_{output_name}"].attrs = ds_out[
                    final_var
                ].attrs
                ds_out[f"mask_{output_name}"].attrs = ds_out[final_mask].attrs

        elif mode == "combined":
            masks = []
            filter_names = []
            all_params = []

            for filter_obj, kwargs in self.filters:
                mask = filter_obj.compute_mask(ds_out[self.var_name], **kwargs)
                masks.append(mask)
                filter_names.append(filter_obj.name)
                all_params.append(kwargs)

                mask_name = f"mask_{filter_obj.name}"
                if mask_name not in ds_out:
                    ds_out[mask_name] = mask
                    ds_out[mask_name].attrs = {
                        "filter_type": filter_obj.name,
                        **kwargs,
                    }

            combined_mask = masks[0]
            for mask in masks[1:]:
                combined_mask = combined_mask & mask

            suffix = output_name or "combined"
            filtered_data = ds_out[self.var_name].where(combined_mask)

            filtered_var_name = f"{self.var_name}_filtered_{suffix}"
            mask_var_name = f"mask_{suffix}"

            ds_out[filtered_var_name] = filtered_data
            ds_out[mask_var_name] = combined_mask

            n_total = int(combined_mask.size)
            n_removed = int((~combined_mask).sum().values)

            metadata = {
                "filter_chain": filter_names,
                "mode": "combined",
                "applied_to": self.var_name,
                "n_total": n_total,
                "n_removed": n_removed,
                "fraction_removed": float(n_removed / n_total),
                "timestamp": datetime.now().isoformat(),
                "filters": {
                    fname: params for fname, params in zip(filter_names, all_params)
                },
            }

            ds_out[filtered_var_name].attrs = metadata
            ds_out[mask_var_name].attrs = metadata

        else:
            raise ValueError(f"Unknown mode: {mode}")

        return ds_out

    def summary(self) -> str:
        """Return a human-readable summary of the pipeline."""
        lines = [f"Filter Pipeline for '{self.var_name}':", ""]
        for i, (filter_obj, kwargs) in enumerate(self.filters):
            lines.append(f"{i + 1}. {filter_obj.name}")
            for key, val in kwargs.items():
                lines.append(f"   - {key}: {val}")
        return "\n".join(lines)


# ==============================================================================
# Convenience functions
# ==============================================================================


def create_zscore_filter(
    ds: xr.Dataset,
    var_name: str = "VOD",
    threshold: float = 3.0,
    suffix: str = "zscore",
) -> xr.Dataset:
    """One-liner z-score filter."""
    return ZScoreFilter().apply(ds, var_name, suffix, threshold=threshold)


def create_range_filter(
    ds: xr.Dataset,
    var_name: str = "VOD",
    min_value: float | None = None,
    max_value: float | None = None,
    suffix: str = "range",
) -> xr.Dataset:
    """One-liner range filter."""
    return RangeFilter().apply(
        ds, var_name, suffix, min_value=min_value, max_value=max_value
    )
