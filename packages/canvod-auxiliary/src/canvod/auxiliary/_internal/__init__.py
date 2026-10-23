"""
Internal utilities for canvod-auxiliary package.

Date utilities are imported from canvod.utils.tools (canonical location).
Units are specific to canvod-auxiliary package.
"""

# Import date utilities from canonical location
# Import aux-specific utilities
from canvod.utils.tools import YYYYDOY, get_gps_week_from_filename

from canvod.auxiliary._internal.units import SPEEDOFLIGHT, UREG

__all__ = [
    "SPEEDOFLIGHT",
    # Units
    "UREG",
    # Date utilities (re-exported from canvod.utils.tools)
    "YYYYDOY",
    "get_gps_week_from_filename",
]
