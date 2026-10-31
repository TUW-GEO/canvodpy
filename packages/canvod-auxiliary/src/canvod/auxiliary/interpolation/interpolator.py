"""Interpolation strategies for GNSS auxiliary data.

Provides specialized interpolation for:
- SP3 ephemeris: polynomial of degree 10 through the 11 nearest epochs
- CLK clock: Piecewise linear with discontinuity detection
"""

from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import numpy as np
import xarray as xr
from canvod.utils.tools import deprecated_argument
from pydantic import ConfigDict
from pydantic.dataclasses import dataclass
from scipy.interpolate import interp1d

#: Epochs of an orbit product each interpolated position is computed from:
#: a polynomial of degree 10, as RTKLIB interpolates precise ephemerides
#: (RTKLIB 2.4.2 p13, src/preceph.c, ``pephpos``, ``NMAX``).
ORBIT_INTERPOLATION_POINTS = 11


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


class Sp3Config(InterpolatorConfig):
    """Configuration for SP3 ephemeris interpolation.

    The orbits are interpolated with a polynomial of degree 10 through the
    11 nearest epochs (:data:`ORBIT_INTERPOLATION_POINTS`); nothing about
    it is configurable.
    """

    @deprecated_argument(
        "use_velocities",
        "The 'use_velocities' argument of Sp3Config is left over from "
        "development and will be removed with the next major version. The "
        "orbits are interpolated from the positions alone. Remove the argument.",
    )
    @deprecated_argument(
        "fallback_method",
        "The 'fallback_method' argument of Sp3Config is left over from "
        "development and will be removed with the next major version. The "
        "orbits are interpolated from the positions alone. Remove the argument.",
    )
    def __init__(
        self, use_velocities: bool | None = None, fallback_method: str | None = None
    ) -> None:
        self.use_velocities = use_velocities
        self.fallback_method = fallback_method

    def to_dict(self) -> dict[str, Any]:
        """Convert config to dictionary for attrs storage."""
        return {"method": "lagrange", "points": ORBIT_INTERPOLATION_POINTS}


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
class Interpolator[C: InterpolatorConfig](ABC):
    """Abstract base class for interpolation strategies.

    Notes
    -----
    This is a Pydantic dataclass with `arbitrary_types_allowed=True` and
    uses `ABC` to define required interpolation hooks.
    """

    config: C

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
class Sp3InterpolationStrategy(Interpolator[Sp3Config]):
    """Polynomial interpolation of SP3 ephemeris data.

    Each position is interpolated with the Lagrange polynomial of degree 10
    through the 11 nearest epochs of the satellite
    (:data:`ORBIT_INTERPOLATION_POINTS`), as RTKLIB interpolates precise
    ephemerides (RTKLIB 2.4.2 p13, src/preceph.c, ``pephpos``). The velocities
    (``Vx``, ``Vy``, ``Vz``) are the derivative of the same polynomial.

    Examples
    --------
    >>> from canvod.auxiliary.interpolation import Sp3InterpolationStrategy, Sp3Config
    >>>
    >>> interpolator = Sp3InterpolationStrategy(config=Sp3Config())
    >>>
    >>> # Interpolate to RINEX epochs
    >>> sp3_interp = interpolator.interpolate(sp3_data, rinex_epochs)
    """

    def interpolate(self, ds: xr.Dataset, target_epochs: np.ndarray) -> xr.Dataset:
        """Interpolate SP3 ephemeris to target epochs."""
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
            (np.asarray(target_epochs) - ds["epoch"].values[0])
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
        """Interpolate a single satellite with the Lagrange polynomial.

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
        pos = np.stack([ds[c].sel({sat_dim: sat}).values for c in "XYZ"], axis=-1)
        for coord, vel in [("X", "Vx"), ("Y", "Vy"), ("Z", "Vz")]:
            coords[coord][:, idx] = np.nan
            vels[vel][:, idx] = np.nan

        # The polynomial goes through the epochs with data only (a satellite
        # can be missing from part of a file, or from one of the joined
        # days, see AuxFile.join_days)
        ok = np.isfinite(pos).all(axis=1)
        if ok.sum() < 2:
            return
        t_ok = t_source[ok]

        # No value where the satellite has no data around the target:
        # outside its epochs (no extrapolation) or in a gap wider than
        # 1.5 steps
        right = np.clip(np.searchsorted(t_ok, t_target), 1, len(t_ok) - 1)
        bracket = t_ok[right] - t_ok[right - 1]
        covered = (
            (t_target >= t_ok[0]) & (t_target <= t_ok[-1]) & (bracket <= 1.5 * step)
        )
        value, rate = _lagrange(t_ok, pos[ok], t_target[covered])
        for k, (coord, vel) in enumerate([("X", "Vx"), ("Y", "Vy"), ("Z", "Vz")]):
            coords[coord][covered, idx] = value[:, k]
            vels[vel][covered, idx] = rate[:, k]


def _lagrange(
    t_nodes: np.ndarray,
    y_nodes: np.ndarray,
    t_query: np.ndarray,
    n_points: int = ORBIT_INTERPOLATION_POINTS,
) -> tuple[np.ndarray, np.ndarray]:
    """Lagrange polynomial through the nearest nodes, and its derivative.

    Each query point gets the polynomial through the ``n_points`` nodes
    around it (fewer if there are fewer nodes): centered where possible,
    shifted inward at the ends of the nodes. The basis polynomials and
    their derivatives come from the barycentric weights of each window
    (Berrut and Trefethen 2004, Barycentric Lagrange Interpolation, SIAM
    Review 46(3), 501-517, doi:10.1137/S0036144502417715: weights eq. 3.2,
    basis eq. 3.3, derivatives at a node eqs. 9.4 and 9.5).

    Parameters
    ----------
    t_nodes : np.ndarray
        Node times (s), strictly increasing.
    y_nodes : np.ndarray
        Node values, shape ``(len(t_nodes), n_components)``.
    t_query : np.ndarray
        Query times (s).
    n_points : int
        Nodes per polynomial (its degree plus one).

    Returns
    -------
    tuple[np.ndarray, np.ndarray]
        Values and derivatives, each shape ``(len(t_query), n_components)``.
    """
    n = min(n_points, len(t_nodes))
    start = np.clip(np.searchsorted(t_nodes, t_query) - n // 2, 0, len(t_nodes) - n)
    window = start[:, None] + np.arange(n)
    # Barycentric weights w_k = 1 / prod_{m != k} (x_k - x_m), once per window
    starts, inverse = np.unique(start, return_inverse=True)
    x_win = t_nodes[starts[:, None] + np.arange(n)]
    diff = x_win[:, :, None] - x_win[:, None, :]
    off_diagonal = ~np.eye(n, dtype=bool)
    w = 1.0 / np.where(off_diagonal, diff, 1.0).prod(axis=2)
    w, x = w[inverse], x_win[inverse]  # (Q, n)

    # l_k(q) = w_k * prod_{m != k} (q - x_m), from prefix and suffix
    # products, so it holds at a node too
    d = t_query[:, None] - x
    ones = np.ones_like(d[:, :1])
    prefix = np.cumprod(np.concatenate([ones, d[:, :-1]], axis=1), axis=1)
    suffix = np.cumprod(np.concatenate([ones, d[:, :0:-1]], axis=1), axis=1)[:, ::-1]
    basis = w * prefix * suffix

    # l_k'(q) = l_k(q) * sum_{m != k} 1 / (q - x_m) away from the nodes; at a
    # node x_i: l_k'(x_i) = (w_k / w_i) / (x_i - x_k) for k != i (eq. 9.4),
    # and l_i'(x_i) = -sum_{k != i} l_k'(x_i) (eq. 9.5)
    at_node = d == 0.0
    hit = at_node.any(axis=1)
    rate_basis = np.empty_like(basis)
    free = ~hit
    inv_d = 1.0 / d[free]
    rate_basis[free] = basis[free] * (inv_d.sum(axis=1, keepdims=True) - inv_d)
    if hit.any():
        i = np.argmax(at_node[hit], axis=1)
        rows = np.arange(len(i))
        x_h, w_h = x[hit], w[hit]
        x_i, w_i = x_h[rows, i][:, None], w_h[rows, i][:, None]
        with np.errstate(divide="ignore"):
            other = (w_h / w_i) / (x_i - x_h)
        other[rows, i] = 0.0
        other[rows, i] = -other.sum(axis=1)
        rate_basis[hit] = other

    y = y_nodes[window]  # (Q, n, c)
    return (
        np.einsum("qn,qnc->qc", basis, y),
        np.einsum("qn,qnc->qc", rate_basis, y),
    )


@dataclass(config=ConfigDict(arbitrary_types_allowed=True))
class ClockInterpolationStrategy(Interpolator[ClockConfig]):
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
            (np.asarray(target_epochs) - ds["epoch"].values[0])
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
        # Nothing about the orbit interpolation is configurable; the
        # settings of stores written before v1.1.0 are not passed on
        return Sp3InterpolationStrategy(config=Sp3Config())
    elif interpolator_type == "ClockInterpolationStrategy":
        config = ClockConfig(**config_dict)
        return ClockInterpolationStrategy(config=config)
    else:
        raise ValueError(f"Unknown interpolator type: {interpolator_type}")
