"""
Utility tools for canVODpy packages.

This module provides common utilities used across all canVODpy packages:
- Version management
- Date/time utilities for GNSS data
- Validation helpers
- File hashing
- Deprecation warnings

Examples
--------
>>> from canvod.utils.tools import get_version_from_pyproject
>>> version = get_version_from_pyproject()

>>> from canvod.utils.tools import YYYYDOY
>>> date = YYYYDOY.from_str("2025024")
>>> print(date.to_datetime())

>>> from canvod.utils.tools import gpsweekday
>>> week, day = gpsweekday("15-01-2025")  # dd-mm-yyyy

>>> from canvod.utils.tools import isfloat
>>> isfloat("3.14")  # True

>>> from canvod.utils.tools import sanitize_directory
>>> sanitize_directory(store_path)  # removes stray .DS_Store files

>>> from canvod.utils.tools import deprecated
>>> @deprecated("Use new_function instead.")
... def old_function(): ...
"""

from .date_utils import YYDOY, YYYYDOY, get_gps_week_from_filename
from .deprecation import deprecated, deprecated_argument
from .hashing import bytes_hash, file_hash
from .sanitize import sanitize_directory
from .validation import isfloat
from .version import get_version_from_pyproject
from .worker import _worker_init

# Backwards compatibility: gpsweekday is now a static method on YYYYDOY
# Provide as standalone function for backwards compatibility
gpsweekday = YYYYDOY.gpsweekday

__all__ = [
    "YYDOY",
    "YYYYDOY",
    "_worker_init",
    "bytes_hash",
    "deprecated",
    "deprecated_argument",
    "file_hash",
    "get_gps_week_from_filename",
    "get_version_from_pyproject",
    "gpsweekday",
    "isfloat",
    "sanitize_directory",
]
