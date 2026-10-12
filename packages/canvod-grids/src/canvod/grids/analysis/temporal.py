"""Temporal analysis of gridded VOD data.

Weighted time-series computation, diurnal cycle analysis, and
temporal statistics with optional solar-position correction.

Classes
-------
``TemporalAnalysis``
    Main analysis class; binds a VOD dataset to a grid and exposes
    methods for aggregation, solar correction, diurnal binning, and
    basic plotting.

Notes
-----
* All spatial masks and weight arrays must be 1-D with length
  ``grid.ncells``.
* When a ``SolarPositionCalculator`` is attached (via *site_lat* /
  *site_lon*), additional solar-corrected and solar-binned methods
  become available.
* Plotting helpers are thin wrappers around ``matplotlib``; they
  return ``(fig, ax)`` so callers can continue customising the figure.

"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal, cast

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import structlog
import xarray as xr
from scipy.signal import savgol_filter

from canvod.grids.analysis.solar import SolarPositionCalculator

if TYPE_CHECKING:
    from canvod.grids.core.grid_data import GridData

logger = structlog.get_logger(__name__)


class TemporalAnalysis:
    """Temporal analysis of gridded VOD data.

    Binds a VOD dataset (with pre-assigned cell IDs) to a grid and
    exposes weighted aggregation, diurnal analysis, and plotting.

    Parameters
    ----------
    vod_ds : xr.Dataset
        Dataset containing VOD data and a ``cell_id_<grid_name>``
        variable.
    grid : GridData
        Grid instance (must expose ``.ncells``).
    grid_name : str
        Suffix for the cell-ID variable (e.g. ``'htm_10deg'``).
    site_lat : float or None, optional
        Site latitude in degrees.  Required for solar methods.
    site_lon : float or None, optional
        Site longitude in degrees.  Required for solar methods.
    site_elevation : float, optional
        Site elevation in meters (default 0).

    Raises
    ------
    ValueError
        If ``cell_id_<grid_name>`` is not present in *vod_ds*.

    Examples
    --------
    >>> analysis = TemporalAnalysis(vod_ds, grid, "htm_10deg")
    >>> ts = analysis.compute_timeseries(aggregate="1D")

    """

    def __init__(
        self,
        vod_ds: xr.Dataset,
        grid: GridData,
        grid_name: str,
        site_lat: float | None = None,
        site_lon: float | None = None,
        site_elevation: float = 0.0,
    ) -> None:
        """Initialize the temporal analysis helper.

        Parameters
        ----------
        vod_ds : xr.Dataset
            VOD dataset containing cell IDs.
        grid : GridData
            Grid instance.
        grid_name : str
            Grid name suffix for cell IDs.
        site_lat : float | None, optional
            Site latitude in degrees.
        site_lon : float | None, optional
            Site longitude in degrees.
        site_elevation : float, default 0.0
            Site elevation in meters.

        """
        self.vod_ds = vod_ds
        self.grid = grid
        self.grid_name = grid_name
        self.cell_id_var = f"cell_id_{grid_name}"

        # Solar calculator (optional)
        if site_lat is not None and site_lon is not None:
            self.solar_calc: SolarPositionCalculator | None = SolarPositionCalculator(
                lat=site_lat, lon=site_lon, elevation=site_elevation
            )
            logger.info(
                "solar calculator enabled for (%.4f°, %.4f°)",
                site_lat,
                site_lon,
            )
        else:
            self.solar_calc = None

        # Validate dataset
        if self.cell_id_var not in vod_ds:
            available = [
                str(v) for v in vod_ds.data_vars if str(v).startswith("cell_id_")
            ]
            raise ValueError(
                f"Cell ID variable '{self.cell_id_var}' not found in dataset. "
                f"Available: {available}"
            )

    # ------------------------------------------------------------------
    # Core aggregation
    # ------------------------------------------------------------------

    def compute_timeseries(
        self,
        var_name: str = "VOD",
        spatial_mask: np.ndarray | None = None,
        weights: np.ndarray | None = None,
        aggregate: str = "1D",
        min_cells: int = 1,
    ) -> xr.Dataset:
        """Compute a weighted time-series aggregated over space.

        Parameters
        ----------
        var_name : str, optional
            Data variable to aggregate.
        spatial_mask : np.ndarray or None, optional
            Boolean mask of shape ``(grid.ncells,)``; ``True`` = include.
        weights : np.ndarray or None, optional
            Cell weights of shape ``(grid.ncells,)``; normalized
            internally.  ``None`` → uniform weights.
        aggregate : str, optional
            Pandas-compatible frequency string for temporal resampling.
        min_cells : int, optional
            Minimum unique cells required per time bin.

        Returns
        -------
        xr.Dataset
            Variables: ``mean``, ``std``, ``n_cells``,
            ``n_observations``, ``sum_weights``.

        Raises
        ------
        ValueError
            If *var_name* is missing or mask/weight shapes are wrong.

        """
        if var_name not in self.vod_ds:
            raise ValueError(f"Variable '{var_name}' not found in dataset")

        logger.info(
            "compute_timeseries: var=%s aggregate=%s mask=%s weights=%s",
            var_name,
            aggregate,
            spatial_mask is not None,
            weights is not None,
        )

        var_data = self.vod_ds[var_name]
        cell_ids = self.vod_ds[self.cell_id_var]

        # Apply spatial mask
        if spatial_mask is not None:
            if spatial_mask.shape != (self.grid.ncells,):
                raise ValueError(
                    f"Spatial mask shape {spatial_mask.shape} doesn't match "
                    f"grid size ({self.grid.ncells},)"
                )
            data_mask = xr.zeros_like(cell_ids, dtype=bool)
            for cell_id in np.where(spatial_mask)[0]:
                data_mask = data_mask | (cell_ids == cell_id)
            var_data = var_data.where(data_mask)
            logger.debug(
                "spatial mask applied: %d/%d cells",
                spatial_mask.sum(),
                self.grid.ncells,
            )

        # Prepare weights
        weights = self._prepare_weights(weights)

        return self._compute_weighted_timeseries(
            var_data, cell_ids, weights, aggregate, min_cells
        )

    # ------------------------------------------------------------------
    # Solar-corrected aggregation
    # ------------------------------------------------------------------

    def compute_timeseries_solar_corrected(
        self,
        var_name: str = "VOD",
        spatial_mask: np.ndarray | None = None,
        weights: np.ndarray | None = None,
        aggregate: str = "1D",
        min_cells: int = 1,
        solar_correction: Literal[
            "normalize", "residual", "cos_correction"
        ] = "normalize",
        reference_zenith: float = 45.0,
        daytime_only: bool = False,
        twilight_angle: float = -6.0,
    ) -> xr.Dataset:
        """Compute a time-series after applying a solar correction.

        Parameters
        ----------
        var_name : str, optional
            Data variable to correct and aggregate.
        spatial_mask : np.ndarray or None, optional
            Cell selection mask.
        weights : np.ndarray or None, optional
            Cell weights.
        aggregate : str, optional
            Temporal resampling frequency.
        min_cells : int, optional
            Minimum cells per time bin.
        solar_correction : {'normalize', 'residual', 'cos_correction'}
            Correction method passed to
            :meth:`SolarPositionCalculator.apply_solar_correction`.
        reference_zenith : float, optional
            Reference zenith for normalization (degrees).
        daytime_only : bool, optional
            If ``True``, mask out nighttime epochs.
        twilight_angle : float, optional
            Solar-elevation threshold for daytime (degrees).

        Returns
        -------
        xr.Dataset
            Solar-corrected time-series with additional metadata attrs.

        Raises
        ------
        ValueError
            If no solar calculator is configured.

        """
        if self.solar_calc is None:
            raise ValueError(
                "Solar calculator not initialized. "
                "Provide site_lat and site_lon to TemporalAnalysis constructor."
            )

        logger.info(
            "solar-corrected timeseries: correction=%s daytime_only=%s",
            solar_correction,
            daytime_only,
        )

        var_data = self.vod_ds[var_name]

        # Apply solar correction
        var_data_corrected = self.solar_calc.apply_solar_correction(
            var_data, method=solar_correction, reference_zenith=reference_zenith
        )

        # Daytime filter
        if daytime_only:
            times = pd.to_datetime(var_data["epoch"].values)
            is_day = self.solar_calc.is_daytime(times, twilight_angle)
            is_day_da = xr.DataArray(
                is_day, coords={"epoch": var_data_corrected["epoch"]}, dims=["epoch"]
            )
            var_data_corrected = var_data_corrected.where(is_day_da)
            logger.debug(
                "daytime filter: %d/%d timesteps kept",
                is_day.sum(),
                len(is_day),
            )

        # Temporary dataset with corrected variable
        corrected_name = f"{var_name}_solar_corrected"
        ds_temp = self.vod_ds.copy()
        ds_temp[corrected_name] = var_data_corrected

        # Reuse compute_timeseries via a lightweight temporary instance
        analysis_temp = TemporalAnalysis.__new__(TemporalAnalysis)
        analysis_temp.vod_ds = ds_temp
        analysis_temp.grid = self.grid
        analysis_temp.grid_name = self.grid_name
        analysis_temp.cell_id_var = self.cell_id_var
        analysis_temp.solar_calc = self.solar_calc

        ts = analysis_temp.compute_timeseries(
            var_name=corrected_name,
            spatial_mask=spatial_mask,
            weights=weights,
            aggregate=aggregate,
            min_cells=min_cells,
        )

        # Solar metadata
        ts.attrs["solar_correction"] = solar_correction
        ts.attrs["reference_zenith"] = reference_zenith
        ts.attrs["daytime_only"] = daytime_only
        if daytime_only:
            ts.attrs["twilight_angle"] = twilight_angle

        return ts

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _prepare_weights(self, weights: np.ndarray | None) -> np.ndarray:
        """Validate and normalize a weight array.

        Returns uniform weights when *weights* is ``None``.
        """
        if weights is None:
            logger.debug("using uniform weights")
            return np.ones(self.grid.ncells) / self.grid.ncells

        if weights.shape != (self.grid.ncells,):
            raise ValueError(
                f"Weights shape {weights.shape} doesn't match "
                f"grid size ({self.grid.ncells},)"
            )
        w_sum = weights.sum()
        if w_sum > 0:
            weights = weights / w_sum
        logger.debug("using provided weights (sum before normalization=%.4f)", w_sum)
        return weights

    def _compute_weighted_timeseries(
        self,
        var_data: xr.DataArray,
        cell_ids: xr.DataArray,
        weights: np.ndarray,
        aggregate: str,
        min_cells: int,
    ) -> xr.Dataset:
        """Aggregate *var_data* into time bins with cell weights.

        Returns
        -------
        xr.Dataset
            ``mean``, ``std``, ``n_cells``, ``n_observations``,
            ``sum_weights`` on the ``epoch`` dimension.

        """
        times = var_data["epoch"].values
        n_sid = var_data.sizes.get("sid", 1)

        # Flatten (epoch × sid) → 1-D
        values = var_data.values.ravel()
        cells = cell_ids.values.ravel()

        valid = np.isfinite(values) & np.isfinite(cells)
        times_valid = np.repeat(times, n_sid)[valid]
        values_valid = values[valid]
        cells_valid = cells[valid].astype(int)

        df = pd.DataFrame(
            {"epoch": times_valid, "value": values_valid, "cell_id": cells_valid}
        )
        df["weight"] = df["cell_id"].map(
            lambda cid: weights[cid] if cid < len(weights) else 0.0
        )
        df["epoch"] = pd.to_datetime(df["epoch"])
        df = df.set_index("epoch")

        grouped = df.groupby(pd.Grouper(freq=aggregate))

        result_rows: list[dict] = []
        for time_bin, group in grouped:
            if len(group) == 0:
                continue
            n_cells = group["cell_id"].nunique()
            if n_cells < min_cells:
                continue

            w = group["weight"].values
            v = group["value"].values
            w_sum = w.sum()

            if w_sum > 0:
                weighted_mean = np.average(v, weights=w)
                weighted_std = np.sqrt(np.average((v - weighted_mean) ** 2, weights=w))
                result_rows.append(
                    {
                        "epoch": time_bin,
                        "mean": weighted_mean,
                        "std": weighted_std,
                        "n_cells": n_cells,
                        "n_observations": len(group),
                        "sum_weights": w_sum,
                    }
                )

        if not result_rows:
            logger.warning("no data after aggregation")
            return xr.Dataset()

        result_df = pd.DataFrame(result_rows)
        ds = xr.Dataset(
            {
                "mean": ("epoch", result_df["mean"].values),
                "std": ("epoch", result_df["std"].values),
                "n_cells": ("epoch", result_df["n_cells"].values),
                "n_observations": ("epoch", result_df["n_observations"].values),
                "sum_weights": ("epoch", result_df["sum_weights"].values),
            },
            coords={"epoch": result_df["epoch"].values},
        )
        ds.attrs["variable"] = var_data.name
        ds.attrs["grid"] = self.grid_name
        ds.attrs["aggregation"] = aggregate
        ds.attrs["min_cells"] = min_cells

        logger.info(
            "timeseries computed: %d steps, mean n_cells=%.1f",
            len(result_df),
            result_df["n_cells"].mean(),
        )
        return ds

    # ------------------------------------------------------------------
    # Diurnal cycle
    # ------------------------------------------------------------------

    def compute_diurnal_cycle(
        self,
        var_name: str = "VOD",
        spatial_mask: np.ndarray | None = None,
        weights: np.ndarray | None = None,
        hour_bins: int = 24,
        min_observations: int = 10,
    ) -> xr.Dataset:
        """Compute clock-time diurnal cycle (hour-of-day statistics).

        Parameters
        ----------
        var_name : str, optional
            Data variable to bin.
        spatial_mask : np.ndarray or None, optional
            Cell selection mask.
        weights : np.ndarray or None, optional
            Cell weights.
        hour_bins : int, optional
            Number of equal-width hour bins over [0, 24).
        min_observations : int, optional
            Minimum observations required per bin.

        Returns
        -------
        xr.Dataset
            ``mean``, ``std``, ``n_observations`` on the ``hour``
            coordinate.

        """
        if var_name not in self.vod_ds:
            raise ValueError(f"Variable '{var_name}' not found in dataset")

        logger.info("compute_diurnal_cycle: var=%s hour_bins=%d", var_name, hour_bins)

        var_data = self.vod_ds[var_name]
        cell_ids = self.vod_ds[self.cell_id_var]

        # Spatial mask
        if spatial_mask is not None:
            data_mask = xr.zeros_like(cell_ids, dtype=bool)
            for cell_id in np.where(spatial_mask)[0]:
                data_mask = data_mask | (cell_ids == cell_id)
            var_data = var_data.where(data_mask)

        weights = self._prepare_weights(weights)

        # Hour of day (fractional)
        times = pd.to_datetime(var_data["epoch"].values)
        hours = (
            pd.Series(times).dt.hour.to_numpy()
            + pd.Series(times).dt.minute.to_numpy() / 60.0
        )

        n_sid = var_data.sizes.get("sid", 1)
        hour_edges = np.linspace(0, 24, hour_bins + 1)
        hour_centers = (hour_edges[:-1] + hour_edges[1:]) / 2

        # Flatten
        values = var_data.values.ravel()
        cells = cell_ids.values.ravel()
        hours_flat = np.repeat(hours, n_sid)

        valid = np.isfinite(values) & np.isfinite(cells)
        df = pd.DataFrame(
            {
                "hour": hours_flat[valid],
                "value": values[valid],
                "cell_id": cells[valid].astype(int),
            }
        )
        df["weight"] = df["cell_id"].map(
            lambda cid: weights[cid] if cid < len(weights) else 0.0
        )
        df["hour_bin"] = pd.cut(
            df["hour"], bins=hour_edges, labels=hour_centers, include_lowest=True
        )

        grouped = df.groupby("hour_bin")

        means, stds, n_obs = [], [], []
        for hc in hour_centers:
            if hc in grouped.groups:
                group = grouped.get_group(hc)
                if len(group) >= min_observations:
                    w = group["weight"].values
                    v = group["value"].values
                    if w.sum() > 0:
                        wm = np.average(v, weights=w)
                        ws = np.sqrt(np.average((v - wm) ** 2, weights=w))
                    else:
                        wm, ws = np.nan, np.nan
                    means.append(wm)
                    stds.append(ws)
                    n_obs.append(len(group))
                else:
                    means.append(np.nan)
                    stds.append(np.nan)
                    n_obs.append(0)
            else:
                means.append(np.nan)
                stds.append(np.nan)
                n_obs.append(0)

        ds = xr.Dataset(
            {
                "mean": ("hour", np.array(means)),
                "std": ("hour", np.array(stds)),
                "n_observations": ("hour", np.array(n_obs)),
            },
            coords={"hour": hour_centers},
        )
        ds.attrs.update(
            {
                "variable": var_name,
                "grid": self.grid_name,
                "hour_bins": hour_bins,
                "min_observations": min_observations,
            }
        )
        logger.info(
            "diurnal cycle: %d bins, mean n_obs=%.1f",
            hour_bins,
            np.nanmean(n_obs),
        )
        return ds

    def compute_diurnal_cycle_solar(
        self,
        var_name: str = "VOD",
        spatial_mask: np.ndarray | None = None,
        weights: np.ndarray | None = None,
        n_solar_bins: int = 12,
        min_observations: int = 10,
    ) -> xr.Dataset:
        """Diurnal cycle binned by solar elevation instead of clock time.

        Accounts for seasonal variation in solar position, producing a
        more physically meaningful diurnal pattern.

        Parameters
        ----------
        var_name : str, optional
            Data variable to bin.
        spatial_mask : np.ndarray or None, optional
            Cell selection mask.
        weights : np.ndarray or None, optional
            Cell weights.
        n_solar_bins : int, optional
            Number of equal-width bins over [-20°, 90°].
        min_observations : int, optional
            Minimum observations per bin.

        Returns
        -------
        xr.Dataset
            ``mean``, ``std``, ``n_observations`` on the
            ``solar_elevation`` coordinate.

        Raises
        ------
        ValueError
            If no solar calculator is configured.

        """
        if self.solar_calc is None:
            raise ValueError(
                "Solar calculator not initialized. "
                "Provide site_lat and site_lon to TemporalAnalysis constructor."
            )

        logger.info("solar-binned diurnal cycle: n_bins=%d", n_solar_bins)

        var_data = self.vod_ds[var_name]
        cell_ids = self.vod_ds[self.cell_id_var]

        # Spatial mask
        if spatial_mask is not None:
            data_mask = xr.zeros_like(cell_ids, dtype=bool)
            for cell_id in np.where(spatial_mask)[0]:
                data_mask = data_mask | (cell_ids == cell_id)
            var_data = var_data.where(data_mask)

        weights = self._prepare_weights(weights)

        # Solar bins per epoch
        times = pd.to_datetime(var_data["epoch"].values)
        solar_bins = self.solar_calc.compute_solar_bins(times, n_bins=n_solar_bins)
        bin_edges = np.linspace(-20, 90, n_solar_bins + 1)
        bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2

        n_sid = var_data.sizes.get("sid", 1)

        # Flatten
        values = var_data.values.ravel()
        cells = cell_ids.values.ravel()
        bins_flat = np.repeat(solar_bins, n_sid)

        valid = np.isfinite(values) & np.isfinite(cells)
        df = pd.DataFrame(
            {
                "solar_bin": bins_flat[valid],
                "value": values[valid],
                "cell_id": cells[valid].astype(int),
            }
        )
        df["weight"] = df["cell_id"].map(
            lambda cid: weights[cid] if cid < len(weights) else 0.0
        )

        grouped = df.groupby("solar_bin")

        means, stds, n_obs = [], [], []
        for bin_idx in range(n_solar_bins):
            if bin_idx in grouped.groups:
                group = grouped.get_group(bin_idx)
                if len(group) >= min_observations:
                    w = group["weight"].values
                    v = group["value"].values
                    if w.sum() > 0:
                        wm = np.average(v, weights=w)
                        ws = np.sqrt(np.average((v - wm) ** 2, weights=w))
                    else:
                        wm, ws = np.nan, np.nan
                    means.append(wm)
                    stds.append(ws)
                    n_obs.append(len(group))
                else:
                    means.append(np.nan)
                    stds.append(np.nan)
                    n_obs.append(0)
            else:
                means.append(np.nan)
                stds.append(np.nan)
                n_obs.append(0)

        ds = xr.Dataset(
            {
                "mean": ("solar_elevation", np.array(means)),
                "std": ("solar_elevation", np.array(stds)),
                "n_observations": ("solar_elevation", np.array(n_obs)),
            },
            coords={"solar_elevation": bin_centers},
        )
        ds.attrs.update(
            {
                "variable": var_name,
                "grid": self.grid_name,
                "n_solar_bins": n_solar_bins,
                "min_observations": min_observations,
                "coordinate_type": "solar_elevation",
            }
        )
        logger.info(
            "solar-binned diurnal: %d bins, mean n_obs=%.1f",
            n_solar_bins,
            np.nanmean(n_obs),
        )
        return ds

    # ------------------------------------------------------------------
    # Solar metadata
    # ------------------------------------------------------------------

    def add_solar_metadata_to_timeseries(self, timeseries: xr.Dataset) -> xr.Dataset:
        """Attach solar zenith, azimuth and elevation to a time-series.

        Parameters
        ----------
        timeseries : xr.Dataset
            Time-series dataset with an ``epoch`` coordinate.

        Returns
        -------
        xr.Dataset
            Copy with ``solar_zenith``, ``solar_azimuth``,
            ``solar_elevation`` added.

        Raises
        ------
        ValueError
            If no solar calculator is configured.

        """
        if self.solar_calc is None:
            raise ValueError("Solar calculator not initialized")

        times = pd.to_datetime(timeseries["epoch"].values)
        zenith, azimuth = self.solar_calc.compute_solar_position(times)
        elevation = 90 - zenith

        ts_solar = timeseries.copy()
        ts_solar["solar_zenith"] = ("epoch", zenith)
        ts_solar["solar_azimuth"] = ("epoch", azimuth)
        ts_solar["solar_elevation"] = ("epoch", elevation)

        ts_solar["solar_zenith"].attrs = {
            "units": "degrees",
            "description": "Solar polar angle (0° = overhead)",
        }
        ts_solar["solar_azimuth"].attrs = {
            "units": "degrees",
            "description": "Solar azimuth angle (0° = North, 90° = East)",
        }
        ts_solar["solar_elevation"].attrs = {
            "units": "degrees",
            "description": "Solar elevation angle (0° = horizon, 90° = overhead)",
        }
        return ts_solar

    # ------------------------------------------------------------------
    # Plotting
    # ------------------------------------------------------------------

    def plot_timeseries(
        self,
        timeseries: xr.Dataset,
        smooth_window: int = 0,
        show_uncertainty: bool = True,
        show_n_cells: bool = False,
        ax: plt.Axes | None = None,
        **style_kwargs: Any,
    ) -> tuple[plt.Figure, plt.Axes]:
        """Plot a time-series with optional Savitzky-Golay smoothing.

        Parameters
        ----------
        timeseries : xr.Dataset
            Output of :meth:`compute_timeseries`.
        smooth_window : int, optional
            Savitzky-Golay window length (0 = off; forced odd internally).
        show_uncertainty : bool, optional
            Draw ±1 std band.
        show_n_cells : bool, optional
            Secondary y-axis showing cell count.
        ax : plt.Axes or None, optional
            Axes to draw on; created if ``None``.
        **style_kwargs
            ``ylabel``, ``title``, ``figsize`` forwarded to matplotlib.

        Returns
        -------
        fig, ax : plt.Figure, plt.Axes

        """
        if ax is None:
            figsize = style_kwargs.pop("figsize", (12, 6))
            fig, ax = plt.subplots(figsize=figsize)
        else:
            fig = cast(plt.Figure, ax.figure)

        time = timeseries["epoch"].values
        mean = timeseries["mean"].values
        std = timeseries["std"].values

        if smooth_window > 0:
            if smooth_window % 2 == 0:
                smooth_window += 1
            valid = np.isfinite(mean)
            if np.sum(valid) > smooth_window:
                mean_smooth = mean.copy()
                mean_smooth[valid] = savgol_filter(
                    mean[valid], smooth_window, polyorder=2
                )
                ax.plot(
                    time,
                    mean,
                    "o",
                    alpha=0.3,
                    label="Raw",
                    markersize=3,
                    color="gray",
                )
                ax.plot(
                    time,
                    mean_smooth,
                    "-",
                    label=f"Smoothed (window={smooth_window})",
                    linewidth=2,
                )
                mean_plot = mean_smooth
            else:
                ax.plot(time, mean, "o-", label="Mean")
                mean_plot = mean
        else:
            ax.plot(time, mean, "o-", label="Mean", markersize=4)
            mean_plot = mean

        if show_uncertainty and "std" in timeseries:
            ax.fill_between(
                time,
                mean_plot - std,
                mean_plot + std,
                alpha=0.2,
                label="±1 std",
            )

        if show_n_cells and "n_cells" in timeseries:
            ax2 = ax.twinx()
            ax2.plot(
                time,
                timeseries["n_cells"].values,
                "--",
                color="orange",
                alpha=0.5,
                label="N cells",
            )
            ax2.set_ylabel("Number of cells", color="orange")
            ax2.tick_params(axis="y", labelcolor="orange")

        ax.set_xlabel("Time")
        ax.set_ylabel(style_kwargs.get("ylabel", "Value"))
        ax.set_title(style_kwargs.get("title", "Timeseries"))
        ax.legend(loc="best")
        ax.grid(True, alpha=0.3)
        fig.tight_layout()
        return fig, ax

    def plot_diurnal_cycle(
        self,
        diurnal: xr.Dataset,
        show_confidence: bool = True,
        ax: plt.Axes | None = None,
        **style_kwargs: Any,
    ) -> tuple[plt.Figure, plt.Axes]:
        """Plot a clock-time diurnal cycle.

        Parameters
        ----------
        diurnal : xr.Dataset
            Output of :meth:`compute_diurnal_cycle`.
        show_confidence : bool, optional
            Draw ±1 std band.
        ax : plt.Axes or None, optional
            Axes to draw on; created if ``None``.
        **style_kwargs
            ``ylabel``, ``title``, ``figsize``.

        Returns
        -------
        fig, ax : plt.Figure, plt.Axes

        """
        if ax is None:
            figsize = style_kwargs.pop("figsize", (10, 6))
            fig, ax = plt.subplots(figsize=figsize)
        else:
            fig = cast(plt.Figure, ax.figure)

        hours = diurnal["hour"].values
        mean = diurnal["mean"].values
        std = diurnal["std"].values

        ax.plot(hours, mean, "o-", linewidth=2, markersize=6, label="Mean")
        if show_confidence:
            ax.fill_between(
                hours,
                mean - std,
                mean + std,
                alpha=0.2,
                label="±1 std",
            )

        ax.set_xlabel("Hour of Day")
        ax.set_ylabel(style_kwargs.get("ylabel", "Value"))
        ax.set_title(style_kwargs.get("title", "Diurnal Cycle"))
        ax.set_xlim(0, 24)
        ax.set_xticks(np.arange(0, 25, 3))
        ax.legend(loc="best")
        ax.grid(True, alpha=0.3)
        fig.tight_layout()
        return fig, ax

    def plot_diurnal_cycle_comparison(
        self,
        diurnal_clock: xr.Dataset,
        diurnal_solar: xr.Dataset,
        figsize: tuple[float, float] = (14, 6),
        **style_kwargs: Any,
    ) -> tuple[plt.Figure, np.ndarray]:
        """Side-by-side clock-time vs solar-time diurnal cycle plots.

        Parameters
        ----------
        diurnal_clock : xr.Dataset
            Output of :meth:`compute_diurnal_cycle`.
        diurnal_solar : xr.Dataset
            Output of :meth:`compute_diurnal_cycle_solar`.
        figsize : tuple, optional
            Figure size.
        **style_kwargs
            ``ylabel``, ``title``.

        Returns
        -------
        fig, axes : plt.Figure, np.ndarray of plt.Axes

        """
        fig, axes = plt.subplots(1, 2, figsize=figsize)

        # Clock-time panel
        hours = diurnal_clock["hour"].values
        mean_c = diurnal_clock["mean"].values
        std_c = diurnal_clock["std"].values

        axes[0].plot(hours, mean_c, "o-", linewidth=2, markersize=6)
        axes[0].fill_between(hours, mean_c - std_c, mean_c + std_c, alpha=0.2)
        axes[0].set_xlabel("Hour of Day")
        axes[0].set_ylabel(style_kwargs.get("ylabel", "Value"))
        axes[0].set_title("Clock-Time Diurnal Cycle")
        axes[0].set_xlim(0, 24)
        axes[0].set_xticks(np.arange(0, 25, 3))
        axes[0].grid(True, alpha=0.3)

        # Solar-elevation panel
        solar_elev = diurnal_solar["solar_elevation"].values
        mean_s = diurnal_solar["mean"].values
        std_s = diurnal_solar["std"].values

        axes[1].plot(
            solar_elev,
            mean_s,
            "o-",
            linewidth=2,
            markersize=6,
            color="orange",
        )
        axes[1].fill_between(
            solar_elev,
            mean_s - std_s,
            mean_s + std_s,
            alpha=0.2,
            color="orange",
        )
        axes[1].axvline(0, color="k", linestyle="--", alpha=0.3, label="Horizon")
        axes[1].set_xlabel("Solar Elevation (°)")
        axes[1].set_ylabel(style_kwargs.get("ylabel", "Value"))
        axes[1].set_title("Solar-Time Diurnal Cycle")
        axes[1].grid(True, alpha=0.3)
        axes[1].legend()

        fig.suptitle(
            style_kwargs.get("title", "Diurnal Cycle Comparison"), fontsize=14, y=1.02
        )
        fig.tight_layout()
        return fig, axes
