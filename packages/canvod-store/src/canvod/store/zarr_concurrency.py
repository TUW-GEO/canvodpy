"""Shared zarr async-concurrency scoping.

Zarr v3's async codec pipeline issues chunk writes/reads for a single array
as a concurrent ``asyncio.gather`` burst, sized by ``zarr.config``'s
``async.concurrency`` (default 10). On network-mounted (CIFS/NFS) stores
that burst can trip connection-abort errors under load. Capping it costs
throughput, so every caller opts in explicitly via its own config knob
(``IcechunkConfig.zarr_async_concurrency``, ``AuxDataConfig.zarr_async_concurrency``)
rather than this helper choosing a default.

Extracted out of ``MyIcechunkStore`` so the aux (SP3/CLK Hermite) cache's
plain-Zarr write path -- a separate store, untouched by the Icechunk-only
fix that originally shipped this -- can use the exact same mechanism.
"""

from __future__ import annotations

import threading
from collections.abc import Generator
from contextlib import contextmanager

import zarr

# zarr.config is a single process-wide donfig singleton; zarr.config.set()'s
# context manager does a plain save-on-enter/restore-on-exit against it, with
# no locking or thread-local isolation of its own. Safe under a strictly
# sequential caller, but multiple threads entering/exiting this block
# concurrently (e.g. canvodpy's cross-group forked writes) could interleave
# out of stack order and restore each other's scoped value mid-write. This
# lock serializes only this small config-mutation+write critical section, not
# whole callers -- cheap, and a no-op whenever concurrency is None (the
# common case, since this feature is opt-in per deployment).
_zarr_config_scope_lock = threading.RLock()


@contextmanager
def scoped_zarr_concurrency(concurrency: int | None) -> Generator[None]:
    """Scope zarr's async chunk write/read concurrency for the enclosed block.

    ``concurrency=None`` is a no-op (zarr's own default applies, unchanged).
    Otherwise reads the current ``async`` config subsection and merges the
    new concurrency value onto it before scoping -- ``zarr.config.set()``
    replaces the whole subsection rather than merging, so passing only
    ``{"concurrency": ...}`` would silently drop sibling keys (e.g.
    ``timeout``) for the scope of the block. This crashed a production run
    with ``KeyError: 'timeout'`` the first time this mistake was made; do
    not reintroduce it.

    Thread-safe: serializes concurrent callers via ``_zarr_config_scope_lock``
    so interleaved enter/exit from multiple threads can't corrupt each
    other's scoped value (see module docstring). The lock is reentrant
    (``RLock``) because this context manager nests on a single thread today
    (see ``test_nested_scoping_reverts_to_the_outer_value``) -- a plain
    ``Lock`` here deadlocks the inner call against its own thread's outer
    acquisition.
    """
    if concurrency is None:
        yield
        return
    with _zarr_config_scope_lock:
        scoped_async_cfg = dict(zarr.config.get("async"))
        scoped_async_cfg["concurrency"] = concurrency
        with zarr.config.set({"async": scoped_async_cfg}):
            yield
