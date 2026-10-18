"""A run works in units of days, committed once per unit (ADR 0021, #425).

The batch loop runs with Phase 1 replaced by the days' processors and
tasks, and a worker pool that runs each task in this process across a
pickle round trip, as tasks cross the process boundary of the pool.
"""

from __future__ import annotations

import pickle
import threading
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import polars as pl
import pytest
import structlog
import xarray as xr
from canvodpy.orchestrator import forked_writes
from canvodpy.orchestrator import pipeline as pipeline_module
from canvodpy.orchestrator.pipeline import PipelineOrchestrator
from canvodpy.orchestrator.resources import MemoryMonitor
from test_cross_group_batch_write import store  # noqa: F401 (fixture)
from test_day_block_write import _inputs
from test_forked_day_writes import _GROUP, _dataset, _descriptors, _name, _Processor

from canvod.store import MyIcechunkStore
from canvod.utils.tools import YYYYDOY

#: Three hours of each day: two chunks of six 15-minute files.
FILES_PER_DAY = 12
#: Fourteen days from 2025-03-28 (2025087).
DAYS = [f"2025{doy:03d}" for doy in range(87, 101)]
NO_ORBITS = "2025090"


@pytest.fixture
def files(monkeypatch) -> dict[str, xr.Dataset]:
    """The file a task reads, by name."""
    by_name = {
        _name(i, day): _dataset(i, date_key=day)
        for day in DAYS
        for i in range(FILES_PER_DAY)
    }

    def read(file_task, groups):
        fname = Path(file_task[0])
        return fname, {groups[0]: by_name[fname.name]}, {}

    monkeypatch.setattr(forked_writes, "_read", read)
    return by_name


def _seed(gnss_store: MyIcechunkStore, files) -> MyIcechunkStore:
    """Write the first file of the first day, so the group exists."""
    first = _name(0, DAYS[0])
    _Processor(gnss_store, date_key=DAYS[0])._write_day_blocks(
        _inputs(_GROUP, [(Path(first), files[first])])
    )
    return gnss_store


@pytest.fixture
def seeded(store: MyIcechunkStore, files) -> MyIcechunkStore:  # noqa: F811
    return _seed(store, files)


class _Pool:
    """A worker pool that runs each task here, across a pickle round trip."""

    def submit(self, fn, *args) -> Future:
        future: Future = Future()
        try:
            result = fn(*pickle.loads(pickle.dumps(args)))
            future.set_result(pickle.loads(pickle.dumps(result)))
        except Exception as exc:
            future.set_exception(exc)
        return future


class _Recorder:
    """The run history's receiver-day results."""

    def __init__(self) -> None:
        self.days: list[tuple[str, str, str]] = []

    def finish(self, receiver, day, result, *, bytes_added=None) -> None:
        self.days.append((receiver, day, result))


def _run(
    gnss_store: MyIcechunkStore,
    monkeypatch,
    days: list[str],
    unit_days: int,
    no_orbits: str | None = NO_ORBITS,
) -> PipelineOrchestrator:
    """Run ``days`` in units of ``unit_days``; the days come back in order.

    The orbit products of ``no_orbits`` are not out yet.
    """
    pipe = PipelineOrchestrator.__new__(PipelineOrchestrator)
    pipe.site = SimpleNamespace(
        gnss_store=gnss_store,
        gnss_store_path=gnss_store.store_path,
        read_receiver_data=lambda **_: xr.Dataset(),
    )
    pipe.unit_days = unit_days
    pipe.n_max_workers = 1
    pipe._workers = None
    pipe._threads_per_worker = 1
    pipe._on_group_written = None
    pipe._run = _Recorder()
    pipe._logger = structlog.get_logger(__name__)
    pipe._memory_monitor = MemoryMonitor()
    resources = {"nice_priority": None, "cpu_affinity": None}
    pipe._config = SimpleNamespace(
        processing=SimpleNamespace(
            params=SimpleNamespace(resolve_resources=lambda: resources)
        )
    )

    def prepare(date_key, _receivers, _keep_vars):
        if date_key == no_orbits:
            msg = f"Failed to download the orbit products of {date_key}"
            raise RuntimeError(msg)
        descriptors = _descriptors(range(FILES_PER_DAY), date_key)
        file_map = [(_GROUP, [d[0] for d in descriptors])]
        return _Processor(gnss_store, date_key=date_key), descriptors, file_map

    monkeypatch.setattr(pipe, "_prepare_single_date", prepare)
    monkeypatch.setattr(pipeline_module, "_loky_reusable", lambda **_: _Pool())
    batch = [(day, {_GROUP: (None, None, None, "rinex3")}) for day in days]
    done = [
        day
        for day, _, _ in pipe._process_multi_day_batches(batch, None, threading.Event())
    ]
    assert done == [day for day in days if day != no_orbits]
    return pipe


def _commits(gnss_store: MyIcechunkStore) -> list[str]:
    return [s.message for s in gnss_store.repo.ancestry(branch="main")]


def _stored_days(gnss_store: MyIcechunkStore) -> set[str]:
    data = gnss_store.read_group(_GROUP, drop_empty=True)
    return {
        YYYYDOY.from_date(day.astype(object)).to_str()
        for day in np.unique(data.epoch.values.astype("M8[D]"))
    }


def test_a_backlog_makes_one_growth_and_one_data_commit_per_unit(
    seeded, monkeypatch
) -> None:
    before = len(_commits(seeded))

    pipe = _run(seeded, monkeypatch, DAYS, unit_days=7, no_orbits=None)

    new = _commits(seeded)[: len(_commits(seeded)) - before]
    assert len(new) == 4
    assert sum("Day blocks for" in m for m in new) == 2
    assert sum("(7 days)" in m for m in new) == 2
    assert _stored_days(seeded) == set(DAYS)
    assert sorted(pipe._run.days) == sorted((_GROUP, day, "written") for day in DAYS)


def test_a_day_without_orbit_products_fails_alone(seeded, monkeypatch) -> None:
    pipe = _run(seeded, monkeypatch, DAYS[:7], unit_days=7)

    # The other days of the unit are stored; the day without orbit products
    # gets no block and no row, and stays open for the next run.
    assert _stored_days(seeded) == set(DAYS[:7]) - {NO_ORBITS}
    assert NO_ORBITS not in {day for _, day, _ in pipe._run.days}

    _run(seeded, monkeypatch, [NO_ORBITS], unit_days=7, no_orbits=None)
    assert _stored_days(seeded) == set(DAYS[:7])


def _log_book(gnss_store: MyIcechunkStore) -> pl.DataFrame:
    """The log book without what differs between runs, in a fixed order."""
    with gnss_store.readonly_session("main") as session:
        df = gnss_store.load_metadata(session.store, _GROUP)
    differ = {"index", "written_at", "commit_msg", "snapshot_id", "run_id"}
    return (
        df.drop([c for c in df.columns if c in differ])
        .sort(["start", "rinex_hash", "action"])
        .select(sorted(set(df.columns) - differ))
    )


def test_units_store_what_a_run_of_one_day_at_a_time_stores(
    tmp_path, files, monkeypatch
) -> None:
    from canvod.store_metadata.testing import create_test_store, give_test_metadata

    def new_store(name: str) -> MyIcechunkStore:
        path = tmp_path / name
        path.mkdir()
        gnss_store = MyIcechunkStore(create_test_store(path))
        give_test_metadata(path)
        return _seed(gnss_store, files)

    # The later week first, then the earlier one: days out of order.
    later, earlier = DAYS[7:], DAYS[:7]
    units, days = new_store("units"), new_store("days")
    for part in (later, earlier):
        _run(units, monkeypatch, part, unit_days=7, no_orbits=None)
        _run(days, monkeypatch, part, unit_days=1, no_orbits=None)

    a = units.read_group(_GROUP, drop_empty=True)
    b = days.read_group(_GROUP, drop_empty=True)
    np.testing.assert_array_equal(a.epoch.values, b.epoch.values)
    np.testing.assert_array_equal(a["S1C"].values, b["S1C"].values)
    assert _log_book(units).equals(_log_book(days))
    assert len(_commits(units)) < len(_commits(days))
