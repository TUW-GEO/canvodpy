"""Tests for the shared zarr async-concurrency scoping helper.

Extracted from MyIcechunkStore's icechunk-only throttle so the aux
(SP3/CLK Hermite) cache's plain-Zarr write path can share the exact same
mechanism. MyIcechunkStore's own behavior is
covered by test_write_concurrency_cap.py and is unaffected by this
extraction (verified there, unmodified).
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import zarr

from canvod.store.zarr_concurrency import scoped_zarr_concurrency


def test_none_is_a_no_op() -> None:
    before = zarr.config.get("async.concurrency")
    with scoped_zarr_concurrency(None):
        assert zarr.config.get("async.concurrency") == before


def test_scopes_concurrency_for_the_block() -> None:
    with scoped_zarr_concurrency(2):
        assert zarr.config.get("async.concurrency") == 2


def test_reverts_after_the_block() -> None:
    before = zarr.config.get("async.concurrency")
    with scoped_zarr_concurrency(3):
        pass
    assert zarr.config.get("async.concurrency") == before


def test_preserves_sibling_async_config_keys() -> None:
    # The regression this module exists to prevent from recurring:
    # zarr.config.set({"async": {"concurrency": N}}) replaces the whole
    # "async" subdict rather than merging, silently dropping sibling keys
    # (e.g. "timeout") for the scope of the block.
    before_async_cfg = dict(zarr.config.get("async"))
    assert "timeout" in before_async_cfg
    with scoped_zarr_concurrency(2):
        during = dict(zarr.config.get("async"))
        assert during["concurrency"] == 2
        assert during["timeout"] == before_async_cfg["timeout"]


def test_nested_scoping_reverts_to_the_outer_value() -> None:
    with scoped_zarr_concurrency(4):
        with scoped_zarr_concurrency(2):
            assert zarr.config.get("async.concurrency") == 2
        assert zarr.config.get("async.concurrency") == 4


def test_concurrent_threads_never_observe_each_others_scoped_value() -> None:
    """Regression test for the cross-group fork/merge write-batch design.

    `zarr.config` is a single process-wide donfig singleton;
    `scoped_zarr_concurrency` mutates it via save-on-enter/restore-on-exit.
    Before `_zarr_config_scope_lock` was added, concurrent callers (e.g. one
    thread per receiver group in `RinexDataProcessor._write_group_into_fork`)
    could interleave enter/exit out of stack order and observe -- or restore
    -- each other's scoped value mid-write. The lock forces full
    serialization of the config-mutation+read critical section, so each
    thread's block always sees exactly its own value, no matter how many
    other threads are contending for the same block concurrently.
    """
    before = zarr.config.get("async.concurrency")
    n_threads = 8
    barrier = threading.Barrier(n_threads)
    observed: dict[int, int] = {}

    def _worker(thread_idx: int) -> None:
        concurrency = 100 + thread_idx
        barrier.wait()  # maximize contention: all threads race to enter together
        with scoped_zarr_concurrency(concurrency):
            # A tiny sleep widens the window in which an unprotected,
            # interleaved implementation would leak another thread's value.
            time.sleep(0.01)
            observed[thread_idx] = zarr.config.get("async.concurrency")

    with ThreadPoolExecutor(max_workers=n_threads) as tpe:
        futures = [tpe.submit(_worker, i) for i in range(n_threads)]
        for fut in as_completed(futures):
            fut.result()

    for thread_idx in range(n_threads):
        assert observed[thread_idx] == 100 + thread_idx, (
            f"thread {thread_idx} observed a concurrency value that wasn't "
            "its own -- scoped_zarr_concurrency is not thread-safe"
        )
    assert zarr.config.get("async.concurrency") == before
