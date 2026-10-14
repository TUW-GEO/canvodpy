"""Forked writes of day blocks (ADR 0016): workers write, one thread commits.

A day of a store made of day blocks is planned as tasks that own whole
epoch chunks (``RinexDataProcessor.plan_forked_day``); each task writes its
files into its own fork (``write_files_into_fork``); the writer thread
merges the forks and commits the day once (``_commit_forked_day``). Here
the tasks run in this process: the fork and the result cross a pickle
round trip, as they cross the process boundary of the worker pool.
"""

from __future__ import annotations

import hashlib
import pickle
import time
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace

import icechunk
import numpy as np
import pytest
import structlog
import xarray as xr
from canvodpy.orchestrator import forked_writes
from canvodpy.orchestrator import pipeline as pipeline_module
from canvodpy.orchestrator.forked_writes import ForkResult, write_files_into_fork
from canvodpy.orchestrator.pipeline import PipelineOrchestrator, _ForkJob
from canvodpy.orchestrator.resources import MemoryMonitor
from test_cross_group_batch_write import (
    _SIDS,
    store,  # noqa: F401 (fixture)
)
from test_day_block_write import _config, _DayBlockProcessor, _inputs

from canvod.config.models import PreprocessingConfig
from canvod.store import MyIcechunkStore
from canvod.store.day_blocks import ChunkOwnershipError
from canvod.store_metadata.io import read_metadata
from canvod.utils.tools import YYYYDOY

_DATE_KEY = "2025087"
_NEXT_DATE_KEY = "2025088"
_GROUP = "canopy_01"
# 15-minute files at 30 s: 30 epochs each, so the store's 180-epoch chunks
# hold six files each and a day of 96 files fills 16 chunks.
_FILES_PER_DAY = 96
_EPOCHS_PER_FILE = 30


def _name(index: int, date_key: str = _DATE_KEY) -> str:
    minutes = index * 15
    return f"FANR35INK_R_{date_key}{minutes // 60:02d}{minutes % 60:02d}_15M_30S_AA.rnx"


def _dataset(index: int, offset: float = 0.0, date_key: str = _DATE_KEY) -> xr.Dataset:
    """File ``index`` of the day: 30 epochs at 30 s, values from its index."""
    day = np.datetime64(YYYYDOY.from_str(date_key).date, "s")
    start = day + np.timedelta64(index * 15 * 60, "s")
    epochs = start + np.arange(_EPOCHS_PER_FILE) * np.timedelta64(30, "s")
    values = np.full((_EPOCHS_PER_FILE, len(_SIDS)), 30.0 + index + offset, np.float32)
    file_hash = hashlib.sha256(f"{date_key}/{index}/{offset}".encode()).hexdigest()[:16]
    return xr.Dataset(
        {"S1C": xr.DataArray(values, dims=["epoch", "sid"])},
        coords={"epoch": ("epoch", epochs, {"time_system": "GPS"}), "sid": _SIDS},
        attrs={
            "File Hash": file_hash,
            "Source Format": "rinex3",
            "canonical_name": _name(index, date_key),
            "physical_path": _name(index, date_key),
        },
    )


class _Processor(_DayBlockProcessor):
    """One day's processor of a run, without reading files."""

    def __init__(
        self,
        gnss_store: MyIcechunkStore,
        strategy: str = "skip",
        date_key: str = _DATE_KEY,
    ) -> None:
        super().__init__(gnss_store, strategy=strategy)
        self._config = _config()
        # The real section: tasks carry it to the workers, pickled.
        self._config.processing.preprocessing = PreprocessingConfig()
        self.matched_data_dirs = SimpleNamespace(yyyydoy=YYYYDOY.from_str(date_key))

    def _canonical_name(self, fname: Path) -> str:
        return fname.name


def _descriptors(indices, date_key: str = _DATE_KEY) -> list[tuple]:
    """The day's task descriptors as ``prepare_batch_tasks`` gives them."""
    return [
        (Path(_name(i, date_key)), None, None, None, _GROUP, False) for i in indices
    ]


@pytest.fixture
def files(monkeypatch) -> dict[str, xr.Dataset]:
    """The file a task reads, by name; tests change it to change the data."""
    by_name = {
        _name(i, date_key): _dataset(i, date_key=date_key)
        for date_key in (_DATE_KEY, _NEXT_DATE_KEY)
        for i in range(_FILES_PER_DAY)
    }

    def read(file_task, groups):
        fname = Path(file_task[0])
        return fname, {groups[0]: by_name[fname.name]}, {}

    monkeypatch.setattr(forked_writes, "_read", read)
    return by_name


@pytest.fixture
def seeded(store: MyIcechunkStore, files) -> MyIcechunkStore:  # noqa: F811
    """The store with the day's first file written, so the day has its block."""
    _Processor(store)._write_day_blocks(
        _inputs(_GROUP, [(Path(_name(0)), files[_name(0)])])
    )
    return store


def _day(files: dict[str, xr.Dataset], date_key: str = _DATE_KEY) -> xr.Dataset:
    """The files of one day, joined."""
    names = [_name(i, date_key) for i in range(_FILES_PER_DAY)]
    return xr.concat([files[name] for name in names], dim="epoch")


def _run_task(job: _ForkJob) -> ForkResult:
    """Run a fork job as the worker pool does, across a pickle round trip."""
    fork, task = pickle.loads(pickle.dumps((job.fork, job.task)))
    return pickle.loads(pickle.dumps(write_files_into_fork(fork, task)))


def _submit(job: _ForkJob) -> Future:
    future: Future = Future()
    future.set_result(_run_task(job))
    return future


def _write_day(proc: _Processor) -> dict:
    planned = proc.plan_forked_day(_descriptors(range(_FILES_PER_DAY)))
    assert planned is not None
    results = [_run_task(_ForkJob(task, fork)) for task, fork in planned.tasks]
    return proc._commit_forked_day(planned, results)


def _commits(gnss_store: MyIcechunkStore) -> int:
    return len(list(gnss_store.repo.ancestry(branch="main")))


def _log_book(gnss_store: MyIcechunkStore):
    with gnss_store.readonly_session("main") as session:
        return gnss_store.load_metadata(session.store, _GROUP)


def test_files_sharing_a_chunk_go_to_one_task(seeded) -> None:
    planned = _Processor(seeded).plan_forked_day(_descriptors(range(_FILES_PER_DAY)))

    assert planned is not None
    assert len(planned.tasks) == 16
    owned = [task.chunks[_GROUP] for task, _ in planned.tasks]
    assert all(len(task.file_tasks) == 6 for task, _ in planned.tasks)
    assert all(len(chunks) == 1 for chunks in owned)
    assert len(frozenset.union(*owned)) == 16


def test_a_forked_day_keeps_every_epoch_in_one_commit(seeded, files) -> None:
    # Without the grouping, the forks of a chunk's six files replace each
    # other's chunk when merged and five sixths of the day are lost.
    n_commits = _commits(seeded)

    out = _write_day(_Processor(seeded))

    assert _commits(seeded) == n_commits + 1
    assert out[_GROUP].actions["written"] == _FILES_PER_DAY - 1
    assert out[_GROUP].actions["skipped"] == 1
    stored = seeded.read_group(_GROUP, drop_empty=True)
    expected = _day(files)
    assert stored.sizes["epoch"] == _FILES_PER_DAY * _EPOCHS_PER_FILE
    np.testing.assert_array_equal(stored.epoch.values, expected.epoch.values)
    np.testing.assert_array_equal(stored["S1C"].values, expected["S1C"].values)
    log = _log_book(seeded)
    # The seed's row, then a row for every file of the day, skipped ones too.
    assert log.height == 1 + _FILES_PER_DAY
    assert log["epochs"].to_list()[1:] == [-1] + [_EPOCHS_PER_FILE] * 95
    summary = read_metadata(seeded.store_path).summaries
    assert summary.total_epochs == stored.sizes["epoch"]


def test_an_overwrite_rerun_gives_the_same_data_in_one_commit(seeded, files) -> None:
    _write_day(_Processor(seeded))
    before = seeded.read_group(_GROUP, drop_empty=True)
    n_commits = _commits(seeded)

    out = _write_day(_Processor(seeded, strategy="overwrite"))

    assert _commits(seeded) == n_commits + 1
    assert out[_GROUP].actions["overwritten"] == _FILES_PER_DAY
    after = seeded.read_group(_GROUP, drop_empty=True)
    xr.testing.assert_identical(after, before)
    summary = read_metadata(seeded.store_path).summaries
    assert summary.total_epochs == after.sizes["epoch"]


def test_a_rerun_with_skip_writes_no_data(seeded) -> None:
    _write_day(_Processor(seeded))
    before = seeded.read_group(_GROUP, drop_empty=True)

    out = _write_day(_Processor(seeded))

    assert out[_GROUP].actions["skipped"] == _FILES_PER_DAY
    assert out[_GROUP].total_nbytes == 0
    xr.testing.assert_identical(seeded.read_group(_GROUP, drop_empty=True), before)


def test_two_days_planned_together_both_commit(seeded, files) -> None:
    # A batch grows its days' blocks, then plans all its days before the
    # writer commits the first one.
    next_day = np.datetime64(YYYYDOY.from_str(_NEXT_DATE_KEY).date, "D")
    seeded.grow_day_blocks({_GROUP: {next_day: 30.0}}, message="grow")
    days = []
    for date_key in (_DATE_KEY, _NEXT_DATE_KEY):
        proc = _Processor(seeded, date_key=date_key)
        planned = proc.plan_forked_day(_descriptors(range(_FILES_PER_DAY), date_key))
        assert planned is not None
        days.append((proc, planned))
    for proc, planned in days:
        results = [_run_task(_ForkJob(task, fork)) for task, fork in planned.tasks]
        proc._commit_forked_day(planned, results)

    stored = seeded.read_group(_GROUP, drop_empty=True)
    expected = xr.concat([_day(files), _day(files, _NEXT_DATE_KEY)], dim="epoch")
    np.testing.assert_array_equal(stored.epoch.values, expected.epoch.values)
    np.testing.assert_array_equal(stored["S1C"].values, expected["S1C"].values)
    summary = read_metadata(seeded.store_path).summaries
    assert summary.total_epochs == stored.sizes["epoch"]


def _orchestrator(gnss_store: MyIcechunkStore) -> PipelineOrchestrator:
    pipe = PipelineOrchestrator.__new__(PipelineOrchestrator)
    pipe.site = SimpleNamespace(
        gnss_store=gnss_store, gnss_store_path=gnss_store.store_path
    )
    pipe._logger = structlog.get_logger(__name__)
    pipe._on_group_written = None
    pipe._run = _Recorder()
    return pipe


class _Recorder:
    """The run history's receiver-day results."""

    def __init__(self) -> None:
        self.days: list[tuple[str, str, str]] = []

    def finish(self, receiver, day, result, *, bytes_added=None) -> None:
        self.days.append((receiver, day, result))


def test_a_day_that_lost_a_conflict_is_written_again(seeded, files) -> None:
    # Two runs plan the same day; the other commits first.
    proc = _Processor(seeded, strategy="overwrite")
    planned = proc.plan_forked_day(_descriptors(range(_FILES_PER_DAY)))
    assert planned is not None
    results = [_run_task(_ForkJob(task, fork)) for task, fork in planned.tasks]
    for index in range(_FILES_PER_DAY):
        files[_name(index)] = _dataset(index, offset=100.0)
    _write_day(_Processor(seeded, strategy="overwrite"))
    for index in range(_FILES_PER_DAY):
        files[_name(index)] = _dataset(index)
    with pytest.raises(icechunk.ConflictError):
        proc._commit_forked_day(planned, results)

    out = _orchestrator(seeded)._write_forked_day(
        proc, planned, _descriptors(range(_FILES_PER_DAY)), results, _submit, 1
    )

    # The other run's files had other hashes: only the seed's is known.
    assert out[_GROUP].actions["overwritten"] == 1
    assert out[_GROUP].actions["written"] == _FILES_PER_DAY - 1
    stored = seeded.read_group(_GROUP, drop_empty=True)
    expected = _day(files)
    np.testing.assert_array_equal(stored["S1C"].values, expected["S1C"].values)


def test_a_day_whose_write_failed_is_recorded_failed(seeded) -> None:
    proc = _Processor(seeded)
    planned = proc.plan_forked_day(_descriptors(range(_FILES_PER_DAY)))
    assert planned is not None
    write: Future = Future()
    write.set_exception(icechunk.ConflictError("lost twice"))
    pipe = _orchestrator(seeded)

    done = pipe._finish_forked_day(_DATE_KEY, planned, write)

    assert done == {}
    assert pipe._run.days == [(_GROUP, _DATE_KEY, "failed")]


def test_a_failed_growth_fails_the_batch_days_and_the_run_goes_on(
    seeded, monkeypatch
) -> None:
    pipe = _orchestrator(seeded)
    pipe.days_per_batch = 1
    pipe.n_max_workers = 1
    pipe._threads_per_worker = 1
    pipe._memory_monitor = MemoryMonitor()
    resources = {"nice_priority": None, "cpu_affinity": None}
    pipe._config = SimpleNamespace(
        processing=SimpleNamespace(
            params=SimpleNamespace(resolve_resources=lambda: resources)
        )
    )

    def prepare(date_key, _receivers, _keep_vars):
        file_map = [(_GROUP, [Path(_name(0))])]
        return _Processor(seeded), _descriptors([0]), file_map

    def grow(_doy_contexts, _batch_index):
        msg = "Could not grow the day blocks: other commits conflicted 3 times."
        raise RuntimeError(msg)

    monkeypatch.setattr(pipe, "_prepare_single_date", prepare)
    monkeypatch.setattr(pipe, "_grow_day_blocks", grow)
    monkeypatch.setattr(pipeline_module, "_loky_reusable", lambda **_: None)

    batch = [(_DATE_KEY, {}), ("2025088", {})]
    assert list(pipe._process_multi_day_batches(batch, None)) == []
    assert pipe._run.days == [
        (_GROUP, _DATE_KEY, "failed"),
        (_GROUP, "2025088", "failed"),
    ]


def test_a_group_keeps_its_chunks_when_the_settings_change(store, files) -> None:  # noqa: F811
    # The group was created with chunks of 90 epochs; the settings now say
    # 180. Tasks own the chunks the group has, so no file is left to the
    # writer thread.
    store.chunk_strategy = {**store.chunk_strategy, "epoch": 90}
    _Processor(store)._write_day_blocks(
        _inputs(_GROUP, [(Path(_name(0)), files[_name(0)])])
    )
    store.chunk_strategy = {**store.chunk_strategy, "epoch": 180}
    before = _commits(store)
    proc = _Processor(store)
    planned = proc.plan_forked_day(_descriptors(range(_FILES_PER_DAY)))
    assert planned is not None
    results = [_run_task(_ForkJob(task, fork)) for task, fork in planned.tasks]
    assert not [n for r in results for n in r.files if n.deferred is not None]

    proc._commit_forked_day(planned, results)

    # Three 30-epoch files per 90-epoch chunk.
    assert len(planned.tasks) == _FILES_PER_DAY // 3
    assert _commits(store) == before + 1
    stored = store.read_group(_GROUP, drop_empty=True)
    np.testing.assert_array_equal(stored["S1C"].values, _day(files)["S1C"].values)


def _finished(pipe, planned, out) -> list[tuple[str, str, str]]:
    """The run history's receiver-days after finishing a written day."""
    write: Future = Future()
    write.set_result(out)
    pipe._finish_forked_day(_DATE_KEY, planned, write)
    return pipe._run.days


def test_files_that_fail_in_the_retry_round_fail_the_day(seeded, files) -> None:
    proc = _Processor(seeded, strategy="overwrite")
    planned = proc.plan_forked_day(_descriptors(range(_FILES_PER_DAY)))
    assert planned is not None
    results = [_run_task(_ForkJob(task, fork)) for task, fork in planned.tasks]
    _write_day(_Processor(seeded, strategy="overwrite"))

    def failing(_job: _ForkJob) -> Future:
        future: Future = Future()
        future.set_exception(OSError("the worker lost the data drive"))
        return future

    pipe = _orchestrator(seeded)
    out = pipe._write_forked_day(
        proc, planned, _descriptors(range(_FILES_PER_DAY)), results, failing, 1
    )

    assert out[_GROUP].failed_files == _FILES_PER_DAY
    assert _finished(pipe, planned, out) == [(_GROUP, _DATE_KEY, "failed")]


def test_a_deferred_file_that_fails_fails_the_day(seeded, monkeypatch) -> None:
    def beyond(*_args, **_kwargs):
        msg = "beyond the task's chunks"
        raise ChunkOwnershipError(msg)

    def broken(_session, _numbers):
        msg = "the writer thread could not write it"
        raise RuntimeError(msg)

    monkeypatch.setattr(forked_writes, "write_file_region", beyond)
    proc = _Processor(seeded)
    monkeypatch.setattr(proc, "_write_deferred", broken)
    # Without the seed's file, which would be skipped and so give a row.
    planned = proc.plan_forked_day(_descriptors(range(1, _FILES_PER_DAY)))
    assert planned is not None
    results = [_run_task(_ForkJob(task, fork)) for task, fork in planned.tasks]

    out = proc._commit_forked_day(planned, results)

    assert out[_GROUP].failed_files == _FILES_PER_DAY - 1
    pipe = _orchestrator(seeded)
    assert _finished(pipe, planned, out) == [(_GROUP, _DATE_KEY, "failed")]


def test_a_day_without_a_calendar_date_is_refused_when_planned(seeded) -> None:
    # Refused before any fork runs, not when the writer thread finishes it.
    proc = _Processor(seeded)
    proc.matched_data_dirs = SimpleNamespace(
        yyyydoy=SimpleNamespace(date=None, to_str=lambda: _DATE_KEY)
    )

    with pytest.raises(ValueError, match="no calendar date"):
        proc.plan_forked_day(_descriptors(range(_FILES_PER_DAY)))


def test_a_batch_that_breaks_waits_for_the_day_being_committed(
    seeded, monkeypatch
) -> None:
    # The day's commit is running in the writer thread when the batch
    # breaks: the error leaves the batch only after the commit finished.
    pipe = _orchestrator(seeded)
    pipe.days_per_batch = 1
    pipe.n_max_workers = 1
    pipe._threads_per_worker = 1
    pipe._memory_monitor = MemoryMonitor()
    resources = {"nice_priority": None, "cpu_affinity": None}
    pipe._config = SimpleNamespace(
        processing=SimpleNamespace(
            params=SimpleNamespace(resolve_resources=lambda: resources)
        )
    )

    def prepare(date_key, _receivers, _keep_vars):
        file_map = [(_GROUP, [Path(_name(i)) for i in range(_FILES_PER_DAY)])]
        return _Processor(seeded), _descriptors(range(_FILES_PER_DAY)), file_map

    def completions(_submit_task, tasks, _window):
        for task in tasks:
            if isinstance(task[1], _ForkJob):
                yield task, _submit(task[1])
        msg = "the worker pool broke"
        raise RuntimeError(msg)

    committed: list[str] = []

    def commit(_processor, planned, *_args):
        time.sleep(0.5)
        committed.append(planned.date_key)
        return {}

    monkeypatch.setattr(pipe, "_prepare_single_date", prepare)
    monkeypatch.setattr(pipe, "_grow_day_blocks", lambda *_: None)
    monkeypatch.setattr(pipe, "_write_forked_day", commit)
    monkeypatch.setattr(pipeline_module, "_loky_reusable", lambda **_: None)
    monkeypatch.setattr(pipeline_module, "_windowed_completions", completions)

    with pytest.raises(RuntimeError, match="worker pool broke"):
        list(pipe._process_multi_day_batches([(_DATE_KEY, {})], None))
    assert committed == [_DATE_KEY]
