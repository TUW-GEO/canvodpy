"""Growing a store's day blocks in one small commit per batch (ADR 0016)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import xarray as xr
from _helpers import new_gnss_store
from canvod.store_metadata.io import commit_with_rebase

from canvod.store import MyIcechunkStore
from canvod.store.day_blocks import (
    LayoutError,
    add_day_block,
    day_blocks,
    write_file_region,
)

GROUP = "canopy_01"
SIDS = ["G01|L1|C", "G02|L1|C"]
DAY_1 = np.datetime64("2025-01-01", "D")
DAY_2 = np.datetime64("2025-01-02", "D")
DAY_3 = np.datetime64("2025-01-03", "D")


def _template(day: np.datetime64) -> xr.Dataset:
    epochs = day.astype("M8[ns]") + np.arange(3) * np.timedelta64(5, "s")
    return xr.Dataset(
        {"SNR": (("epoch", "sid"), np.ones((3, len(SIDS)), dtype="f4"))},
        coords={"epoch": ("epoch", epochs, {"time_system": "GPS"}), "sid": SIDS},
    )


def _row(region) -> dict:
    return {
        "fname": "/data/a.rnx",
        "rinex_hash": "a",
        "start": region.start,
        "end": region.end,
        "epochs": region.epochs,
        "dataset_attrs": "{}",
        "exists": False,
        "rel_path": "data/a.rnx",
        "canonical_name": "",
        "physical_path": "/data/a.rnx",
        "action": "initial",
        "write_strategy": "skip",
        "run_id": "run-1",
        "commit_msg": "first day",
        "snapshot_id": "",
    }


@pytest.fixture
def store(tmp_path: Path) -> MyIcechunkStore:
    """A store whose group holds one file of DAY_1, with its log-book row."""
    path = tmp_path / "gnss_store"
    path.mkdir()
    store = new_gnss_store(path)
    ds = _template(DAY_1)
    with store.writable_session("main") as session:
        add_day_block(session, GROUP, DAY_1, 5, template=ds)
        region = write_file_region(session, GROUP, ds)
        store.append_metadata_bulk(GROUP, [_row(region)], session=session)
        commit_with_rebase(
            session, "first day", store_path=store.store_path, config=store.settings
        )
    return store


def _blocks(store: MyIcechunkStore) -> dict:
    with store.readonly_session("main") as session:
        return day_blocks(session.store, GROUP)


def _snapshots(store: MyIcechunkStore) -> int:
    return len(list(store.repo.ancestry(branch="main")))


def test_growth_adds_the_days_of_a_batch_in_one_commit(store) -> None:
    before = _snapshots(store)

    snapshot = store.grow_day_blocks({GROUP: {DAY_2: 5, DAY_3: 1}}, message="grow")

    assert snapshot is not None
    assert _snapshots(store) == before + 1
    blocks = _blocks(store)
    assert set(blocks) == {DAY_1, DAY_2, DAY_3}
    assert blocks[DAY_2].cadence_s == 5
    assert blocks[DAY_3].cadence_s == 1


def test_days_that_have_a_block_keep_it_and_nothing_is_committed(store) -> None:
    before = _snapshots(store)
    first = _blocks(store)[DAY_1]

    assert store.grow_day_blocks({GROUP: {DAY_1: 5}}, message="grow") is None

    assert _snapshots(store) == before
    assert _blocks(store)[DAY_1] == first


def test_growth_refuses_a_group_that_does_not_exist(store) -> None:
    with pytest.raises(LayoutError, match="canopy_02"):
        store.grow_day_blocks({"canopy_02": {DAY_2: 5}}, message="grow")


def test_a_growth_conflict_is_retried_and_ends_with_one_block_per_day(
    store, monkeypatch
) -> None:
    """Another run grows DAY_2 after this one opened its session."""
    rival = MyIcechunkStore(store.store_path)
    opened = store.repo.writable_session
    raced = []

    def writable_session(branch: str):
        session = opened(branch)
        if not raced:
            raced.append(True)
            rival.grow_day_blocks({GROUP: {DAY_2: 5}}, message="rival")
        return session

    monkeypatch.setattr(store.repo, "writable_session", writable_session)

    store.grow_day_blocks({GROUP: {DAY_2: 5, DAY_3: 5}}, message="grow")

    blocks = _blocks(store)
    assert set(blocks) == {DAY_1, DAY_2, DAY_3}
    with store.readonly_session("main") as session:
        epochs = xr.open_zarr(session.store, group=GROUP, consolidated=False).epoch
    assert epochs.size == 3 * 17280
