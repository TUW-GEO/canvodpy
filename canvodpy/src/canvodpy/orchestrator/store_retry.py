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

import errno
import time as _time
from collections.abc import Callable

import icechunk

from canvod.store_metadata.io import CONFLICT_TRIES, wait_after_conflict

STORE_ERROR_TYPES = (OSError, RuntimeError, ValueError, icechunk.IcechunkError)
# Only these can be transient (a dropped connection). A ValueError or
# RuntimeError (e.g. a dataset that fails validation) fails the same way on
# every attempt, so it propagates at once instead of after the backoff.
RETRYABLE_STORE_ERRORS = (OSError, icechunk.IcechunkError)
# OS errors among those that fail the same way on every attempt: a retry
# would only add the waits (and for a unit, its whole work again).
_LASTING_OS_ERRORS = (
    PermissionError,
    FileNotFoundError,
    IsADirectoryError,
    NotADirectoryError,
)
_LASTING_ERRNOS = frozenset(
    code
    for code in (
        errno.ENOSPC,
        errno.EROFS,
        getattr(errno, "EDQUOT", None),
    )
    if code is not None
)
# Windows: a file held briefly by another process (a virus scanner) gives
# a PermissionError with ERROR_SHARING_VIOLATION or ERROR_LOCK_VIOLATION.
_WINDOWS_SHARING_ERRORS = frozenset({32, 33})
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


def is_transient(exc: BaseException) -> bool:
    """Whether a store error can be transient, so trying again may succeed.

    An error in :data:`RETRYABLE_STORE_ERRORS` is, unless it is an OS error
    that lasts: no permission, a missing file or folder, a full disk or
    quota, a read-only file system. A Windows sharing or lock violation is
    a ``PermissionError`` but passes: the other process lets the file go.
    """
    if not isinstance(exc, RETRYABLE_STORE_ERRORS):
        return False
    if getattr(exc, "winerror", None) in _WINDOWS_SHARING_ERRORS:
        return True
    if isinstance(exc, _LASTING_OS_ERRORS):
        return False
    return not (isinstance(exc, OSError) and exc.errno in _LASTING_ERRNOS)


def wait_after_store_error(
    errors: int, exc: BaseException, *, logger, **log_ctx: object
) -> bool:
    """Wait before trying again after the ``errors``-th transient store error.

    For a caller that redoes more than one call after an error, such as a
    unit of days written again. Logs ``store_op_retry`` and waits as
    :func:`call_with_store_retries` does.

    Returns
    -------
    bool
        ``False`` if ``exc`` is not transient (:func:`is_transient`) or the
        retries are used up: the caller raises ``exc``.
    """
    if not is_transient(exc) or errors > len(STORE_RETRY_BACKOFF_SECONDS):
        return False
    backoff = STORE_RETRY_BACKOFF_SECONDS[errors - 1]
    logger.warning(
        "store_op_retry",
        attempt=errors,
        backoff_seconds=backoff,
        error=str(exc),
        **log_ctx,
    )
    _time.sleep(backoff)
    return True


def log_lost_conflict(logger, exc: Exception, **log_ctx: object) -> None:
    """Log a conflict lost on every try, before the caller raises it.

    Another writer committed to the store first on all
    :data:`CONFLICT_TRIES` tries, so what this step would have written is
    not in the store (for ``commit_skipped_files`` only the log-book rows;
    the days' data is stored). ``log_ctx`` names the step (``op``) and its
    days.
    """
    logger.error(
        "store_conflict_lost",
        tries=CONFLICT_TRIES,
        error=str(exc),
        hint=(
            "Another writer committed to this store first on every try, so "
            "what this step would have written is not in the store. Running "
            "these days again writes it."
        ),
        **log_ctx,
    )


def call_with_store_retries[T](fn: Callable[[], T], *, logger, **log_ctx: object) -> T:
    """Retry a store read/write with backoff before giving up.

    Only transient errors are retried (:func:`is_transient`); any other
    error propagates at once. The final attempt is unguarded -- its exception propagates to the
    caller's own ``except``/``log.exception`` so existing log event names
    and give-up behavior are unchanged; this only adds retries in front of
    that.

    An ``icechunk.ConflictError`` (another commit moved the branch) is not a
    dropped connection: ``fn`` is tried again after
    :func:`wait_after_conflict`, up to :data:`CONFLICT_TRIES` tries in all,
    and the last conflict propagates. Every ``fn`` given here opens its own
    session, so each try starts from the other commit.
    """
    conflicts = 0
    attempt = 0
    while attempt < len(STORE_RETRY_BACKOFF_SECONDS):
        backoff = STORE_RETRY_BACKOFF_SECONDS[attempt]
        try:
            return fn()
        except icechunk.ConflictError as exc:
            conflicts += 1
            if conflicts >= CONFLICT_TRIES:
                log_lost_conflict(logger, exc, **log_ctx)
                raise
            seconds = wait_after_conflict(conflicts)
            logger.warning(
                "store_conflict_retry",
                retry=conflicts,
                of=CONFLICT_TRIES - 1,
                waited_seconds=round(seconds, 1),
                error=str(exc),
                **log_ctx,
            )
            continue
        except RETRYABLE_STORE_ERRORS as exc:
            if not is_transient(exc):
                raise
            logger.warning(
                "store_op_retry",
                attempt=attempt + 1,
                backoff_seconds=backoff,
                error=str(exc),
                **log_ctx,
            )
            _time.sleep(backoff)
            attempt += 1
    return fn()
