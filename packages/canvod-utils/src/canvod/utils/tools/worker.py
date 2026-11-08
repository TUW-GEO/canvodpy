"""Worker initializer for ProcessPoolExecutor and loky pools."""

from __future__ import annotations


def _worker_init(nice: int, affinity: list[int] | None) -> None:
    """Initialize a worker process with nice priority and optional CPU affinity.

    Called as the ``initializer`` argument of ``ProcessPoolExecutor`` or loky.
    Silently ignores OS errors so pool creation never fails due to missing
    permissions (e.g. nice clamping on macOS, affinity unavailable on BSD).
    ``nice`` may be negative to request higher-than-normal priority; on Linux
    that requires root/CAP_SYS_NICE and just no-ops (caught below) otherwise.
    """
    import os

    if nice != 0:
        try:
            os.nice(nice)
        except AttributeError, PermissionError:
            pass  # no os.nice, or not allowed: the worker runs at normal priority
    if affinity is not None:
        import psutil

        proc = psutil.Process()
        if hasattr(proc, "cpu_affinity"):
            try:
                proc.cpu_affinity(affinity)
            except psutil.Error, OSError, ValueError:
                # Not allowed, or a CPU the machine doesn't have: like the
                # priority, best effort, so a pool never fails on it.
                pass
