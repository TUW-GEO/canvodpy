"""Shared retry-with-backoff wrapper for Icechunk store I/O.

``icechunk.IcechunkError`` wraps object-store errors -- including transient
network drops on shared/mounted storage (os error 103 ECONNABORTED, seen in
production against an NFS-style share) -- but is not a subclass of OSError/RuntimeError/ValueError, so it
escapes a plain ``except (OSError, RuntimeError, ValueError)`` uncaught.
Used by both the RINEX ingest path (``orchestrator/pipeline.py``) and the
VOD store write path (``cli/run.py``) -- both hit the same store, over the
same network mount, so both need the same retry treatment.
"""

from __future__ import annotations

import time as _time
from collections.abc import Callable

import icechunk

STORE_ERROR_TYPES = (OSError, RuntimeError, ValueError, icechunk.IcechunkError)
# Only these can be transient (a dropped connection). A ValueError or
# RuntimeError (e.g. a dataset that fails validation) fails the same way on
# every attempt, so it propagates at once instead of after the backoff.
RETRYABLE_STORE_ERRORS = (OSError, icechunk.IcechunkError)
# CIFS's default dead-connection-detection interval (echo_interval) is 60s --
# a (2, 8, 30) schedule (40s total) can exhaust every retry before the OS-level
# driver has even noticed the connection dropped, so every attempt would hit
# the same still-broken connection. This is general CIFS behavior, not a
# confirmed incident: no captured production log corroborates a specific
# "N consecutive os error 103" sequence for this exact schedule as of
# 2026-07-17. Widened as a precautionary default so the total window
# comfortably outlasts CIFS's reconnect timescale; revisit if real
# store_op_retry log data becomes available.
STORE_RETRY_BACKOFF_SECONDS = (5.0, 15.0, 45.0, 90.0)


def call_with_store_retries[T](fn: Callable[[], T], *, logger, **log_ctx: object) -> T:
    """Retry a store read/write with backoff before giving up.

    Only errors in ``RETRYABLE_STORE_ERRORS`` are retried; any other error
    propagates at once. The final attempt is unguarded -- its exception propagates to the
    caller's own ``except``/``log.exception`` so existing log event names
    and give-up behavior are unchanged; this only adds retries in front of
    that.
    """
    for attempt, backoff in enumerate(STORE_RETRY_BACKOFF_SECONDS):
        try:
            return fn()
        except RETRYABLE_STORE_ERRORS as exc:
            logger.warning(
                "store_op_retry",
                attempt=attempt + 1,
                backoff_seconds=backoff,
                error=str(exc),
                **log_ctx,
            )
            _time.sleep(backoff)
    return fn()
