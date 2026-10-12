"""Per-cell aggregation of VOD observations onto hemisphere grids.

Top-level entry points
----------------------
``aggregate_data_to_grid``       – single-statistic spatial aggregation
``compute_percell_timeseries``   – chunked (cell × time) time-series

Analysis helpers
----------------
``compute_global_average``       – observation-count–weighted global mean
``compute_regional_average``     – same, restricted to a cell subset
``analyze_diurnal_patterns``     – hourly groupby
``analyze_spatial_patterns``     – time-averaged spatial field

Convenience wrappers
--------------------
``compute_hemisphere_percell``   – daily, full hemisphere
``compute_zenith_percell``       – daily, θ ≤ 30°
"""

from __future__ import annotations

import gc
import re
import time
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd
import polars as pl
import xarray as xr
from tqdm.auto import tqdm

if TYPE_CHECKING:
    from canvod.grids.core import GridData


# ==============================================================================
# Single-statistic spatial aggregation
# ==============================================================================


def aggregate_data_to_grid(
    data_ds: xr.Dataset,
    grid: GridData,
    value_var: str = "VOD",
    cell_var: str = "cell_id_equal_area_2deg",
    sid: list[str] | None = None,
    time_range: tuple | None = None,
    stat: str = "median",
) -> np.ndarray:
    """Aggregate VOD data across all timestamps and SIDs to per-cell statistics.

    Parameters
    ----------
    data_ds : xr.Dataset
        Full VOD dataset from the Icechunk store.
    grid : GridData
        Grid definition.
    value_var : str
        Name of the VOD variable.
    cell_var : str
        Name of the cell-ID variable in *data_ds*.
    sid : list[str], optional
        Satellite IDs to include.  ``None`` → all.
    time_range : tuple, optional
        ``(start, end)`` datetimes for epoch filtering.
    stat : {'mean', 'median', 'std'}
        Statistic to compute per cell.

    Returns
    -------
    np.ndarray
        Array of length ``grid.ncells`` with per-cell aggregated values
        (NaN where no observations exist).

    """
    vod = data_ds[value_var]
    cell_ids = data_ds[cell_var]

    if sid is not None and "sid" in vod.dims:
        vod = vod.sel(sid=sid)
        cell_ids = cell_ids.sel(sid=sid)
        print(f"Using SIDs: {sid}")
    elif not sid and "sid" in vod.dims:
        available_sids = vod.sid.values.tolist()
        print(f"Using all available SIDs: {available_sids}")
    else:
        raise ValueError("No SID dimension in data.")

    if time_range is not None:
        vod = vod.sel(epoch=slice(time_range[0], time_range[1]))
        cell_ids = cell_ids.sel(epoch=slice(time_range[0], time_range[1]))

    vod_flat = np.asarray(vod.values).ravel()
    cell_flat = np.asarray(cell_ids.values).ravel()
    valid = np.isfinite(vod_flat) & np.isfinite(cell_flat)

    df = pl.DataFrame(
        {
            "cell_id": cell_flat[valid].astype(np.int64),
            "vod": vod_flat[valid],
        }
    )

    agg_expr = {
        "mean": pl.col("vod").mean(),
        "median": pl.col("vod").median(),
        "std": pl.col("vod").std(),
    }
    if stat not in agg_expr:
        raise ValueError(f"Unsupported stat: {stat}")

    agg = df.group_by("cell_id").agg(agg_expr[stat].alias("vod_stat"))

    result = np.full(grid.ncells, np.nan, dtype=float)
    result[agg["cell_id"].to_numpy()] = agg["vod_stat"].to_numpy()
    return result


# ==============================================================================
# CellAggregator
# ==============================================================================


class CellAggregator:
    """Polars-based per-cell aggregation helpers."""

    @staticmethod
    def aggregate_by_cell(
        df: pl.DataFrame,
        value_var: str = "VOD",
        method: str = "mean",
    ) -> pl.DataFrame:
        """Aggregate values by ``cell_id``.

        Parameters
        ----------
        df : pl.DataFrame
            Must contain ``cell_id`` and *value_var* columns.
        value_var : str
            Column to aggregate.
        method : {'mean', 'median', 'std', 'count'}
            Aggregation method.

        Returns
        -------
        pl.DataFrame
            Two-column DataFrame: ``cell_id``, *value_var*.

        """
        if "cell_id" not in df.columns:
            raise ValueError("pl.DataFrame must have 'cell_id' column")
        if value_var not in df.columns:
            raise ValueError(f"pl.DataFrame must have '{value_var}' column")

        agg_map = {
            "mean": pl.col(value_var).mean(),
            "median": pl.col(value_var).median(),
            "std": pl.col(value_var).std(),
            "count": pl.col(value_var).count(),
        }
        if method not in agg_map:
            raise ValueError(f"Unknown method: {method}")

        return (
            df.group_by("cell_id").agg(agg_map[method].alias(value_var)).sort("cell_id")
        )


# ==============================================================================
# Per-cell time-series aggregation
# ==============================================================================


def compute_percell_timeseries(
    data_ds: xr.Dataset,
    grid: GridData,
    value_var: str = "VOD",
    cell_var: str = "cell_id_equal_area_2deg",
    theta_range: tuple[float, float] | None = None,
    phi_range: tuple[float, float] | None = None,
    selected_sids: list[str] | None = None,
    time_range: tuple | None = None,
    temporal_resolution: str = "1D",
    chunk_days: int = 21,
    min_obs_per_cell_time: int = 1,
    stat: str = "mean",
) -> xr.Dataset:
    """Compute time series per cell with SID aggregation.

    Processing is chunked over time to bound memory usage.

    Parameters
    ----------
    data_ds : xr.Dataset
        Full VOD dataset.
    grid : GridData
        Grid definition.
    value_var : str
        VOD variable name.
    cell_var : str
        Cell-ID variable name.
    theta_range : tuple, optional
        ``(min_deg, max_deg)`` elevation filter.
    phi_range : tuple, optional
        ``(min_deg, max_deg)`` azimuth filter (wraps at 360°).
    selected_sids : list[str], optional
        Satellite IDs to include.
    time_range : tuple, optional
        ``(start, end)`` epoch slice.
    temporal_resolution : str
        Pandas/polars frequency string (e.g. ``"1D"``, ``"30min"``).
    chunk_days : int
        Days per processing chunk.
    min_obs_per_cell_time : int
        Minimum SID observations per (cell, time-bin) to retain.
    stat : {'mean', 'median'}
        Statistic to compute per (cell, time-bin), mirroring
        :func:`aggregate_data_to_grid`'s ``stat`` parameter.

    Returns
    -------
    xr.Dataset
        Dataset with dimensions ``(cell, time)`` and variables
        ``cell_timeseries``, ``cell_weights``, ``cell_counts``,
        ``cell_theta``, ``cell_phi``.

    """
    if stat not in ("mean", "median"):
        raise ValueError(f"Unsupported stat: {stat!r} (expected 'mean' or 'median')")

    print("📍 PER-CELL TIME SERIES AGGREGATION")
    print("=" * 60)
    print(f"📦 Chunk size: {chunk_days} days")
    print(f"🕒 Resolution: {temporal_resolution}")

    start_time = time.time()

    selected_cells = _create_spatial_selection(grid, theta_range, phi_range)
    print(f"📍 Selected cells: {len(selected_cells)}")

    if selected_sids is not None and "sid" in data_ds.dims:
        data_ds = data_ds.sel(sid=selected_sids)
        print(f"🛰️  Selected SIDs: {len(selected_sids)}")

    if time_range is not None:
        data_ds = data_ds.sel(epoch=slice(time_range[0], time_range[1]))

    print(f"📊 Data shape: {data_ds[value_var].shape}")

    # Normalize frequency string for pandas
    pandas_freq = _normalise_pandas_freq(temporal_resolution)

    # Floor to the period boundary (e.g. midnight for "1D"), NOT the raw
    # first/last epoch timestamp. _process_chunk_percell truncates every
    # observation's timestamp to a period boundary via polars' dt.truncate()
    # before grouping, so if the first epoch isn't already exactly on a
    # boundary (e.g. a receiver that started recording mid-day rather than
    # at midnight), an un-floored output_times grid never matches any
    # chunk_times value — every _merge_percell_results lookup silently
    # misses and the entire output ends up empty despite valid input data.
    time_start = pd.Timestamp(data_ds.epoch.values[0]).floor(pandas_freq)
    time_end = pd.Timestamp(data_ds.epoch.values[-1]).floor(pandas_freq)

    output_times = pd.date_range(
        start=time_start,
        end=time_end,
        freq=pandas_freq,
    )

    n_times = len(output_times)
    n_cells = len(selected_cells)

    print(f"📅 Output shape: {n_cells} cells × {n_times} time bins")

    # Result arrays (cell × time)
    cell_timeseries = np.full((n_cells, n_times), np.nan)
    cell_weights = np.zeros((n_cells, n_times))
    cell_counts = np.zeros((n_cells, n_times), dtype=int)

    cell_to_idx = {int(cell_id): i for i, cell_id in enumerate(selected_cells)}
    time_to_idx = {pd.Timestamp(t): i for i, t in enumerate(output_times)}

    chunk_starts = pd.date_range(
        start=time_start,
        end=time_end,
        freq=f"{chunk_days}D",
    )

    print(f"🔄 Processing {len(chunk_starts)} chunks...")

    for chunk_start in tqdm(chunk_starts, desc="Processing chunks"):
        chunk_end = min(
            chunk_start + pd.Timedelta(days=chunk_days),
            time_end,
        )
        chunk_data = data_ds.sel(epoch=slice(chunk_start, chunk_end))

        if len(chunk_data.epoch) == 0:
            continue

        chunk_results = _process_chunk_percell(
            chunk_data,
            selected_cells,
            temporal_resolution,
            value_var,
            cell_var,
            min_obs_per_cell_time,
            stat,
        )

        if chunk_results:
            _merge_percell_results(
                chunk_results,
                cell_timeseries,
                cell_weights,
                cell_counts,
                cell_to_idx,
                time_to_idx,  # ty: ignore[invalid-argument-type]
            )

        del chunk_data
        gc.collect()

    processing_time = time.time() - start_time

    result_ds = _create_percell_dataset(
        cell_timeseries,
        cell_weights,
        cell_counts,
        selected_cells,
        output_times,
        grid,
        processing_time,
        theta_range,
        phi_range,
        temporal_resolution,
        chunk_days,
    )

    valid_cell_times = np.sum(np.isfinite(cell_timeseries))
    total_cell_times = n_cells * n_times
    coverage = (valid_cell_times / total_cell_times) * 100

    print("\n✅ PER-CELL AGGREGATION COMPLETE!")
    print(f"⚡ Time: {processing_time / 60:.2f} minutes")
    print(f"📊 Output: {n_cells} cells × {n_times} times")
    print(f"📈 Coverage: {valid_cell_times:,} / {total_cell_times:,} ({coverage:.1f}%)")
    print("🎯 Ready for diurnal analysis, spatial patterns, custom aggregations!")

    return result_ds


# ==============================================================================
# Analysis functions
# ==============================================================================


def compute_global_average(percell_ds: xr.Dataset) -> xr.Dataset:
    """Compute observation-count–weighted global average from per-cell data.

    Parameters
    ----------
    percell_ds : xr.Dataset
        Output of :func:`compute_percell_timeseries`.

    Returns
    -------
    xr.Dataset
        Variables: ``global_timeseries``, ``spatial_std``,
        ``total_weights``, ``active_cells``.

    """
    weights = percell_ds.cell_weights
    values = percell_ds.cell_timeseries

    weighted_sum = (values * weights).sum(dim="cell", skipna=True)
    total_weights = weights.sum(dim="cell", skipna=True)

    global_mean = weighted_sum / total_weights

    valid_mask = np.isfinite(values)
    spatial_std = values.where(valid_mask).std(dim="cell", skipna=True)

    return xr.Dataset(
        {
            "global_timeseries": global_mean,
            "spatial_std": spatial_std,
            "total_weights": total_weights,
            "active_cells": valid_mask.sum(dim="cell"),
        }
    )


def compute_regional_average(
    percell_ds: xr.Dataset, region_cells: list[int] | np.ndarray
) -> xr.DataArray:
    """Compute observation-count–weighted average for a cell subset.

    Parameters
    ----------
    percell_ds : xr.Dataset
        Output of :func:`compute_percell_timeseries`.
    region_cells : array-like
        Cell IDs defining the region.

    Returns
    -------
    xr.DataArray
        Weighted regional mean time series.

    """
    regional_data = percell_ds.sel(cell=region_cells)

    weights = regional_data.cell_weights
    values = regional_data.cell_timeseries

    weighted_sum = (values * weights).sum(dim="cell", skipna=True)
    total_weights = weights.sum(dim="cell", skipna=True)

    return weighted_sum / total_weights


def analyze_diurnal_patterns(percell_ds: xr.Dataset) -> xr.Dataset:
    """Compute hourly means from per-cell time series.

    Parameters
    ----------
    percell_ds : xr.Dataset
        Output of :func:`compute_percell_timeseries`.

    Returns
    -------
    xr.Dataset
        Grouped by ``time.hour``.

    """
    return percell_ds.groupby("time.hour").mean(dim="time")


def analyze_spatial_patterns(percell_ds: xr.Dataset) -> xr.Dataset:
    """Compute time-averaged spatial field.

    Parameters
    ----------
    percell_ds : xr.Dataset
        Output of :func:`compute_percell_timeseries`.

    Returns
    -------
    xr.Dataset
        Time-averaged dataset.

    """
    return percell_ds.mean(dim="time")


# ==============================================================================
# Convenience wrappers
# ==============================================================================


def compute_hemisphere_percell(
    data_ds: xr.Dataset,
    grid: GridData,
    **kwargs: Any,
) -> xr.Dataset:
    """Daily per-cell time series for the full hemisphere."""
    return compute_percell_timeseries(
        data_ds=data_ds, grid=grid, temporal_resolution="1D", **kwargs
    )


def compute_zenith_percell(
    data_ds: xr.Dataset,
    grid: GridData,
    **kwargs: Any,
) -> xr.Dataset:
    """Daily per-cell time series restricted to θ ≤ 30°."""
    return compute_percell_timeseries(
        data_ds=data_ds,
        grid=grid,
        theta_range=(0, 30),
        temporal_resolution="1D",
        **kwargs,
    )


# ==============================================================================
# Internal helpers
# ==============================================================================


def _normalise_pandas_freq(freq_str: str) -> str:
    """Normalize a frequency string for pandas compatibility."""
    if freq_str in ("30T", "30min"):
        return "30min"
    if freq_str in ("15T", "15min"):
        return "15min"
    return freq_str


def _convert_to_polars_freq(freq_str: str) -> str:
    """Convert a pandas-style frequency string to polars truncate format.

    Examples: ``"1D"`` → ``"1d"``, ``"10min"`` → ``"10m"``, ``"10T"`` → ``"10m"``.
    """
    freq_lower = freq_str.lower()

    # "Nmin" → "Nm"
    match = re.search(r"(\d+)min", freq_lower)
    if match:
        return f"{match.group(1)}m"

    # Pandas "T" notation → "m"
    if "T" in freq_str:
        return freq_str.replace("T", "m")

    # Simple unit swaps
    return freq_str.replace("D", "d").replace("H", "h")


def _create_spatial_selection(
    grid: GridData,
    theta_range: tuple[float, float] | None,
    phi_range: tuple[float, float] | None,
) -> np.ndarray:
    """Return cell indices matching spatial filters (degrees)."""
    if theta_range is None and phi_range is None:
        return np.arange(grid.ncells)

    mask = np.ones(grid.ncells, dtype=bool)
    grid_df = grid.grid

    if theta_range is not None:
        theta_deg = np.degrees(grid_df["theta"].to_numpy())
        mask &= (theta_deg >= theta_range[0]) & (theta_deg <= theta_range[1])

    if phi_range is not None:
        phi_deg = np.degrees(grid_df["phi"].to_numpy())
        if phi_range[0] <= phi_range[1]:
            mask &= (phi_deg >= phi_range[0]) & (phi_deg <= phi_range[1])
        else:  # wraps around 360°
            mask &= (phi_deg >= phi_range[0]) | (phi_deg <= phi_range[1])

    return np.where(mask)[0]


def _process_chunk_percell(
    chunk_data: xr.Dataset,
    selected_cells: np.ndarray,
    temporal_resolution: str,
    value_var: str,
    cell_var: str,
    min_obs_per_cell_time: int,
    stat: str = "mean",
) -> dict | None:
    """Aggregate one time chunk into (time_bin, cell_id) stats via polars."""
    vod_values = chunk_data[value_var].values
    cell_values = chunk_data[cell_var].values
    epochs = chunk_data.epoch.values

    if vod_values.ndim == 1:
        vod_values = vod_values[:, None]
        cell_values = cell_values[:, None]

    valid_mask = (
        np.isfinite(vod_values)
        & np.isfinite(cell_values)
        & np.isin(cell_values, selected_cells)
    )

    if not np.any(valid_mask):
        return None

    epoch_idx, _ = np.where(valid_mask)
    flat_vod = vod_values[valid_mask]
    flat_cells = cell_values[valid_mask].astype(np.int32)
    flat_epochs = epochs[epoch_idx]

    polars_resolution = _convert_to_polars_freq(temporal_resolution)
    stat_expr = {
        "mean": pl.col("vod").mean(),
        "median": pl.col("vod").median(),
    }[stat]

    try:
        result = (
            pl.DataFrame(
                {
                    "epoch": pd.to_datetime(flat_epochs),
                    "cell_id": flat_cells,
                    "vod": flat_vod,
                }
            )
            .with_columns(
                pl.col("epoch").dt.truncate(polars_resolution).alias("time_bin")
            )
            .group_by(["time_bin", "cell_id"])
            .agg(
                [
                    stat_expr.alias("cell_mean"),
                    pl.col("vod").count().alias("cell_count"),
                ]
            )
            .filter(pl.col("cell_count") >= min_obs_per_cell_time)
            .sort(["time_bin", "cell_id"])
        )

        if len(result) == 0:
            return None

        return {
            "time_bins": result["time_bin"].to_numpy(),
            "cell_ids": result["cell_id"].to_numpy(),
            "means": result["cell_mean"].to_numpy(),
            "counts": result["cell_count"].to_numpy(),
        }

    except Exception as e:
        print(f"Error in per-cell processing: {e}")
        return None


def _merge_percell_results(
    chunk_results: dict,
    cell_timeseries: np.ndarray,
    cell_weights: np.ndarray,
    cell_counts: np.ndarray,
    cell_to_idx: dict[int, int],
    time_to_idx: dict[pd.Timestamp, int],
) -> None:
    """Write chunk results into the pre-allocated result arrays (in place)."""
    chunk_times = pd.to_datetime(chunk_results["time_bins"])
    chunk_cells = chunk_results["cell_ids"]
    chunk_means = chunk_results["means"]
    chunk_counts = chunk_results["counts"]

    for i in range(len(chunk_times)):
        time_idx = time_to_idx.get(chunk_times[i])
        cell_idx = cell_to_idx.get(int(chunk_cells[i]))

        if time_idx is not None and cell_idx is not None:
            cell_timeseries[cell_idx, time_idx] = chunk_means[i]
            cell_weights[cell_idx, time_idx] = chunk_counts[i]
            cell_counts[cell_idx, time_idx] = chunk_counts[i]


def _create_percell_dataset(
    cell_timeseries: np.ndarray,
    cell_weights: np.ndarray,
    cell_counts: np.ndarray,
    selected_cells: np.ndarray,
    output_times: pd.DatetimeIndex,
    grid: GridData,
    processing_time: float,
    theta_range: tuple[float, float] | None,
    phi_range: tuple[float, float] | None,
    temporal_resolution: str,
    chunk_days: int,
) -> xr.Dataset:
    """Assemble the final xr.Dataset from result arrays."""
    grid_df = grid.grid

    # Convert to pandas for .loc indexing if needed
    if hasattr(grid_df, "to_pandas"):
        grid_df_pd = grid_df.to_pandas()
    else:
        grid_df_pd = grid_df

    if hasattr(grid_df_pd, "loc"):
        cell_theta = np.degrees(grid_df_pd.loc[selected_cells, "theta"].values)
        cell_phi = np.degrees(grid_df_pd.loc[selected_cells, "phi"].values)
    else:
        theta_all = np.degrees(grid_df["theta"].to_numpy())
        phi_all = np.degrees(grid_df["phi"].to_numpy())
        cell_theta = theta_all[selected_cells]
        cell_phi = phi_all[selected_cells]

    return xr.Dataset(
        data_vars={
            "cell_timeseries": (
                ["cell", "time"],
                cell_timeseries,
                {
                    "long_name": "VOD time series per cell",
                    "units": "dimensionless",
                    "description": "SID-aggregated VOD per cell per time bin",
                },
            ),
            "cell_weights": (
                ["cell", "time"],
                cell_weights,
                {
                    "long_name": "Observation weights per cell",
                    "units": "count",
                    "description": "Number of SID observations per cell per time bin",
                },
            ),
            "cell_counts": (
                ["cell", "time"],
                cell_counts,
                {
                    "long_name": "Observation counts per cell",
                    "units": "count",
                    "description": "Same as cell_weights (for compatibility)",
                },
            ),
            "cell_theta": (
                ["cell"],
                cell_theta,
                {
                    "long_name": "Cell elevation angle",
                    "units": "degrees",
                    "description": "Elevation angle from zenith",
                },
            ),
            "cell_phi": (
                ["cell"],
                cell_phi,
                {
                    "long_name": "Cell azimuth angle",
                    "units": "degrees",
                    "description": "Azimuth angle",
                },
            ),
        },
        coords={
            "cell": selected_cells,
            "time": output_times,
        },
        attrs={
            "method": "per_cell_timeseries_aggregation",
            "processing_time_min": processing_time / 60,
            "temporal_resolution": temporal_resolution,
            "chunk_days": chunk_days,
            # Dict values aren't valid netCDF/CF attrs (must be str, Number,
            # ndarray, list, tuple, or bytes) — stringify so the output of
            # this function round-trips through to_netcdf()/open_dataset()
            # without callers having to know to clean attrs themselves.
            "spatial_selection": str(
                {
                    "theta_range": theta_range,
                    "phi_range": phi_range,
                    "selected_cells_count": len(selected_cells),
                    "total_cells": grid.ncells,
                }
            ),
            "usage_examples": str(
                {
                    "global_average": "compute_global_average(ds)",
                    "regional_subset": "ds.sel(cell=region_cells)",
                    "diurnal_analysis": "ds.groupby('time.hour').mean()",
                    "spatial_patterns": "ds.mean(dim='time')",
                }
            ),
        },
    )
