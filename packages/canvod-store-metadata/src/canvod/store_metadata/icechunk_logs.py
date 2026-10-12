"""Which Icechunk warnings canVODpy shows.

Two Icechunk warnings that don't apply to canVODpy's stores are hidden;
every other Icechunk warning is shown. ``ICECHUNK_LOG``, when set,
replaces this filter.

- icechunk_arrow_object_store, on every store opened: the local file system
  is not safe for concurrent commits. canVODpy runs every commit under
  ``commit_lock``.
- icechunk_storage::readback, once per process: without
  ``unsafe_use_metadata``, a lost reply to a conditional write may surface
  as a spurious conflict. Icechunk's local file system storage can't store
  that metadata (it refuses ``unsafe_use_metadata=True``) and makes one try
  per write, so no reply is lost and retried.
"""

from __future__ import annotations

import os

import icechunk

#: The filter set by :func:`apply_icechunk_log_filter`.
ICECHUNK_LOG_FILTER = (
    "warn,icechunk_arrow_object_store=error,icechunk_storage::readback=error"
)

_applied = False


def apply_icechunk_log_filter() -> None:
    """Set the filter once per process, unless ``ICECHUNK_LOG`` is set.

    Called on import by every package that opens stores
    (``canvod.store_metadata``, ``canvod.store``).
    """
    global _applied
    if _applied or "ICECHUNK_LOG" in os.environ:
        return
    icechunk.set_logs_filter(ICECHUNK_LOG_FILTER)
    _applied = True
