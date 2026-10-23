"""Deprecated location of :mod:`canvod.utils.logging.run_context`.

Using a name from here warns; the names are those of the new location.
"""

import importlib
import warnings
from typing import Any

_new = importlib.import_module("canvod.utils.logging.run_context")

_NAMES = ("RUN_ID", "get_run_id", "reset_run_id", "set_run_id")


def __getattr__(name: str) -> Any:
    if name not in _NAMES:
        msg = f"module {__name__!r} has no attribute {name!r}"
        raise AttributeError(msg)
    warnings.warn(
        "canvodpy.logging.run_context is left over from development and will be "
        "removed with the next major version. Use canvod.utils.logging.run_context "
        "instead.",
        FutureWarning,
        stacklevel=2,
    )
    return getattr(_new, name)
