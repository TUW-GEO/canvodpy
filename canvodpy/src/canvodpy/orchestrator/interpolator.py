"""Interpolation strategies for auxiliary datasets.

.. deprecated::
    Left over from development and removed with the next major version.
    The interpolation strategies live in ``canvod.auxiliary.interpolation``;
    the names here are subclasses of those without any logic of their own,
    so both give identical results.
"""

from typing import Any

from canvod.auxiliary import interpolation as _aux
from canvod.utils.tools import deprecated

MIN_SEGMENT_LEN = 2


def _message(name: str) -> str:
    return (
        f"canvodpy.orchestrator.interpolator.{name} is left over from "
        "development and will be removed with the next major version. Use "
        f"canvod.auxiliary.interpolation.{name} instead."
    )


@deprecated(_message("InterpolatorConfig"))
class InterpolatorConfig(_aux.InterpolatorConfig):
    """Deprecated, use ``canvod.auxiliary.interpolation.InterpolatorConfig``."""


@deprecated(_message("Sp3Config"))
class Sp3Config(_aux.Sp3Config):
    """Deprecated, use ``canvod.auxiliary.interpolation.Sp3Config``."""


@deprecated(_message("ClockConfig"))
class ClockConfig(_aux.ClockConfig):
    """Deprecated, use ``canvod.auxiliary.interpolation.ClockConfig``."""


@deprecated(_message("Interpolator"))
class Interpolator(_aux.Interpolator):
    """Deprecated, use ``canvod.auxiliary.interpolation.Interpolator``."""


@deprecated(_message("ClockInterpolationStrategy"))
class ClockInterpolationStrategy(_aux.ClockInterpolationStrategy):
    """Deprecated, use ``canvod.auxiliary.interpolation.ClockInterpolationStrategy``."""


@deprecated(_message("Sp3InterpolationStrategy"))
class Sp3InterpolationStrategy(_aux.Sp3InterpolationStrategy):
    """Deprecated, use ``canvod.auxiliary.interpolation.Sp3InterpolationStrategy``."""


@deprecated(_message("create_interpolator_from_attrs"))
def create_interpolator_from_attrs(attrs: dict[str, Any]) -> _aux.Interpolator:
    """Deprecated, use ``canvod.auxiliary.interpolation.create_interpolator_from_attrs``."""
    return _aux.create_interpolator_from_attrs(attrs)
