"""Interpolation strategies for GNSS auxiliary data."""

from canvod.auxiliary.interpolation.day_grid import (
    aux_epoch_grid,
    interpolate_aux_day,
    sampling_interval_from_epochs,
)
from canvod.auxiliary.interpolation.interpolator import (
    ClockConfig,
    ClockInterpolationStrategy,
    Interpolator,
    InterpolatorConfig,
    Sp3Config,
    Sp3InterpolationStrategy,
    create_interpolator_from_attrs,
)

__all__ = [
    "ClockConfig",
    "ClockInterpolationStrategy",
    "Interpolator",
    "InterpolatorConfig",
    "Sp3Config",
    "Sp3InterpolationStrategy",
    "aux_epoch_grid",
    "create_interpolator_from_attrs",
    "interpolate_aux_day",
    "sampling_interval_from_epochs",
]
