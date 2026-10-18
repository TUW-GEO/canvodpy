"""Tests for the resource sampler's store-size measurement.

The size is keyed by the data day the run has finished furthest, measured
once per such day, and the last sample runs on the sampler thread, never
on the caller's. The vanishing-file walk is tested in
``canvod-utils/tests/test_fs.py``.
"""

from __future__ import annotations

import threading
from pathlib import Path

from canvodpy.orchestrator.resources import ResourceSampler


def _seed_store(root: Path, name: str, size: int = 100) -> Path:
    store = root / name
    store.mkdir()
    (store / "a.bin").write_bytes(b"x" * size)
    return store


def test_sampler_records_against_the_last_finished_day_only_once(tmp_path) -> None:
    # The store size is recorded against the data day the run has finished
    # furthest, and only when that day changed since the last walk.
    frontier = {"day": None}
    calls: list[tuple[str, str, int]] = []
    store = _seed_store(tmp_path, "gnss")
    sampler = ResourceSampler(
        30.0,
        stores={"GNSS store": store},
        on_store_size=lambda store, day, size, walk_seconds: calls.append(
            (store, day, size)
        ),
        get_last_finished_day=lambda: frontier["day"],
    )

    # No data day finished yet: nothing is recorded.
    sampler._sample_store_sizes()
    assert calls == []

    # The run finished its first data day: the size is recorded against it.
    frontier["day"] = "2025001"
    sampler._sample_store_sizes()
    assert calls == [("GNSS store", "2025001", 100)]

    # The same data day again: nothing new was stored, no walk.
    calls.clear()
    sampler._sample_store_sizes()
    assert calls == []

    # A later data day: the size is recorded against the new frontier.
    frontier["day"] = "2025002"
    sampler._sample_store_sizes()
    assert calls == [("GNSS store", "2025002", 100)]


def test_stop_walks_on_the_sampler_thread_not_the_caller(tmp_path) -> None:
    # stop() signals the thread and joins it; the last sample (and any final
    # store walk) runs on the sampler thread, never on the caller's, so it
    # does not add to the caller's wall time.
    store = _seed_store(tmp_path, "gnss")
    caller_id = threading.get_ident()
    walker_ids: list[int] = []
    sampler = ResourceSampler(
        1000.0,  # large interval: no periodic sample before stop()
        stores={"GNSS store": store},
        on_store_size=lambda store, day, size, walk_seconds: walker_ids.append(
            threading.get_ident()
        ),
        get_last_finished_day=lambda: "2025001",
    )
    sampler.start()
    sampler.stop(timeout=5.0)
    assert walker_ids
    assert walker_ids[0] != caller_id
