"""Deprecated location of :mod:`canvod.utils.logging.stage_timer`.

Using a name from here warns; the names are those of the new location.
"""

import importlib
import warnings
from typing import Any

_new = importlib.import_module("canvod.utils.logging.stage_timer")

_NAMES = ("emit_run_summary", "reset_run_stats", "stage_timer", "timed_stage")


def __getattr__(name: str) -> Any:
    if name not in _NAMES:
        msg = f"module {__name__!r} has no attribute {name!r}"
        raise AttributeError(msg)
    warnings.warn(
        "canvodpy.logging.stage_timer is left over from development and will be "
        "removed with the next major version. Use canvod.utils.logging.stage_timer "
        "instead.",
        FutureWarning,
        stacklevel=2,
    )
    return getattr(_new, name)
