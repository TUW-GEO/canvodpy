# Interpolation methods

SP3 orbits come every 5 or 15 minutes and CLK clocks every 30 s or 5
minutes; observations come every 1 to 30 s. canvod-auxiliary interpolates
one day of orbits and clocks onto a regular grid that starts at 00:00 and
has the sampling interval of the observations
(`canvod.auxiliary.interpolation.interpolate_aux_day`). Each observation
epoch then takes the nearest grid epoch. `canvodpy run`, the ephemeris
provider of the Python API and the Airflow tasks all use these functions.

<div class="grid cards" markdown>

-   :fontawesome-solid-wave-square: &nbsp; **Polynomial of degree 10 or Hermite spline**

    ---

    Used for **SP3 orbits** (satellite X, Y, Z).

    By default, the polynomial through the positions at the 11 orbit
    epochs nearest to each target epoch; or, as before v1.1.0, the cubic
    Hermite spline through the positions and velocities.

-   :fontawesome-solid-chart-line: &nbsp; **Piecewise linear**

    ---

    Used for **CLK clock offsets**.

    Linear between neighboring clock epochs, never across a detected
    clock jump.

</div>

---

## Orbits

The setting `processing.aux_data.sp3_interpolation` picks the method:

| Value | Method |
|---|---|
| `lagrange` (default) | Polynomial of degree 10 through the 11 nearest orbit epochs |
| `hermite` | Cubic Hermite spline through the positions and velocities, the method of canvodpy before v1.1.0 |

Despite its name, the setting also applies to the broadcast orbits of
RINEX navigation files (see below).

### Polynomial of degree 10 (`lagrange`)

Each interpolated position comes from the Lagrange polynomial of degree
10 through the positions at the 11 orbit epochs nearest to it, as RTKLIB
interpolates precise ephemerides
([RTKLIB 2.4.2 p13](https://github.com/tomojitakasu/RTKLIB), `src/preceph.c`,
`pephpos`). The velocities `Vx`, `Vy`, `Vz` of the interpolated orbits are
the derivative of the same polynomial, both evaluated in the barycentric
form
([Barycentric Lagrange Interpolation](https://doi.org/10.1137/S0036144502417715),
SIAM Review 46(3), 2004).

The broadcast ephemeris of RINEX files goes through the same
interpolation: its orbits are first computed on a 5-minute grid (see
[Ephemeris sources](../readers/ephemeris-sources.md)).

### Hermite spline (`hermite`)

Each coordinate is interpolated with the cubic Hermite spline through the
positions and velocities at the orbit epochs (`scipy.interpolate.CubicHermiteSpline`).
SP3 files without velocities get them as central differences of the
positions (`Sp3File`). The velocities of the interpolated orbits are the
derivative of the spline. This is the code of canvodpy v1.0.0, unchanged:
a run with `hermite` gives the angles of v1.0.0.

```python
from canvod.auxiliary.interpolation import Sp3Config, Sp3InterpolationStrategy

interpolator = Sp3InterpolationStrategy(config=Sp3Config(method="hermite"))
result = interpolator.interpolate(sp3_data, target_epochs)
```

`Sp3Config()` is the default, `lagrange`. Another value raises a
`ValueError`.

### One method per store

A GNSS store records the method in its content settings, and refuses a
run with the other one (see
[content settings](../../guides/configuration.md#content-settings-fixed-for-each-store)). A store created
before v1.1.0 records none: it counts as `hermite`, the only method then.
To continue writing to such a store, set
`processing.aux_data.sp3_interpolation: hermite`; with the default, write
to a new store. The log book of a store records the method of every file
(column `orbit_interpolation`).

### Start and end of the day

A daily orbit file can end before midnight (ESA's 15-minute rapid orbits
end at 23:45; CODE's 5-minute orbits include 24:00), and near its first
and last epoch the interpolation would have orbit epochs on one side only.
So every run loads the orbit and clock files of the **previous and the
next day** too (`AuxDataPipeline.create_standard`) and keeps one hour of
each (`AuxFile.join_days`; where files overlap, the day's own epoch is
kept). Every epoch of the day then lies between two orbit epochs: nothing
is extrapolated. If a neighboring day's file cannot be obtained, the run
stops with an error naming it.
Final products come out per GPS week, so the last day of a week can be
processed only once the next week's products are published.

Either method goes through the epochs of the satellite with data. A
target epoch outside a satellite's data, or in a gap of more than 1.5
sampling intervals, is NaN.

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
    """Example: your own interpolation."""

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
