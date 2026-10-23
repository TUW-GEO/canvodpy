"""The day's epoch grid and the interpolation onto it (shared by all paths)."""

import numpy as np
import pytest
import xarray as xr

from canvod.auxiliary.interpolation import (
    aux_epoch_grid,
    interpolate_aux_day,
    sampling_interval_from_epochs,
)

DAY = np.datetime64("2025-01-01")
NEXT_DAY = np.datetime64("2025-01-02T00:00:00", "ns")


def _epochs(seconds) -> np.ndarray:
    return np.datetime64("2025-01-01T10:00:00", "ns") + np.array(
        [round(s * 1e9) for s in seconds], dtype="timedelta64[ns]"
    )


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        ([0, 5, 10, 15], 5.0),
        ([0, 5, 10, 300, 305, 310], 5.0),  # a data gap does not count
        ([0, 0.2, 0.4, 0.6], 0.2),
        ([0, 30, 30, 60], 30.0),  # repeated epoch ignored
    ],
)
def test_sampling_interval_is_the_most_common_step(seconds, expected):
    assert sampling_interval_from_epochs(_epochs(seconds)) == expected


@pytest.mark.parametrize("seconds", [[0], [0, 0]])
def test_sampling_interval_needs_two_epochs(seconds):
    with pytest.raises(ValueError, match="at least two distinct epochs"):
        sampling_interval_from_epochs(_epochs(seconds))


@pytest.mark.parametrize(
    ("interval_s", "n_epochs", "last"),
    [
        (5.0, 17_280, "2025-01-01T23:59:55"),
        (1.0, 86_400, "2025-01-01T23:59:59"),
        (30.0, 2_880, "2025-01-01T23:59:30"),
        (7.0, 12_343, "2025-01-01T23:59:54"),
        (0.2, 432_000, "2025-01-01T23:59:59.8"),
    ],
)
def test_grid_covers_the_day(interval_s, n_epochs, last):
    grid = aux_epoch_grid(DAY, interval_s)
    assert grid.dtype == np.dtype("datetime64[ns]")
    assert grid[0] == np.datetime64("2025-01-01T00:00:00", "ns")
    assert len(grid) == n_epochs
    assert grid[-1] == np.datetime64(last, "ns")
    assert grid[-1] < NEXT_DAY


@pytest.mark.parametrize("interval_s", [0.0, -5.0])
def test_grid_rejects_non_positive_interval(interval_s):
    with pytest.raises(ValueError, match="must be positive"):
        aux_epoch_grid(DAY, interval_s)


def _orbits() -> xr.Dataset:
    epochs = np.datetime64("2025-01-01T00:00:00", "ns") + np.arange(
        97
    ) * np.timedelta64(900, "s")
    t = np.arange(97, dtype=float)[:, None]
    v = np.full((97, 1), 1e3 / 900)
    return xr.Dataset(
        {
            "X": (("epoch", "sid"), 2e7 + 1e3 * t),
            "Y": (("epoch", "sid"), 1e7 + 1e3 * t),
            "Z": (("epoch", "sid"), 1.5e7 + 1e3 * t),
            "Vx": (("epoch", "sid"), v),
            "Vy": (("epoch", "sid"), v),
            "Vz": (("epoch", "sid"), v),
        },
        coords={"epoch": epochs, "sid": ["G01|L1|C"]},
    )


def _clocks() -> xr.Dataset:
    epochs = np.datetime64("2025-01-01T00:00:00", "ns") + np.arange(
        2880
    ) * np.timedelta64(30, "s")
    return xr.Dataset(
        {"clock_offset": (("epoch", "sid"), np.full((2880, 1), 1e-4))},
        coords={"epoch": epochs, "sid": ["G01|L1|C"]},
    )


def test_interpolate_aux_day_without_clock():
    grid = aux_epoch_grid(DAY, 5.0)
    aux = interpolate_aux_day(_orbits(), None, grid)
    assert set(aux.data_vars) == {"X", "Y", "Z", "Vx", "Vy", "Vz"}
    np.testing.assert_array_equal(aux["epoch"].values, grid)
    assert (
        aux.attrs["interpolator_config"]["interpolator_type"]
        == "Sp3InterpolationStrategy"
    )
    # Linear motion: the Hermite spline reproduces it exactly.
    expected_x = 2e7 + 1e3 * np.arange(17_280) / 180
    np.testing.assert_allclose(aux["X"].values[:, 0], expected_x)


def test_interpolate_aux_day_with_clock():
    aux = interpolate_aux_day(_orbits(), _clocks(), aux_epoch_grid(DAY, 5.0))
    assert "clock_offset" in aux
    np.testing.assert_allclose(aux["clock_offset"].values[:-6, 0], 1e-4)
