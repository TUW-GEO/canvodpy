"""Moving a store written by appending to day blocks (#279, ADR 0016)."""

from __future__ import annotations

from pathlib import Path

import icechunk
import numpy as np
import pytest
import xarray as xr
import zarr
from _helpers import (
    make_synthetic_dataset,
    make_synthetic_vod_dataset,
    new_gnss_store,
    new_vod_store,
)
from canvod.store_metadata.layout import (
    DAY_BLOCK_INDEX_ATTR,
    LayoutError,
    is_day_block_group,
)
from canvod.store_metadata.summary import summarize_store

from canvod.store import MyIcechunkStore, open_gnss_store, open_vod_store
from canvod.store.day_blocks import day_blocks
from canvod.store.migrate_layout import (
    INDEX,
    NOTHING,
    REWRITE,
    migrate_layout,
    plan_layout_migration,
)
from canvod.store.store import VodWriteItem

GROUP = "canopy_01"
VOD_GROUP = "tau_omega/canopy_01_vs_reference_01"


def _snapshots(store: MyIcechunkStore) -> int:
    return len(list(store.repo.ancestry(branch="main")))


def _attrs(store: MyIcechunkStore, group: str) -> dict:
    with store.readonly_session("main") as session:
        return dict(zarr.open_group(session.store, mode="r", path=group).attrs)


def _blocks(store: MyIcechunkStore, group: str) -> dict:
    with store.readonly_session("main") as session:
        return day_blocks(session.store, group)


def _log_epochs(store: MyIcechunkStore, group: str) -> list[int]:
    with store.readonly_session("main") as session:
        table = zarr.open_group(session.store, mode="r", path=f"{group}/metadata/table")
        return np.asarray(table["epochs"][...]).tolist()


@pytest.fixture
def appended(tmp_path: Path) -> tuple[MyIcechunkStore, xr.Dataset, xr.Dataset]:
    """A GNSS group written by appending: days out of order, a file twice.

    The second day's file first, then the first day's file, then the
    first day's file again with other values. Returns the store and the
    data the group holds, the later entry of each epoch.
    """
    store = new_gnss_store(tmp_path / "gnss_store")
    later = make_synthetic_dataset(slot=4, day="2025-01-02")
    first = make_synthetic_dataset(slot=0, day="2025-01-01")
    again = make_synthetic_dataset(slot=0, seed=7, day="2025-01-01")
    store.write_initial_group(later, GROUP)
    store.append_to_group(first, GROUP, action="append")
    store.append_to_group(again, GROUP, action="overwrite")
    assert not is_day_block_group(_attrs(store, GROUP))
    return store, again, later


def test_plan_reads_without_writing(appended) -> None:
    store, _, _ = appended
    before = _snapshots(store)

    (plan,) = plan_layout_migration(store.store_path)

    assert plan.action == REWRITE
    assert plan.epochs == 360
    assert plan.duplicates == 180
    assert plan.cadences == {
        np.datetime64("2025-01-01"): 5.0,
        np.datetime64("2025-01-02"): 5.0,
    }
    assert _snapshots(store) == before


def test_appended_group_becomes_day_blocks_in_one_commit(appended) -> None:
    store, again, later = appended
    before = _snapshots(store)
    attrs = _attrs(store, GROUP)

    result = migrate_layout(store.store_path, config=store.settings)

    assert result.snapshot_id is not None
    assert _snapshots(store) == before + 1
    (plan,) = result.groups
    assert plan.action == REWRITE
    assert plan.unlogged == 0
    moved = _attrs(store, GROUP)
    assert is_day_block_group(moved)
    assert DAY_BLOCK_INDEX_ATTR in moved
    for key, value in attrs.items():
        assert moved[key] == value
    blocks = _blocks(store, GROUP)
    assert sorted(str(day) for day in blocks) == ["2025-01-01", "2025-01-02"]
    assert {block.cadence_s for block in blocks.values()} == {5.0}


def test_moved_group_holds_the_last_written_entry_of_each_epoch(appended) -> None:
    store, again, later = appended
    migrate_layout(store.store_path, config=store.settings)

    read = open_gnss_store(store.store_path).read_group(GROUP, drop_empty=True)
    expected = xr.concat([again, later], dim="epoch")

    np.testing.assert_array_equal(
        read.epoch.values, expected.epoch.values.astype("M8[ns]")
    )
    for name in ("S1C", "S2W"):
        np.testing.assert_array_equal(read[name].values, expected[name].values)


def test_log_book_and_metadata_stay(appended) -> None:
    store, _, _ = appended
    rows = store.metadata_row_count(GROUP)

    migrate_layout(store.store_path, config=store.settings)

    moved = open_gnss_store(store.store_path)
    assert moved.metadata_row_count(GROUP) == rows
    # The file of the second day, the first file of the first day (all its
    # epochs written again later) and the one written again.
    assert _log_epochs(moved, GROUP) == [180, 0, 180]


def test_summary_counts_each_epoch_once(appended) -> None:
    store, _, _ = appended
    migrate_layout(store.store_path, config=store.settings)

    assert summarize_store(store.store_path)["summaries.total_epochs"] == 360


def test_a_moved_store_is_left_as_it_is(appended) -> None:
    store, _, _ = appended
    migrate_layout(store.store_path, config=store.settings)
    before = _snapshots(store)

    result = migrate_layout(store.store_path, config=store.settings)

    assert result.snapshot_id is None
    assert [plan.action for plan in result.groups] == [NOTHING]
    assert _snapshots(store) == before


def _vod_item(day: str, seed: int = 0) -> VodWriteItem:
    return VodWriteItem(
        group_name=VOD_GROUP,
        dataset=make_synthetic_vod_dataset(slot=0, day=day, seed=seed),
        source_file_hashes={"canopy_01": f"hash_{day}_{seed}"},
        source_gnss_stores={"canopy_01": "/fake/gnss_store"},
        calculator_name="tau_omega",
        commit_message=f"VOD {day}",
    )


def test_vod_store_is_moved(tmp_path: Path) -> None:
    store = new_vod_store(tmp_path / "vod_store")
    items = [_vod_item("2025-03-29"), _vod_item("2025-03-28")]
    for item in items:
        store.write_or_append_vod_groups_batch([item])
    assert not is_day_block_group(_attrs(store, VOD_GROUP))

    result = migrate_layout(store.store_path, config=store.settings)

    (plan,) = result.groups
    assert plan.action == REWRITE
    assert plan.unlogged == 0
    moved = open_vod_store(store.store_path)
    read = moved.read_group(VOD_GROUP, drop_empty=True)
    expected = xr.concat([items[1].dataset, items[0].dataset], dim="epoch")
    np.testing.assert_array_equal(read.epoch.values, expected.epoch.values)
    np.testing.assert_array_equal(read["VOD"].values, expected["VOD"].values)
    assert summarize_store(store.store_path)["summaries.total_epochs"] == 360


def test_day_blocks_without_index_get_it(tmp_path: Path) -> None:
    """A group of a development version: whole-day blocks, no index."""
    store = new_vod_store(tmp_path / "vod_store")
    item = _vod_item("2025-03-28")
    item.cadences = {np.datetime64("2025-03-28", "D"): 5.0}
    store.write_or_append_vod_groups_batch([item])
    index = _attrs(store, VOD_GROUP)[DAY_BLOCK_INDEX_ATTR]
    with store.writable_session("main") as session:
        group = zarr.open_group(session.store, mode="r+", path=VOD_GROUP)
        del group.attrs[DAY_BLOCK_INDEX_ATTR]
        session.commit("Fangorn drops the block index")
    with store.readonly_session("main") as session:
        data = xr.open_zarr(session.store, group=VOD_GROUP, consolidated=False)
        stored = data["VOD"].values

    result = migrate_layout(store.store_path, config=store.settings)

    assert [plan.action for plan in result.groups] == [INDEX]
    assert _attrs(store, VOD_GROUP)[DAY_BLOCK_INDEX_ATTR] == index
    with store.readonly_session("main") as session:
        data = xr.open_zarr(session.store, group=VOD_GROUP, consolidated=False)
        np.testing.assert_array_equal(data["VOD"].values, stored)


def test_store_without_repository_metadata_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "bare_store"
    icechunk.Repository.create(icechunk.local_filesystem_storage(str(path)))

    with pytest.raises(ValueError, match="migrate-metadata"):
        migrate_layout(path, config={})


def test_each_day_keeps_its_cadence(tmp_path: Path) -> None:
    """A cadence that divides no day into whole chunks (7 s) is padded."""
    store = new_gnss_store(tmp_path / "gnss_store")
    five = make_synthetic_dataset(slot=0, day="2025-01-01")
    seven = make_synthetic_dataset(slot=0, day="2025-01-02")
    seven = seven.assign_coords(
        epoch=seven.epoch.values[0] + np.arange(180) * np.timedelta64(7, "s")
    )
    seven.epoch.attrs["time_system"] = "GPS"
    store.write_initial_group(five, GROUP)
    store.append_to_group(seven, GROUP, action="append")

    migrate_layout(store.store_path, config=store.settings)

    blocks = _blocks(store, GROUP)
    assert [blocks[day].cadence_s for day in sorted(blocks)] == [5.0, 7.0]
    read = open_gnss_store(store.store_path).read_group(GROUP, drop_empty=True)
    expected = xr.concat([five, seven], dim="epoch")
    np.testing.assert_array_equal(
        read.epoch.values, expected.epoch.values.astype("M8[ns]")
    )
    np.testing.assert_array_equal(read["S1C"].values, expected["S1C"].values)


def test_a_moved_group_is_never_written_again_as_a_whole(appended) -> None:
    """``rewrite_group`` would drop the layout and the block index."""
    store, again, _ = appended
    migrate_layout(store.store_path, config=store.settings)
    moved = open_gnss_store(store.store_path)

    with (
        moved.writable_session("main") as session,
        pytest.raises(LayoutError, match="day blocks"),
    ):
        moved.rewrite_group(session, GROUP, again, [])
