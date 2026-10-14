"""Writes of day blocks into forks of one session (ADR 0016).

Forks are pickled to worker processes, so these tests use a repository on
disk: an in-memory repository does not survive pickling.
"""

from __future__ import annotations

import pickle

import icechunk
import numpy as np
import pytest
import xarray as xr

from canvod.store.day_blocks import (
    ChunkOwnershipError,
    add_day_block,
    day_blocks,
    load_group,
    span_chunks,
    write_file_region,
)

GROUP = "canopy_01"
SIDS = ["G01|L1|C", "G02|L1|C"]
DAY = np.datetime64("2025-01-01", "D")


def _file(start_s: float, n: int, cadence_s: float, value: float) -> xr.Dataset:
    """A made-up file: ``n`` epochs from ``start_s`` seconds into the day."""
    offsets = start_s + np.arange(n) * cadence_s
    epochs = DAY.astype("M8[ns]") + (offsets * 1e9).astype("m8[ns]")
    return xr.Dataset(
        {"SNR": (("epoch", "sid"), np.full((n, len(SIDS)), value, dtype="f4"))},
        coords={
            "epoch": xr.Variable("epoch", epochs, {"time_system": "GPS"}),
            "sid": SIDS,
        },
    )


@pytest.fixture
def repo(tmp_path) -> icechunk.Repository:
    repo = icechunk.Repository.create(
        icechunk.local_filesystem_storage(str(tmp_path / "store"))
    )
    session = repo.writable_session("main")
    add_day_block(session, GROUP, DAY, 30, template=_file(0, 1, 30, 0.0))
    session.commit("a 30 s day block: 2880 slots, 16 chunks of 180")
    return repo


def _in_worker(fork, ds: xr.Dataset, **kwargs):
    """Write ``ds`` into a pickled copy of ``fork``, as a worker would."""
    fork = pickle.loads(pickle.dumps(fork))
    write_file_region(fork, GROUP, ds, **kwargs)
    return pickle.loads(pickle.dumps(fork))


def test_two_forks_writing_one_chunk_lose_data(repo):
    # The reason a chunk must never be split across forks: Icechunk merges
    # chunks, not regions, so the later fork's chunk replaces the earlier.
    session = repo.writable_session("main")
    first = _in_worker(session.fork(), _file(0, 30, 30, 1.0))
    second = _in_worker(session.fork(), _file(900, 30, 30, 2.0))
    session.merge(first, second)
    session.commit("two 15-minute files of one chunk, in two forks")

    stored = load_group(repo.readonly_session("main").store, GROUP)
    snr = stored.SNR.isel(epoch=slice(0, 60)).values
    assert np.isnan(snr[:30]).all()
    assert (snr[30:] == 2.0).all()


def test_forks_writing_their_own_chunks_merge_into_one_commit(repo):
    session = repo.writable_session("main")
    one_chunk = 180 * 30
    first = _in_worker(session.fork(), _file(0, 180, 30, 1.0))
    second = _in_worker(session.fork(), _file(one_chunk, 180, 30, 2.0))
    session.merge(first, second)
    session.commit("two files of different chunks, in two forks")

    stored = load_group(repo.readonly_session("main").store, GROUP, drop_empty=True)
    assert stored.sizes["epoch"] == 360
    assert (stored.SNR.values[:180] == 1.0).all()
    assert (stored.SNR.values[180:] == 2.0).all()


def test_a_write_outside_its_chunks_is_refused_and_writes_nothing(repo):
    session = repo.writable_session("main")
    # Epochs 170 to 189 of the day: chunks 0 and 1.
    straddling = _file(170 * 30, 20, 30, 1.0)

    with pytest.raises(ChunkOwnershipError, match="chunks"):
        write_file_region(session, GROUP, straddling, chunks={0})

    assert not session.has_uncommitted_changes


def test_a_write_inside_its_chunks_is_the_same_as_without(repo):
    session = repo.writable_session("main")
    blocks = day_blocks(session.store, GROUP)
    ds = _file(170 * 30, 20, 30, 1.0)

    region = write_file_region(session, GROUP, ds, blocks=blocks, chunks={0, 1})

    assert region.epochs == 20
    stored = load_group(session.store, GROUP, drop_empty=True)
    np.testing.assert_array_equal(stored.epoch.values, ds.epoch.values)


@pytest.mark.parametrize(
    ("start_s", "last_s", "expected"),
    [
        (0, 870, {0}),  # a 15-minute file at 30 s: within chunk 0
        (5400, 6270, {1}),  # 01:30, the first epoch of chunk 1
        (5100, 5970, {0, 1}),  # 01:25 to 01:39:30
        (86370, 86370, {15}),  # the last slot of the day
    ],
)
def test_span_chunks_gives_the_chunks_of_a_span_of_the_day(
    repo, start_s, last_s, expected
):
    block = day_blocks(repo.readonly_session("main").store, GROUP)[DAY]
    day = DAY.astype("M8[ns]")
    start = day + np.timedelta64(int(start_s * 1e9), "ns")
    last = day + np.timedelta64(int(last_s * 1e9), "ns")

    assert span_chunks(block, start, last, epoch_chunk=180) == expected
