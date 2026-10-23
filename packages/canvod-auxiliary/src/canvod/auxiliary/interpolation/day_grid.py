"""Interpolate one day of SP3/CLK products onto the epoch grid of the observations.

The orbits and clocks are interpolated once per day onto a regular grid that
starts at 00:00 of the day and has the sampling interval of the observations;
each observation epoch then takes the nearest grid epoch. For observations on
that grid (the usual case) the nearest grid epoch is the observation epoch.

``canvodpy run``, the ephemeris provider of the Python API and the Airflow
tasks all build the grid and interpolate with these functions.
"""

from __future__ import annotations

import numpy as np
import xarray as xr

from canvod.auxiliary.interpolation.interpolator import (
    ClockConfig,
    ClockInterpolationStrategy,
    Sp3Config,
    Sp3InterpolationStrategy,
)

SECONDS_PER_DAY = 86_400


def sampling_interval_from_epochs(epochs: np.ndarray) -> float:
    """Sampling interval of observation epochs, in seconds.

    The most common difference between consecutive epochs, so data gaps do
    not change the result.

    Parameters
    ----------
    epochs : np.ndarray
        Observation epochs (datetime64), in time order.

    Returns
    -------
    float
        Sampling interval in seconds.

    Raises
    ------
    ValueError
        If there are fewer than two distinct epochs.
    """
    diffs = np.diff(np.asarray(epochs, dtype="datetime64[ns]")).astype(np.int64)
    diffs = diffs[diffs > 0]
    if diffs.size == 0:
        msg = "the sampling interval needs at least two distinct epochs"
        raise ValueError(msg)
    values, counts = np.unique(diffs, return_counts=True)
    return float(values[np.argmax(counts)]) / 1e9


def aux_epoch_grid(day_start: np.datetime64, interval_s: float) -> np.ndarray:
    """Epoch grid of one day: ``day_start`` plus multiples of ``interval_s``.

    Parameters
    ----------
    day_start : np.datetime64
        00:00 of the day.
    interval_s : float
        Grid spacing in seconds (the sampling interval of the observations),
        resolved to the nanosecond.

    Returns
    -------
    np.ndarray
        ``datetime64[ns]`` epochs within the day.

    Raises
    ------
    ValueError
        If ``interval_s`` is not positive.
    """
    step_ns = round(interval_s * 1e9)
    if step_ns <= 0:
        msg = f"interval_s must be positive, not {interval_s}"
        raise ValueError(msg)
    n_epochs = -(-SECONDS_PER_DAY * 1_000_000_000 // step_ns)  # ceil
    start = np.asarray(day_start).astype("datetime64[D]").astype("datetime64[ns]")
    return start + np.arange(n_epochs, dtype=np.int64) * np.timedelta64(step_ns, "ns")


def interpolate_aux_day(
    ephem_ds: xr.Dataset,
    clock_ds: xr.Dataset | None,
    target_epochs: np.ndarray,
) -> xr.Dataset:
    """Interpolate one day of orbits (and clocks) onto ``target_epochs``.

    Orbits: cubic Hermite spline with the satellite velocities
    (:class:`Sp3InterpolationStrategy`). Clocks: piecewise linear between
    clock jumps (:class:`ClockInterpolationStrategy`). Each part records its
    interpolator in ``attrs["interpolator_config"]``.

    Parameters
    ----------
    ephem_ds : xr.Dataset
        Orbits with ``X``, ``Y``, ``Z`` and ``Vx``, ``Vy``, ``Vz``.
    clock_ds : xr.Dataset | None
        Clock offsets, or ``None`` when clocks are not fetched.
    target_epochs : np.ndarray
        Epoch grid, see :func:`aux_epoch_grid`.

    Returns
    -------
    xr.Dataset
        Interpolated orbits, merged with the interpolated clocks if given.
    """
    sp3 = Sp3InterpolationStrategy(
        config=Sp3Config(use_velocities=True, fallback_method="linear")
    )
    ephem_interp = sp3.interpolate(ephem_ds, target_epochs)
    ephem_interp.attrs["interpolator_config"] = sp3.to_attrs()
    if clock_ds is None:
        return ephem_interp

    clock = ClockInterpolationStrategy(
        config=ClockConfig(window_size=9, jump_threshold=1e-6)
    )
    clock_interp = clock.interpolate(clock_ds, target_epochs)
    clock_interp.attrs["interpolator_config"] = clock.to_attrs()
    return xr.merge([ephem_interp, clock_interp])
