# Interpolation Methods

SP3 and CLK products sample at 15-minute or 5-minute intervals. RINEX observations arrive at 1–30 s. Interpolation bridges the gap — producing per-epoch satellite positions and clock corrections at the exact observation timestamps.

<div class="grid cards" markdown>

-   :fontawesome-solid-wave-square: &nbsp; **Hermite Cubic Splines**

    ---

    Used for **SP3 ephemerides** (satellite XYZ positions).

    SP3 files include both positions *and* velocities, enabling Hermite
    interpolation — C¹ continuous, sub-millimetre accuracy for IGS final products.

-   :fontawesome-solid-chart-line: &nbsp; **Piecewise Linear**

    ---

    Used for **CLK clock corrections**.

    Clock files provide no derivative information and exhibit discontinuities
    at manoeuvre events. Linear segments between knot points give
    sub-nanosecond accuracy without over-fitting.

</div>

---

## Hermite Cubic Splines (Ephemerides)

Physical motivation: orbital motion is smooth — well-suited to polynomial interpolation. Positions and velocities from SP3 files determine the Hermite polynomial coefficients uniquely over each 15-minute interval.

```python
from canvod.auxiliary.interpolation import Sp3Config, Sp3InterpolationStrategy

config = Sp3Config(
    use_velocities=True,          # use velocity columns from SP3 (recommended)
    fallback_method="linear",     # fall back if velocity missing
    extrapolation_method="nearest",
)

interpolator = Sp3InterpolationStrategy(config=config)
result = interpolator.interpolate(sp3_data, target_epochs)
```

| Parameter | Default | Effect |
|-----------|---------|--------|
| `use_velocities` | `True` | Enables Hermite mode (higher accuracy) |
| `fallback_method` | `"linear"` | Used when velocity columns absent |
| `extrapolation_method` | `"nearest"` | Behaviour outside the SP3 time span |

!!! success "Accuracy"
    Hermite splines achieve **< 1 mm** position error at 30 s cadence
    for IGS final products. Rapid products are typically < 5 mm.

---

## Piecewise Linear Interpolation (Clock Corrections)

Clock corrections are **not** smooth — receiver and satellite clock models are periodically updated, causing step discontinuities. Linear interpolation between adjacent CLK knots avoids fitting across those jumps.

```python
from canvod.auxiliary.interpolation import ClockConfig, ClockInterpolationStrategy

config = ClockConfig(
    window_size=9,          # number of knots to fit (odd, centred)
    jump_threshold=1e-6,    # discontinuity detection threshold (seconds)
    extrapolation="nearest",
)

interpolator = ClockInterpolationStrategy(config=config)
result = interpolator.interpolate(clk_data, target_epochs)
```

!!! warning "Jump detection"
    When `|Δt| > jump_threshold` between consecutive CLK knots, the
    interpolator treats the gap as a boundary and never interpolates
    across it. The nearest valid knot value is used instead.

---

## Custom Strategies

Implement `InterpolationStrategy` to plug in custom interpolation logic:

```python
from canvod.auxiliary.interpolation import InterpolationStrategy
import xarray as xr

class CustomStrategy(InterpolationStrategy):
    """Example: Lagrange polynomial interpolation."""

    def interpolate(
        self,
        aux_ds: xr.Dataset,
        target_epochs: xr.DataArray,
    ) -> xr.Dataset:
        # Your implementation here
        return interpolated_ds
```

The strategy is injected into the auxiliary pipeline — no other changes required.

---

## Accuracy Summary

| Data | Method | Expected accuracy | Notes |
|------|--------|------------------|-------|
| SP3 final (IGS) | Hermite | < 1 mm | Requires velocity columns |
| SP3 rapid (IGS) | Hermite | < 5 mm | Typically available within 17 h |
| SP3 ultra-rapid | Hermite | few cm | Predicted half |
| CLK final | Linear | < 0.1 ns | Sub-centimetre equivalent |
| CLK rapid | Linear | ~0.5 ns | Typically available within 17 h |

---

!!! example "Try it"
    [08 · Ephemeris & Coordinates](../../notebooks/_build/08_ephemeris_coordinates.html){target=_blank}
    · [view source on molab](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/08_ephemeris_coordinates.py)
