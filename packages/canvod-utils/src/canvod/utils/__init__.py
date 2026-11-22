"""Utility functions for canvodpy."""

from ._meta import __version__

# Submodules are imported on demand to avoid circular imports
# Use: from canvod.utils.tools import YYYYDOY, canvodpy_version

__all__ = [
    "__version__",
    "tools",
]
