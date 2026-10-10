# Interpolation methods

SP3 orbits come every 5 or 15 minutes and CLK clocks every 30 s or 5
minutes; observations come every 1 to 30 s. canvod-auxiliary interpolates
one day of orbits and clocks onto a regular grid that starts at 00:00 and
has the sampling interval of the observations
(`canvod.auxiliary.interpolation.interpolate_aux_day`). Each observation
epoch then takes the nearest grid epoch. `canvodpy run`, the ephemeris
provider of the Python API and the Airflow tasks all use these functions.

<div class="grid cards" markdown>

-   :fontawesome-solid-wave-square: &nbsp; **Cubic Hermite spline**

    ---

    Used for **SP3 orbits** (satellite X, Y, Z).

    The spline matches the positions and the satellite velocities at
    every SP3 epoch.

-   :fontawesome-solid-chart-line: &nbsp; **Piecewise linear**

    ---

    Used for **CLK clock offsets**.

    Linear between neighboring clock epochs, never across a detected
    clock jump.

</div>

---

## Cubic Hermite spline (orbits)

Orbital motion is smooth, so a cubic polynomial between two SP3 epochs
fits it well. A Hermite spline fixes each polynomial by the positions and
velocities at both ends of the interval
([`scipy.interpolate.CubicHermiteSpline`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.interpolate.CubicHermiteSpline.html)).

SP3 files read by canVODpy provide positions only. The SP3 reader
(`Sp3File`, `add_velocities=True` by default) estimates the velocities
from the positions by central differences (forward and backward
differences at the first and last epoch); a run computes them on the day
joined with its neighbors (see below), so the day's own first and last
epochs get central differences too.

```python
from canvod.auxiliary.interpolation import Sp3Config, Sp3InterpolationStrategy

config = Sp3Config(
    use_velocities=True,  # Hermite spline with Vx, Vy, Vz
    fallback_method="linear",  # used when the dataset has no velocities
)

interpolator = Sp3InterpolationStrategy(config=config)
result = interpolator.interpolate(sp3_data, target_epochs)
```

| Parameter | Default | Effect |
|-----------|---------|--------|
| `use_velocities` | `True` | Hermite spline if `Vx`, `Vy`, `Vz` are in the dataset |
| `fallback_method` | `"linear"` | `xarray` interpolation method without velocities |

### Start and end of the day

A daily orbit file can end before midnight (ESA's 15-minute rapid orbits
end at 23:45; CODE's 5-minute orbits include 24:00), and the velocities of
its first and last epoch are one-sided differences. So every run loads the
orbit and clock files of the **previous and the next day** too
(`AuxDataPipeline.create_standard`), keeps one hour of each
(`AuxFile.join_days`; where files overlap, the day's own epoch is kept) and
computes the velocities on the joined data. Every epoch of the day then
lies between two orbit epochs: nothing is extrapolated. If a neighboring
day's file cannot be obtained, the run stops with an error naming it.
Final products come out per GPS week, so the last day of a week can be
processed only once the next week's products are published.

The spline is fitted per satellite on the epochs with data. A target epoch
outside a satellite's data, or in a gap of more than 1.5 sampling
intervals, is NaN.

### Accuracy

Measured on the CODE final orbits of 2025-001 (with 2024-366 and
2025-002), by leaving orbit epochs out and interpolating them from the
rest; the angle is the largest direction error seen from the ground:

| Orbit sampling | Largest position error | Largest angle error |
|---|---|---|
| 10 min (positions at the 5-min epochs in between) | 81 m | $0.0002^\circ$ |
| 15 min | 1.1 km | $0.004^\circ$ |

With the day's file alone (before the neighbors were loaded), the first
and last interval of the day were off by up to 37 km ($0.11^\circ$), and a
15-minute file ending at 23:45 was extrapolated by up to 990 km ($2.9^\circ$).

---

## Piecewise linear (clocks)

Satellite clock offsets can jump. Linear interpolation between
neighboring CLK epochs, split at each jump, avoids fitting across one.

```python
from canvod.auxiliary.interpolation import ClockConfig, ClockInterpolationStrategy

config = ClockConfig(
    window_size=9,  # epochs averaged on each side of a candidate jump
    jump_threshold=1e-6,  # jump detection threshold (seconds)
)

interpolator = ClockInterpolationStrategy(config=config)
result = interpolator.interpolate(clk_data, target_epochs)
```

!!! warning "Jump detection"
    For each gap between consecutive CLK epochs, the interpolator compares
    the mean of up to `window_size` epochs before the gap with the mean of
    up to `window_size` epochs after it. Where the difference exceeds
    `jump_threshold`, the gap is a jump (for a run of flagged gaps, only the
    one with the largest difference). The series is split at each jump and
    interpolated linearly within each segment, never across a jump. Target
    epochs inside a jump gap, outside the data, or in a segment of a single
    epoch are NaN. `window_size=1` compares the two neighboring epochs only.

The strategy interpolates every data variable whose name contains
`clock`, `clk`, `Clock` or `CLK`, and raises `ValueError` if there is none.

---

## Recorded in the data

`interpolate_aux_day` writes the class and settings of each strategy to
the interpolated orbits and clocks (`attrs["interpolator_config"]`, from
`Interpolator.to_attrs()`), and
`create_interpolator_from_attrs()` rebuilds the interpolator from these
attributes.

---

## Custom strategies

Subclass `Interpolator` to write your own interpolation:

```python
import numpy as np
import xarray as xr
from canvod.auxiliary.interpolation import Interpolator


class CustomStrategy(Interpolator):
    """Example: Lagrange polynomial interpolation."""

    def interpolate(
        self,
        ds: xr.Dataset,
        target_epochs: np.ndarray,
    ) -> xr.Dataset:
        # Your implementation here
        return interpolated_ds
```

`canvodpy run` always uses `Sp3InterpolationStrategy` and
`ClockInterpolationStrategy`; a custom strategy is for your own scripts.
