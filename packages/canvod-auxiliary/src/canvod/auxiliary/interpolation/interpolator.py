"""Interpolation strategies for GNSS auxiliary data.

Provides specialized interpolation for:
- SP3 ephemeris: Hermite cubic splines using satellite velocities
- CLK clock: Piecewise linear with discontinuity detection
"""

from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import numpy as np
import xarray as xr
from pydantic import ConfigDict
from pydantic.dataclasses import dataclass
from scipy.interpolate import CubicHermiteSpline, interp1d


class InterpolatorConfig:
    """Base class for interpolator configuration."""

    def to_dict(self) -> dict[str, Any]:
        """Convert config to dictionary for attrs storage."""
        return dict(vars(self))


def _detect_jumps(data: np.ndarray, window_size: int, threshold: float) -> np.ndarray:
    """Detect clock-jump discontinuities via a windowed before/after comparison.

    For each candidate boundary, compares the mean of up to ``window_size``
    samples immediately before it to the mean of up to ``window_size``
    samples immediately after it. This is more robust to single-sample noise
    than a raw two-point ``np.diff``: a noisy outlier gets smoothed out by
    averaging with its neighbors on both sides, whereas a genuine clock reset
    keeps the two windows separated regardless of window size.

    ``window_size <= 1`` degenerates to the raw two-point diff.

    Parameters
    ----------
    data : np.ndarray
        Clock data for one satellite, already restricted to valid (non-NaN)
        samples.
    window_size : int
        Number of samples on each side of a candidate boundary to average.
    threshold : float
        Jump threshold for discontinuity detection.

    Returns
    -------
    np.ndarray
        Indices ``i`` such that a jump lies between ``data[i]`` and
        ``data[i + 1]`` — the same convention as
        ``np.where(np.abs(np.diff(data)) > threshold)[0]``.
    """
    n = len(data)
    if n < 2:
        return np.array([], dtype=int)
    if window_size <= 1:
        return np.where(np.abs(np.diff(data)) > threshold)[0]

    idx = np.arange(1, n)
    lo = np.maximum(0, idx - window_size)
    hi = np.minimum(n, idx + window_size)
    cumsum = np.concatenate(([0.0], np.cumsum(data)))
    before_mean = (cumsum[idx] - cumsum[lo]) / (idx - lo)
    after_mean = (cumsum[hi] - cumsum[idx]) / (hi - idx)
    score = np.abs(after_mean - before_mean)

    flagged = score > threshold
    if not np.any(flagged):
        return np.array([], dtype=int)

    # A genuine step elevates the score for every candidate boundary whose
    # window still spans it, not just the true edge — collapse each
    # contiguous flagged run to its single highest-scoring boundary.
    edges = np.diff(flagged.astype(np.int8))
    run_starts = np.where(edges == 1)[0] + 1
    run_ends = np.where(edges == -1)[0] + 1
    if flagged[0]:
        run_starts = np.concatenate(([0], run_starts))
    if flagged[-1]:
        run_ends = np.concatenate((run_ends, [len(flagged)]))

    # idx[j] is the sample starting the "after" side; the diff convention
    # callers expect wants the sample ending the "before" side (idx[j] - 1).
    return np.array(
        [
            idx[start + int(np.argmax(score[start:end]))] - 1
            for start, end in zip(run_starts, run_ends, strict=True)
        ],
        dtype=int,
    )


@dataclass
class Sp3Config(InterpolatorConfig):
    """Configuration for SP3 ephemeris interpolation.

    Attributes
    ----------
    use_velocities : bool, default True
        Use Hermite splines with satellite velocities if available.
    fallback_method : str, default 'linear'
        Interpolation method when velocities are unavailable.
    """

    use_velocities: bool = True
    fallback_method: str = "linear"


@dataclass
class ClockConfig(InterpolatorConfig):
    """Configuration for clock correction interpolation.

    Attributes
    ----------
    window_size : int, default 9
        Window size for discontinuity detection.
    jump_threshold : float, default 1e-6
        Threshold for detecting clock jumps (seconds).
    """

    window_size: int = 9
    jump_threshold: float = 1e-6


@dataclass(config=ConfigDict(arbitrary_types_allowed=True))
class Interpolator(ABC):
    """Abstract base class for interpolation strategies.

    Notes
    -----
    This is a Pydantic dataclass with `arbitrary_types_allowed=True` and
    uses `ABC` to define required interpolation hooks.
    """

    config: InterpolatorConfig

    @abstractmethod
    def interpolate(self, ds: xr.Dataset, target_epochs: np.ndarray) -> xr.Dataset:
        """Interpolate dataset to match target epochs.

        Parameters
        ----------
        ds : xr.Dataset
            Source dataset with (epoch, sid) dimensions.
        target_epochs : np.ndarray
            Target epoch grid (datetime64).

        Returns
        -------
        xr.Dataset
            Interpolated dataset at target epochs.
        """
        pass

    def to_attrs(self) -> dict[str, Any]:
        """Convert interpolator to attrs-compatible dictionary."""
        return {
            "interpolator_type": self.__class__.__name__,
            "config": self.config.to_dict(),
        }


@dataclass(config=ConfigDict(arbitrary_types_allowed=True))
class Sp3InterpolationStrategy(Interpolator):
    """Hermite cubic spline interpolation for SP3 ephemeris data.

    Uses satellite velocities (Vx, Vy, Vz) for higher accuracy.
    Falls back to linear interpolation if velocities unavailable.

    Examples
    --------
    >>> from canvod.auxiliary.interpolation import Sp3InterpolationStrategy, Sp3Config
    >>>
    >>> config = Sp3Config(use_velocities=True, fallback_method='linear')
    >>> interpolator = Sp3InterpolationStrategy(config=config)
    >>>
    >>> # Interpolate to RINEX epochs
    >>> sp3_interp = interpolator.interpolate(sp3_data, rinex_epochs)
    """

    config: Sp3Config

    def interpolate(self, ds: xr.Dataset, target_epochs: np.ndarray) -> xr.Dataset:
        """Interpolate SP3 ephemeris to target epochs."""
        if self.config.use_velocities and all(v in ds for v in ["Vx", "Vy", "Vz"]):
            return self._interpolate_with_velocities(ds, target_epochs)
        return self._interpolate_positions_only(ds, target_epochs)

    def _interpolate_with_velocities(
        self, ds: xr.Dataset, target_epochs: np.ndarray
    ) -> xr.Dataset:
        """Hermite interpolation using satellite velocities."""
        # Determine satellite dimension (sv or sid)
        sat_dim = "sv" if "sv" in ds.dims else "sid"
        sat_values = ds[sat_dim].values

        result_ds = xr.Dataset(coords={"epoch": target_epochs, sat_dim: sat_values})

        # Convert epochs to seconds (relative to first epoch)
        t_source = (
            (ds["epoch"] - ds["epoch"].values[0])
            .values.astype("timedelta64[s]")
            .astype(float)
        )

        t_target = (
            (target_epochs - ds["epoch"].values[0])
            .astype("timedelta64[s]")
            .astype(float)
        )

        # Pre-allocate output arrays
        n_targets = len(target_epochs)
        n_sats = len(sat_values)
        coords = {
            "X": np.empty((n_targets, n_sats)),
            "Y": np.empty((n_targets, n_sats)),
            "Z": np.empty((n_targets, n_sats)),
        }

        vels = {
            "Vx": np.empty((n_targets, n_sats)),
            "Vy": np.empty((n_targets, n_sats)),
            "Vz": np.empty((n_targets, n_sats)),
        }

        # Parallel interpolation per satellite
        with ThreadPoolExecutor() as executor:
            futures = []
            for i, sat in enumerate(sat_values):
                futures.append(
                    executor.submit(
                        self._interpolate_sat,
                        ds,
                        sat,
                        sat_dim,
                        t_source,
                        t_target,
                        i,
                        coords,
                        vels,
                    )
                )

            # Wait for completion
            for future in futures:
                future.result()

        # Assign results to dataset
        for coord, data in coords.items():
            result_ds[coord] = (("epoch", sat_dim), data)
            if coord in ds:
                result_ds[coord].attrs = ds[coord].attrs

        for vel, data in vels.items():
            result_ds[vel] = (("epoch", sat_dim), data)
            if vel in ds:
                result_ds[vel].attrs = ds[vel].attrs

        return result_ds

    def _interpolate_sat(
        self,
        ds: xr.Dataset,
        sat: str,
        sat_dim: str,
        t_source: np.ndarray,
        t_target: np.ndarray,
        idx: int,
        coords: dict[str, np.ndarray],
        vels: dict[str, np.ndarray],
    ) -> None:
        """Interpolate a single satellite using Hermite splines.

        Parameters
        ----------
        ds : xr.Dataset
            Source dataset.
        sat : str
            Satellite identifier.
        sat_dim : str
            Dimension name for satellites ("sv" or "sid").
        t_source : np.ndarray
            Source epochs in seconds from start.
        t_target : np.ndarray
            Target epochs in seconds from start.
        idx : int
            Output index for this satellite.
        coords : dict[str, np.ndarray]
            Output position arrays to fill.
        vels : dict[str, np.ndarray]
            Output velocity arrays to fill.
        """
        step = float(np.median(np.diff(t_source))) if len(t_source) > 1 else 0.0
        for coord, vel in [("X", "Vx"), ("Y", "Vy"), ("Z", "Vz")]:
            # Select by satellite dimension name
            pos = ds[coord].sel({sat_dim: sat}).values
            vel_data = ds[vel].sel({sat_dim: sat}).values
            coords[coord][:, idx] = np.nan
            if vels is not None:
                vels[vel][:, idx] = np.nan

            # The spline is fitted on the epochs with data only (a satellite
            # can be missing from part of a file, or from one of the joined
            # days, see AuxFile.join_days)
            ok = np.isfinite(pos) & np.isfinite(vel_data)
            if ok.sum() < 2:
                continue
            t_ok = t_source[ok]

            # Hermite cubic spline interpolation; no value where the
            # satellite has no data around the target: outside its epochs
            # (no extrapolation) or in a gap wider than 1.5 steps
            interpolator = CubicHermiteSpline(t_ok, pos[ok], vel_data[ok])
            right = np.clip(np.searchsorted(t_ok, t_target), 1, len(t_ok) - 1)
            bracket = t_ok[right] - t_ok[right - 1]
            covered = (
                (t_target >= t_ok[0]) & (t_target <= t_ok[-1]) & (bracket <= 1.5 * step)
            )
            coords[coord][covered, idx] = interpolator(t_target[covered])
            if vels is not None:
                vels[vel][covered, idx] = interpolator.derivative()(t_target[covered])

    def _interpolate_positions_only(
        self, ds: xr.Dataset, target_epochs: np.ndarray
    ) -> xr.Dataset:
        """Fallback: simple linear interpolation for positions only."""
        return ds.interp(
            epoch=target_epochs,
            method=self.config.fallback_method,  # ty: ignore[invalid-argument-type]
        )


@dataclass(config=ConfigDict(arbitrary_types_allowed=True))
class ClockInterpolationStrategy(Interpolator):
    """Piecewise linear interpolation for clock corrections.

    Detects and handles discontinuities (clock jumps) properly.

    Examples
    --------
    >>> from canvod.auxiliary.interpolation import (
    ...     ClockInterpolationStrategy, ClockConfig,
    ... )
    >>>
    >>> config = ClockConfig(window_size=9, jump_threshold=1e-6)
    >>> interpolator = ClockInterpolationStrategy(config=config)
    >>>
    >>> # Interpolate to RINEX epochs
    >>> clk_interp = interpolator.interpolate(clk_data, rinex_epochs)
    """

    config: ClockConfig

    def interpolate(self, ds: xr.Dataset, target_epochs: np.ndarray) -> xr.Dataset:
        """Interpolate clock corrections with discontinuity handling."""
        # Determine satellite dimension (sv or sid)
        sat_dim = "sv" if "sv" in ds.dims else "sid"
        sat_values = ds[sat_dim].values

        result_ds = xr.Dataset(coords={"epoch": target_epochs, sat_dim: sat_values})

        # Convert epochs to seconds
        t_source = (
            (ds["epoch"] - ds["epoch"].values[0])
            .values.astype("timedelta64[s]")
            .astype(float)
        )

        t_target = (
            (target_epochs - ds["epoch"].values[0])
            .astype("timedelta64[s]")
            .astype(float)
        )

        # Find clock variables
        clock_vars = [
            var
            for var in ds.data_vars
            if isinstance(var, str)
            and any(c in var for c in ["clock", "clk", "Clock", "CLK", "clock_offset"])
        ]

        if not clock_vars:
            raise ValueError("No clock variables found in dataset")

        # Process each clock variable
        for var in clock_vars:
            data = ds[var].values
            output = np.full((len(target_epochs), len(sat_values)), np.nan)

            # Parallel processing per satellite
            with ThreadPoolExecutor() as executor:
                futures = []
                for sat_idx in range(len(sat_values)):
                    futures.append(
                        executor.submit(
                            self._interpolate_sat_clock,
                            data[:, sat_idx],
                            t_source,
                            t_target,
                            self.config.jump_threshold,
                            self.config.window_size,
                        )
                    )

                # Collect results
                for sat_idx, future in enumerate(futures):
                    output[:, sat_idx] = future.result()

            result_ds[var] = (("epoch", sat_dim), output)
            if var in ds:
                result_ds[var].attrs = ds[var].attrs

        return result_ds

    def _interpolate_sat_clock(
        self,
        data: np.ndarray,
        t_source: np.ndarray,
        t_target: np.ndarray,
        threshold: float,
        window_size: int,
    ) -> np.ndarray:
        """Interpolate clock data for a single satellite.

        Handles discontinuities by splitting into segments.

        Parameters
        ----------
        data : np.ndarray
            Source clock data for one satellite.
        t_source : np.ndarray
            Source epochs in seconds from start.
        t_target : np.ndarray
            Target epochs in seconds from start.
        threshold : float
            Jump threshold for discontinuity detection.
        window_size : int
            Window size for discontinuity detection — see :func:`_detect_jumps`.

        Returns
        -------
        np.ndarray
            Interpolated values aligned to `t_target`.
        """
        output = np.full_like(t_target, np.nan)

        # Skip if all data is NaN
        if np.all(np.isnan(data)):
            return output

        # Find valid data points
        valid_mask = ~np.isnan(data)
        if not np.any(valid_mask):
            return output

        valid_data = data[valid_mask]
        valid_time = t_source[valid_mask]

        # Detect discontinuities (clock jumps)
        jumps = _detect_jumps(valid_data, window_size, threshold)
        segments = np.split(np.arange(len(valid_time)), jumps + 1)

        # Interpolate each continuous segment
        for seg in segments:
            if len(seg) < 2:
                continue

            seg_time = valid_time[seg]
            seg_data = valid_data[seg]

            # Find target points in this segment
            mask = (t_target >= seg_time[0]) & (t_target <= seg_time[-1])
            if not np.any(mask):
                continue

            # Linear interpolation within segment
            interpolator = interp1d(
                seg_time, seg_data, bounds_error=False, fill_value=np.nan
            )
            output[mask] = interpolator(t_target[mask])

        return output


def create_interpolator_from_attrs(attrs: dict[str, Any]) -> Interpolator:
    """Recreate interpolator instance from dataset attributes.

    Parameters
    ----------
    attrs : dict
        Dataset attributes containing interpolator_config.

    Returns
    -------
    Interpolator
        Reconstructed interpolator instance.

    Examples
    --------
    >>> # Save interpolator config in dataset
    >>> ds.attrs['interpolator_config'] = interpolator.to_attrs()
    >>>
    >>> # Later, recreate interpolator
    >>> interpolator = create_interpolator_from_attrs(ds.attrs)
    """
    interpolator_type = attrs["interpolator_config"]["interpolator_type"]
    config_dict = attrs["interpolator_config"]["config"]

    if interpolator_type == "Sp3InterpolationStrategy":
        config = Sp3Config(**config_dict)
        return Sp3InterpolationStrategy(config=config)
    elif interpolator_type == "ClockInterpolationStrategy":
        config = ClockConfig(**config_dict)
        return ClockInterpolationStrategy(config=config)
    else:
        raise ValueError(f"Unknown interpolator type: {interpolator_type}")
