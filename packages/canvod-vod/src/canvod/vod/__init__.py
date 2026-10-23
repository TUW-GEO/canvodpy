"""canvod-vod: VOD calculation for GNSS vegetation analysis.

This package provides VOD calculation algorithms based on the Tau-Omega model.
"""

from importlib.metadata import version as _version

from canvod.vod.calculator import TauOmegaZerothOrder, VODCalculator

__version__ = _version("canvod-vod")

__all__ = [
    "TauOmegaZerothOrder",
    "VODCalculator",
]
