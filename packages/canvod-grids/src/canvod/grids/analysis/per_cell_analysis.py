"""Per-cell VOD analysis and plotting.

Statistical aggregation, diurnal dynamics, radial distributions, and
theta-time heatmaps for per-cell VOD datasets.  Handles single
datasets or lists of datasets with configurable multi-dataset modes
(separate vs averaged).

Classes
-------
``PerCellVODAnalyzer``
    Main analysis class.  Accepts one or more per-cell datasets
    (each must expose ``cell_timeseries``, ``cell_theta``,
    ``cell_phi``).

Utility functions
-----------------
``extract_percell_stats``            – temporal statistic per cell.
``percell_to_grid_counts``           – total observation counts per cell.
``extract_percell_temporal_stats``   – range / trend / CV per cell.
``extract_percell_coverage``         – data-coverage percentage per cell.
``percell_to_grid_data``             – thin wrapper around
                                       :func:`extract_percell_stats`.

Notes
-----
* Per-cell datasets are expected to have dimensions
  ``(cell, time)`` and variables ``cell_timeseries``, ``cell_theta``,
  ``cell_phi``, and optionally ``cell_weights`` and ``cell_counts``.
* Spatial *visualization* (hemisphere maps) lives in ``canvod-viz``.

"""

from __future__ import annotations

import hashlib
from typing import Literal

import numpy as np
import pandas as pd
import structlog
import xarray as xr

logger = structlog.get_logger(__name__)


# ======================================================================
# Main analysis class
# ======================================================================


class PerCellVODAnalyzer:
    """Multi-dataset per-cell VOD analyzer.

    Parameters
    ----------
    datasets : xr.Dataset or list of xr.Dataset
        Per-cell dataset(s).  Each must contain ``cell_timeseries``,
        ``cell_theta``, and ``cell_phi``.
    labels : list of str or None, optional
        Human-readable labels for each dataset.

    Raises
    ------
    ValueError
        If any dataset is missing required variables.

    """

    def __init__(
        self,
        datasets: xr.Dataset | list[xr.Dataset],
        labels: list[str] | None = None,
    ) -> None:
        """Initialize the analyzer.

        Parameters
        ----------
        datasets : xr.Dataset | list[xr.Dataset]
            Per-cell dataset(s).
        labels : list[str] | None, optional
            Labels for each dataset.

        """
        if isinstance(datasets, xr.Dataset):
            self.datasets = [datasets]
            self.labels = ["Dataset"] if labels is None else [labels[0]]
        else:
            self.datasets = datasets
            self.labels = labels or [f"Dataset {i + 1}" for i in range(len(datasets))]

        self._validate_datasets()
        logger.info(
            "PerCellVODAnalyzer: %d dataset(s), shapes=%s",
            len(self.datasets),
            [ds.cell_timeseries.shape for ds in self.datasets],
        )

    def _validate_datasets(self) -> None:
        """Raise if any dataset is missing required variables."""
        required = {"cell_timeseries", "cell_theta", "cell_phi"}
        for i, ds in enumerate(self.datasets):
            missing = required - set(ds.data_vars)
            if missing:
                raise ValueError(f"Dataset {i + 1} missing variables: {missing}")

    # ------------------------------------------------------------------
    # Computation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _generate_dataset_hash(ds: xr.Dataset) -> str:
        """Deterministic hash for a per-cell dataset (for optional caching).

        Samples up to 10 000 values from ``cell_timeseries`` for
        efficiency on large datasets.
        """
        parts: list[str] = []

        parts.append(hashlib.md5(ds.time.values.tobytes()).hexdigest()[:8])

        cell_data = ds.cell_timeseries.values
        if cell_data.size > 10_000:
            idx = np.linspace(0, cell_data.size - 1, 10_000, dtype=int)
            sample = cell_data.flat[idx]
        else:
            sample = cell_data.flatten()

        valid = sample[np.isfinite(sample)]
        if len(valid) > 0:
            parts.append(hashlib.md5(valid.tobytes()).hexdigest()[:8])

        shape_str = f"{ds.cell_timeseries.shape}_{len(ds.time)}"
        parts.append(hashlib.md5(shape_str.encode()).hexdigest()[:8])

        return hashlib.md5("_".join(parts).encode()).hexdigest()[:16]

    def _compute_diurnal_dynamics(self, ds: xr.Dataset) -> dict:
        """Hourly diurnal statistics (mean, std, count) from one dataset.

        Uses ``cell_weights`` when available.
        """
        cell_ts = ds.cell_timeseries
        hours = pd.Series(pd.to_datetime(ds.time.values)).dt.hour.to_numpy()
        unique_hours = np.unique(hours)

        means, stds, counts = [], [], []

        for hour in unique_hours:
            mask = hours == hour
            if not np.any(mask):
                means.append(np.nan)
                stds.append(np.nan)
                counts.append(0)
                continue

            hour_data = cell_ts[:, mask]

            if "cell_weights" in ds.data_vars:
                w = ds.cell_weights[:, mask]
                w_sum = np.nansum(w, axis=0)
                w_sum[w_sum == 0] = np.nan
                weighted_means = np.nansum(hour_data * w, axis=0) / w_sum
                means.append(float(np.nanmean(weighted_means)))
                stds.append(float(np.nanstd(weighted_means)))
            else:
                means.append(float(np.nanmean(hour_data)))
                stds.append(float(np.nanstd(hour_data)))

            counts.append(int(np.sum(np.isfinite(hour_data))))

        return {
            "hours": unique_hours,
            "means": np.array(means),
            "stds": np.array(stds),
            "counts": np.array(counts),
        }

    def _compute_diurnal_dynamics_30min(self, ds: xr.Dataset) -> dict:
        """30-minute-resolution diurnal statistics from one dataset."""
        cell_ts = ds.cell_timeseries
        time_series = pd.Series(pd.to_datetime(ds.time.values))
        hours = time_series.dt.hour.to_numpy()
        minutes = time_series.dt.minute.to_numpy()
        bins_30 = hours * 2 + (minutes >= 30).astype(int)
        unique_bins = np.unique(bins_30)

        means, stds, counts, labels = [], [], [], []

        for b in unique_bins:
            mask = bins_30 == b
            if not np.any(mask):
                means.append(np.nan)
                stds.append(np.nan)
                counts.append(0)
            else:
                bin_data = cell_ts[:, mask]
                if "cell_weights" in ds.data_vars:
                    w = ds.cell_weights[:, mask]
                    w_sum = np.nansum(w, axis=0)
                    w_sum[w_sum == 0] = np.nan
                    wm = np.nansum(bin_data * w, axis=0) / w_sum
                    means.append(float(np.nanmean(wm)))
                    stds.append(float(np.nanstd(wm)))
                else:
                    means.append(float(np.nanmean(bin_data)))
                    stds.append(float(np.nanstd(bin_data)))
                counts.append(int(np.sum(np.isfinite(bin_data))))

            h, m = int(b) // 2, 30 if (int(b) % 2) else 0
            labels.append(f"{h:02d}:{m:02d}")

        return {
            "time_bins": unique_bins,
            "time_labels": labels,
            "means": np.array(means),
            "stds": np.array(stds),
            "counts": np.array(counts),
        }

    def _compute_averaged_diurnal_dynamics(self) -> dict:
        """Average diurnal dynamics across all datasets.

        Uncertainty is propagated as σ_avg = √(Σσᵢ²) / N.
        """
        all_data = [self._compute_diurnal_dynamics(ds) for ds in self.datasets]
        all_hours = [d["hours"] for d in all_data]
        common = sorted(set.intersection(*[set(h) for h in all_hours]))

        avg_means, avg_stds, avg_counts = [], [], []
        for hour in common:
            h_means, h_stds, h_counts = [], [], []
            for d in all_data:
                idx = np.where(d["hours"] == hour)[0]
                if len(idx):
                    h_means.append(d["means"][idx[0]])
                    h_stds.append(d["stds"][idx[0]])
                    h_counts.append(d["counts"][idx[0]])
            if h_means:
                avg_means.append(np.nanmean(h_means))
                avg_stds.append(np.sqrt(np.nansum(np.array(h_stds) ** 2)) / len(h_stds))
                avg_counts.append(int(np.sum(h_counts)))

        return {
            "hours": np.array(common),
            "means": np.array(avg_means),
            "stds": np.array(avg_stds),
            "counts": np.array(avg_counts),
        }

    def _compute_combined_diurnal_distributions(self) -> dict[int, list[float]]:
        """Collect all hourly value distributions across all datasets."""
        combined: dict[int, list[float]] = {}
        for hour in range(24):
            vals: list[float] = []
            for ds in self.datasets:
                ds_hours = pd.Series(pd.to_datetime(ds.time.values)).dt.hour.to_numpy()
                mask = ds_hours == hour
                if np.any(mask):
                    raw = ds.cell_timeseries[:, mask].values.flatten()
                    vals.extend(raw[np.isfinite(raw)].tolist())
            if vals:
                combined[hour] = vals
        return combined

    def _compute_radial_distribution(self, ds: xr.Dataset) -> dict:
        """Bin mean VOD by polar angle (5° bins, 0–90°)."""
        polar = 90.0 - ds.cell_theta.values
        mean_vod = ds.cell_timeseries.mean(dim="time").values

        edges = np.arange(0, 95, 5)
        centers = edges[:-1] + 2.5
        indices = np.digitize(polar, edges)

        binned, labels = [], []
        for i, c in enumerate(centers):
            mask = indices == i + 1
            if np.any(mask):
                clean = mean_vod[mask]
                clean = clean[np.isfinite(clean)]
                if len(clean) > 0:
                    binned.append(clean)
                    labels.append(f"{edges[i]:.0f}-{edges[i + 1]:.0f}°")

        return {
            "binned_data": binned,
            "bin_labels": labels,
            "bin_centers": centers[: len(binned)],
        }

    def _compute_averaged_radial_distribution(self) -> dict:
        """Average radial distributions across all datasets."""
        all_radial = [self._compute_radial_distribution(ds) for ds in self.datasets]
        all_centers = [d["bin_centers"] for d in all_radial]
        common = sorted(set.intersection(*[set(c) for c in all_centers]))

        avg_binned, avg_labels = [], []
        for c in common:
            combined: list[float] = []
            for d in all_radial:
                idx = np.where(np.abs(d["bin_centers"] - c) < 0.1)[0]
                if len(idx):
                    combined.extend(d["binned_data"][idx[0]])
            if combined:
                avg_binned.append(combined)
                avg_labels.append(f"{c - 2.5:.0f}-{c + 2.5:.0f}°")

        return {
            "binned_data": avg_binned,
            "bin_labels": avg_labels,
            "bin_centers": np.array(common),
        }

    def _compute_single_theta_time_heatmap(
        self, ds: xr.Dataset, time_aggregation: str, theta_bins: int
    ) -> tuple[np.ndarray, dict]:
        """Compute one theta × time heatmap."""
        polar = 90.0 - ds.cell_theta.values
        cell_ts = ds.cell_timeseries.values
        time_coord = ds.time.values

        edges = np.linspace(0, 90, theta_bins + 1)
        time_info = self._process_time_aggregation(time_coord, time_aggregation)

        heatmap = np.full((theta_bins, time_info["n_time_bins"]), np.nan)

        for i in range(theta_bins):
            theta_mask = (polar >= edges[i]) & (polar < edges[i + 1])
            if not np.any(theta_mask):
                continue
            bin_ts = cell_ts[theta_mask, :]
            for t in range(time_info["n_time_bins"]):
                t_mask = time_info["time_groups"] == t
                if np.any(t_mask):
                    heatmap[i, t] = np.nanmean(bin_ts[:, t_mask])

        return heatmap, time_info

    def _compute_averaged_theta_time_heatmap(
        self, time_aggregation: str, theta_bins: int
    ) -> tuple[np.ndarray, dict]:
        """Average theta-time heatmaps across all datasets."""
        heatmaps: list[np.ndarray] = []
        time_info: dict[str, object] | None = None
        for ds in self.datasets:
            h, ti = self._compute_single_theta_time_heatmap(
                ds,
                time_aggregation,
                theta_bins,
            )
            heatmaps.append(h)
            if time_info is None:
                time_info = ti
        if time_info is None:
            raise ValueError("No datasets available for averaged theta-time heatmap")
        return np.nanmean(np.stack(heatmaps, axis=0), axis=0), time_info

    @staticmethod
    def _process_time_aggregation(
        time_coord: np.ndarray,
        time_aggregation: str,
    ) -> dict:
        """Map raw timestamps to integer group indices.

        Returns
        -------
        dict
            ``time_groups``, ``n_time_bins``, ``time_ticks``,
            ``time_tick_labels``, ``x_label``.

        """
        if time_aggregation == "diurnal":
            groups = pd.Series(pd.to_datetime(time_coord)).dt.hour.to_numpy()
            n = 24
            ticks = np.arange(0, 24, 4)
            tick_labels = [f"{h:02d}:00" for h in ticks]
            xlabel = "Hour of Day (UTC)"

        elif time_aggregation == "daily":
            groups = np.arange(len(time_coord))
            n = len(time_coord)
            ticks = np.arange(0, n, max(1, n // 10))
            tick_labels = (
                pd.to_datetime(time_coord)[ticks].strftime("%Y-%m-%d").tolist()
            )
            xlabel = "Date"

        elif time_aggregation == "weekly":
            dates = pd.to_datetime(time_coord)
            weeks = dates.isocalendar().week
            unique_weeks = np.unique(weeks)
            groups = np.searchsorted(unique_weeks, weeks)
            n = len(unique_weeks)
            ticks = np.arange(0, n, max(1, n // 10))
            tick_labels = [f"Week {unique_weeks[i]}" for i in ticks]
            xlabel = "Week"

        elif time_aggregation == "monthly":
            dates = pd.to_datetime(time_coord)
            months = pd.Series(dates).dt.month.to_numpy()
            unique_months = np.unique(months)
            groups = np.searchsorted(unique_months, months)
            n = len(unique_months)
            ticks = np.arange(0, n)
            tick_labels = [f"Month {unique_months[i]}" for i in ticks]
            xlabel = "Month"

        else:
            raise ValueError(f"Unknown time_aggregation: '{time_aggregation}'")

        return {
            "time_groups": groups,
            "n_time_bins": n,
            "time_ticks": ticks,
            "time_tick_labels": tick_labels,
            "x_label": xlabel,
        }


# ======================================================================
# Heatmap computation helpers
# ======================================================================


def _compute_single_heatmap(ds: xr.Dataset, theta_bins: int) -> np.ndarray:
    """Bin cells by polar angle and compute temporal mean per bin.

    Parameters
    ----------
    ds : xr.Dataset
        Per-cell dataset with ``cell_theta`` and ``cell_timeseries``.
    theta_bins : int
        Number of polar-angle bins spanning 0–90°.

    Returns
    -------
    np.ndarray
        Shape ``(theta_bins, n_times)`` heatmap; NaN where no cells fall
        in a bin.

    """
    elevation_angles = ds.cell_theta.values
    polar_angles = 90.0 - elevation_angles
    cell_timeseries = ds.cell_timeseries.values

    n_times = cell_timeseries.shape[1]
    theta_bin_edges = np.linspace(0, 90, theta_bins + 1)

    heatmap_data = np.full((theta_bins, n_times), np.nan)

    for i in range(theta_bins):
        theta_mask = (polar_angles >= theta_bin_edges[i]) & (
            polar_angles < theta_bin_edges[i + 1]
        )
        if np.any(theta_mask):
            bin_timeseries = cell_timeseries[theta_mask, :]
            heatmap_data[i, :] = np.nanmean(bin_timeseries, axis=0)

    return heatmap_data


def _compute_averaged_heatmap(
    datasets: list[xr.Dataset], theta_bins: int
) -> np.ndarray:
    """Average heatmaps computed from multiple per-cell datasets.

    Parameters
    ----------
    datasets : list of xr.Dataset
        Per-cell datasets passed to :func:`_compute_single_heatmap`.
    theta_bins : int
        Number of polar-angle bins.

    Returns
    -------
    np.ndarray
        Mean heatmap across datasets.

    """
    heatmaps = [_compute_single_heatmap(ds, theta_bins) for ds in datasets]
    stacked_heatmaps = np.stack(heatmaps, axis=0)
    return np.nanmean(stacked_heatmaps, axis=0)


# ======================================================================
# Per-cell extraction utilities
# ======================================================================


def extract_percell_stats(
    percell_ds: xr.Dataset,
    stat: Literal["mean", "median", "std"] = "median",
) -> np.ndarray:
    """Compute a single temporal statistic for every cell.

    Parameters
    ----------
    percell_ds : xr.Dataset
        Per-cell dataset with a ``cell_timeseries`` variable of shape
        ``(cell, time)``.
    stat : {"mean", "median", "std"}
        Statistic to reduce across the ``time`` dimension.

    Returns
    -------
    np.ndarray
        1-D array of length ``n_cells``.

    """
    cell_timeseries = percell_ds.cell_timeseries

    if stat == "mean":
        cell_values = cell_timeseries.mean(dim="time")
    elif stat == "median":
        cell_values = cell_timeseries.median(dim="time")
    elif stat == "std":
        cell_values = cell_timeseries.std(dim="time")
    else:
        raise ValueError(f"Unsupported stat: {stat}")

    return cell_values.values


def percell_to_grid_counts(percell_ds: xr.Dataset) -> np.ndarray:
    """Sum observation counts across time for each cell.

    Parameters
    ----------
    percell_ds : xr.Dataset
        Per-cell dataset with a ``cell_counts`` variable of shape
        ``(cell, time)``.

    Returns
    -------
    np.ndarray
        1-D array of total counts per cell.

    """
    cell_counts = percell_ds.cell_counts
    return cell_counts.sum(dim="time").values


def extract_percell_temporal_stats(
    percell_ds: xr.Dataset,
    stat: Literal["range", "trend", "cv"] = "range",
) -> np.ndarray:
    """Compute a temporal-characteristic statistic for every cell.

    Parameters
    ----------
    percell_ds : xr.Dataset
        Per-cell dataset with ``cell_timeseries``.
    stat : {"range", "trend", "cv"}
        Statistic:

        * ``"range"`` – max − min over time.
        * ``"trend"`` – linear-regression slope (requires ≥ 4 valid points;
          otherwise NaN).  Uses :mod:`scipy.stats`.
        * ``"cv"``    – coefficient of variation (std / mean).

    Returns
    -------
    np.ndarray
        1-D array of length ``n_cells``.

    """
    from scipy import stats

    cell_timeseries = percell_ds.cell_timeseries

    if stat == "range":
        cell_max = cell_timeseries.max(dim="time")
        cell_min = cell_timeseries.min(dim="time")
        result = cell_max - cell_min

    elif stat == "trend":
        trends = []
        for i in range(cell_timeseries.shape[0]):
            cell_data = cell_timeseries.values[i, :]
            valid_mask = np.isfinite(cell_data)

            if np.sum(valid_mask) > 3:
                time_indices = np.arange(len(cell_data))[valid_mask]
                values = cell_data[valid_mask]
                slope, _, _, _, _ = stats.linregress(time_indices, values)
                trends.append(slope)
            else:
                trends.append(np.nan)

        result = xr.DataArray(trends, dims=["cell"])

    elif stat == "cv":
        cell_mean = cell_timeseries.mean(dim="time")
        cell_std = cell_timeseries.std(dim="time")
        result = cell_std / cell_mean

    else:
        raise ValueError(f"Unsupported temporal stat: {stat}")

    return result.values


def extract_percell_coverage(percell_ds: xr.Dataset) -> np.ndarray:
    """Compute the fraction of valid (non-NaN) observations per cell.

    Parameters
    ----------
    percell_ds : xr.Dataset
        Per-cell dataset with ``cell_timeseries``.

    Returns
    -------
    np.ndarray
        1-D array of coverage percentages (0–100) per cell.

    """
    cell_timeseries = percell_ds.cell_timeseries

    valid_count = np.isfinite(cell_timeseries).sum(dim="time")
    total_count = cell_timeseries.sizes["time"]

    coverage_pct = (valid_count / total_count) * 100
    return coverage_pct.values


def percell_to_grid_data(
    percell_ds: xr.Dataset,
    stat: Literal["mean", "median", "std"] = "median",
) -> np.ndarray:
    """Thin wrapper around :func:`extract_percell_stats`.

    Provided for symmetry with ``aggregate_data_to_grid`` workflows.

    Parameters
    ----------
    percell_ds : xr.Dataset
        Per-cell dataset.
    stat : {"mean", "median", "std"}
        Statistic to compute.

    Returns
    -------
    np.ndarray
        1-D array compatible with grid visualization.

    """
    return extract_percell_stats(percell_ds, stat=stat)
