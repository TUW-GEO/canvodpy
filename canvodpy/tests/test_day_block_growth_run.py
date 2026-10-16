"""A run grows the day blocks of a batch before reading files (ADR 0016).

The batch loop runs with Phase 1 replaced by made-up results and a worker
pool whose every task fails, so the store shows what the growth alone did.
"""

from __future__ import annotations

import threading
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import structlog
from canvodpy.orchestrator import pipeline as pipeline_module
from canvodpy.orchestrator.pipeline import PipelineOrchestrator
from canvodpy.orchestrator.resources import MemoryMonitor
from test_cross_group_batch_write import _FakeSite
from test_cross_group_batch_write import store as store
from test_day_block_write import _config, _DayBlockProcessor, _file, _inputs

from canvod.store import MyIcechunkStore
from canvod.store.day_blocks import day_blocks
from canvod.utils.tools import YYYYDOY

STORED_DAY = np.datetime64("2025-03-28", "D")  # 2025087
READ_FAILS = "2025088"  # Phase 1 succeeds, every file fails to read
NO_ORBITS = "2025089"  # orbit products not out yet
READ_FAILS_DAY = np.datetime64("2025-03-29", "D")
NO_ORBITS_DAY = np.datetime64("2025-03-30", "D")


def _name(date_key: str, receiver: str = "canopy_01") -> Path:
    return Path(f"FANR35INK_R_{date_key}0000_15M_05S_AA.{receiver}.rnx")


class _Processor(_DayBlockProcessor):
    """One day's processor, as Phase 1 returns it."""

    def __init__(self, store: MyIcechunkStore, date_key: str) -> None:
        super().__init__(store)
        self._config = _config()
        self.matched_data_dirs = SimpleNamespace(yyyydoy=YYYYDOY.from_str(date_key))
        self._canonical_names: dict[Path, str] = {}

    def _canonical_name(self, fname: Path) -> str:
        return fname.name.split(".")[0] + ".rnx"


class _FailingPool:
    """A worker pool on which every file fails to read."""

    def submit(self, fn, *args) -> Future:
        future: Future = Future()
        future.set_exception(RuntimeError("could not read the file"))
        return future


def _run(store: MyIcechunkStore, monkeypatch, receivers: list[str]) -> None:
    """Run one batch of READ_FAILS and NO_ORBITS for ``receivers``."""
    pipe = PipelineOrchestrator.__new__(PipelineOrchestrator)
    pipe.site = _FakeSite(store)
    pipe.days_per_batch = 2
    pipe.n_max_workers = 1
    pipe._threads_per_worker = 1
    pipe._on_group_written = None
    pipe._run = None
    pipe._logger = structlog.get_logger(__name__)
    pipe._memory_monitor = MemoryMonitor()
    resources = {"nice_priority": None, "cpu_affinity": None}
    pipe._config = SimpleNamespace(
        processing=SimpleNamespace(
            params=SimpleNamespace(resolve_resources=lambda: resources)
        )
    )

    def prepare(date_key, _receivers, _keep_vars):
        if date_key == NO_ORBITS:
            msg = f"Failed to download the orbit products of {date_key}"
            raise RuntimeError(msg)
        file_map = [(r, [_name(date_key, r)]) for r in receivers]
        tasks = [(f[0], None, None, None, r, False) for r, f in file_map]
        return _Processor(store, date_key), tasks, file_map

    monkeypatch.setattr(pipe, "_prepare_single_date", prepare)
    monkeypatch.setattr(pipeline_module, "_loky_reusable", lambda **_: _FailingPool())
    batch = [(READ_FAILS, {}), (NO_ORBITS, {})]
    assert list(pipe._process_multi_day_batches(batch, None, threading.Event())) == []


def _blocks(store: MyIcechunkStore, group: str = "canopy_01") -> dict:
    with store.readonly_session("main") as session:
        return day_blocks(session.store, group)


@pytest.fixture
def stored(store: MyIcechunkStore) -> MyIcechunkStore:
    """The store with one day of canopy_01 written as day blocks."""
    proc = _DayBlockProcessor(store)
    proc._config = _config()
    proc._write_day_blocks(_inputs("canopy_01", [_file("a", 0)]))
    return store


def test_days_without_orbit_products_get_no_block(stored, monkeypatch) -> None:
    _run(stored, monkeypatch, ["canopy_01"])

    blocks = _blocks(stored)
    assert NO_ORBITS_DAY not in blocks
    # The day whose files then failed has its block, holding only fill.
    assert set(blocks) == {STORED_DAY, READ_FAILS_DAY}
    assert blocks[READ_FAILS_DAY].cadence_s == 5
    data = stored.read_group("canopy_01", drop_empty=True)
    assert set(data.epoch.values.astype("M8[D]")) == {STORED_DAY}


def test_a_failed_days_block_is_reused_on_rerun(stored, monkeypatch) -> None:
    _run(stored, monkeypatch, ["canopy_01"])
    first = _blocks(stored)
    snapshots = len(list(stored.repo.ancestry(branch="main")))

    _run(stored, monkeypatch, ["canopy_01"])

    assert _blocks(stored) == first
    assert len(list(stored.repo.ancestry(branch="main"))) == snapshots


def test_a_group_not_written_yet_is_left_to_its_first_write(
    stored, monkeypatch
) -> None:
    _run(stored, monkeypatch, ["canopy_01", "canopy_02"])

    assert "canopy_02" not in (stored.list_groups() or [])
