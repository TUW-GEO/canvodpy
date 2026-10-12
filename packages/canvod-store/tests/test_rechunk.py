"""Verify MyIcechunkStore.rechunk_group() preserves metadata and data integrity.

Motivated by a real-world chunk-misalignment finding (2026-07-08): the default
epoch chunk size (34560) is tuned for 2.5s sampling, but a 5s-sampling site's
daily writes (17280 epochs) land mid-chunk, forcing read-modify-write instead
of clean appends. rechunk_group() is the fix, but had zero test coverage
before this file -- these tests verify it's safe to run against a live
production store (metadata table and root attrs must survive; data must be
byte-identical).
"""

from __future__ import annotations

import numpy as np
import pytest
import xarray as xr
from _helpers import _array_checksum, make_synthetic_dataset, new_gnss_store


@pytest.fixture
def store_with_data(tmp_path):
    """A tmp_store with 4 appended 15-min datasets under one group, plus root attrs."""

    store = new_gnss_store(tmp_path / "rechunk_test_store")
    group = "canopy_01"

    datasets = [make_synthetic_dataset(slot=i) for i in range(4)]
    store.write_initial_group(datasets[0], group)
    for ds in datasets[1:]:
        store.append_to_group(ds, group, action="append")

    store.set_root_attrs({"source_format": "rinex3", "test_marker": "abc123"})

    return store, group, datasets


class TestRechunkGroup:
    """rechunk_group() must preserve everything except the chunk layout."""

    def test_metadata_table_survives_rechunk(self, store_with_data) -> None:
        store, group, _ = store_with_data

        with store.readonly_session() as session:
            before = store.read_metadata_table(session, group)

        store.rechunk_group(group, chunks={"epoch": 360, "sid": -1})

        with store.readonly_session() as session:
            after = store.read_metadata_table(session, group)

        assert before.height == after.height, (
            "metadata table row count changed after rechunk"
        )
        assert before.height > 0, "test setup produced an empty metadata table"
        assert set(before.columns) == set(after.columns)
        # Row content should be identical (order may legitimately differ).
        # Sort on rinex_hash (unique per row) rather than all columns --
        # sorting on free-text/JSON columns (attrs, commit_msg) is fragile
        # to formatting differences that don't reflect real data loss.
        cols = sorted(before.columns)
        before_sorted = before.sort("rinex_hash").select(cols)
        after_sorted = after.sort("rinex_hash").select(cols)
        assert before_sorted.equals(after_sorted), (
            "metadata table content changed after rechunk"
        )

    def test_root_attrs_survive_rechunk(self, store_with_data) -> None:
        store, group, _ = store_with_data

        # Every commit writes its own modification date and snapshot summary.
        per_commit = {"date_modified", "canvod:snapshot_summary"}
        before_attrs = store.get_root_attrs()
        store.rechunk_group(group, chunks={"epoch": 360, "sid": -1})
        after_attrs = store.get_root_attrs()

        assert {k: v for k, v in before_attrs.items() if k not in per_commit} == {
            k: v for k, v in after_attrs.items() if k not in per_commit
        }, "root attrs changed after rechunk"

    def test_data_values_identical_after_rechunk(self, store_with_data) -> None:
        store, group, _ = store_with_data

        with store.readonly_session() as session:
            ds_before = xr.open_zarr(
                session.store, group=group, consolidated=False
            ).load()

        store.rechunk_group(group, chunks={"epoch": 360, "sid": -1})

        with store.readonly_session() as session:
            ds_after = xr.open_zarr(
                session.store, group=group, consolidated=False
            ).load()

        assert set(ds_before.data_vars) == set(ds_after.data_vars)
        for var in ds_before.data_vars:
            after_arr = ds_after[var].sortby("epoch").values
            before_arr_sorted = ds_before[var].sortby("epoch").values
            np.testing.assert_array_equal(
                before_arr_sorted,
                after_arr,
                err_msg=f"data changed after rechunk for variable '{var}'",
            )
            assert _array_checksum(before_arr_sorted) == _array_checksum(after_arr)

        assert ds_before.sizes["epoch"] == ds_after.sizes["epoch"]

    def test_chunk_size_actually_changes(self, store_with_data) -> None:
        store, group, _ = store_with_data

        with store.readonly_session() as session:
            ds_before = xr.open_zarr(session.store, group=group, consolidated=False)
        epoch_axis = ds_before["S1C"].dims.index("epoch")
        chunks_before = ds_before["S1C"].chunks[epoch_axis]

        store.rechunk_group(group, chunks={"epoch": 360, "sid": -1})

        with store.readonly_session() as session:
            ds_after = xr.open_zarr(session.store, group=group, consolidated=False)
        chunks_after = ds_after["S1C"].chunks[epoch_axis]

        assert chunks_after != chunks_before, "chunk layout did not change"
        assert all(c == 360 for c in chunks_after[:-1]), (
            f"expected 360-epoch chunks (except possibly the last), got {chunks_after}"
        )

    def test_other_groups_untouched_by_rechunk(self, tmp_path) -> None:
        """rechunk_group() on one group must not affect a sibling group."""

        store = new_gnss_store(tmp_path / "rechunk_multi_group_store")
        ds_a = make_synthetic_dataset(slot=0)
        ds_b = make_synthetic_dataset(slot=0, seed=99, day="2025-01-02")
        for key in list(ds_a.data_vars) + list(ds_a.coords):
            ds_a[key].encoding.clear()
        for key in list(ds_b.data_vars) + list(ds_b.coords):
            ds_b[key].encoding.clear()

        store.write_initial_group(ds_a, "canopy_01")
        store.write_initial_group(ds_b, "canopy_02")

        with store.readonly_session() as session:
            before_b = xr.open_zarr(
                session.store, group="canopy_02", consolidated=False
            ).load()

        store.rechunk_group("canopy_01", chunks={"epoch": 90, "sid": -1})

        with store.readonly_session() as session:
            after_b = xr.open_zarr(
                session.store, group="canopy_02", consolidated=False
            ).load()
            groups = store.list_groups()

        assert "canopy_02" in groups
        for var in before_b.data_vars:
            np.testing.assert_array_equal(before_b[var].values, after_b[var].values)

    def test_promote_to_main_false_leaves_main_unchanged(self, store_with_data) -> None:
        """With promote_to_main=False, main branch keeps the original chunking."""
        store, group, _ = store_with_data

        with store.readonly_session() as session:
            ds_before = xr.open_zarr(session.store, group=group, consolidated=False)
        epoch_axis = ds_before["S1C"].dims.index("epoch")
        chunks_before = ds_before["S1C"].chunks[epoch_axis]

        store.rechunk_group(
            group,
            chunks={"epoch": 360, "sid": -1},
            promote_to_main=False,
            delete_temp_branch=False,
        )

        with store.readonly_session(branch="main") as session:
            ds_main_after = xr.open_zarr(session.store, group=group, consolidated=False)
        chunks_main_after = ds_main_after["S1C"].chunks[epoch_axis]

        assert chunks_main_after == chunks_before, (
            "main branch chunking changed despite promote_to_main=False"
        )
        assert f"{group}_rechunked_temp" in store.repo.list_branches()


class TestPromoteBranch:
    """promote_branch() never drops commits made to the target meanwhile."""

    def test_moves_target_when_unchanged(self, store_with_data) -> None:
        store, _, _ = store_with_data
        tip = store.repo.lookup_branch("main")
        store.repo.create_branch("staged", tip)
        staged_tip = store.set_root_attrs({"staged": "yes"}, branch="staged")

        assert store.promote_branch("staged", "main", tip) == staged_tip
        assert store.repo.lookup_branch("main") == staged_tip

    def test_refuses_when_target_moved(self, store_with_data) -> None:
        from canvod.store.store import BranchMovedError

        store, _, _ = store_with_data
        tip = store.repo.lookup_branch("main")
        store.repo.create_branch("staged", tip)
        store.set_root_attrs({"staged": "yes"}, branch="staged")
        moved_tip = store.set_root_attrs({"other_writer": "yes"}, branch="main")

        with pytest.raises(BranchMovedError, match="moved"):
            store.promote_branch("staged", "main", tip)

        assert store.repo.lookup_branch("main") == moved_tip
        assert "staged" in store.repo.list_branches()

    def test_rechunk_keeps_concurrent_commit(
        self, store_with_data, monkeypatch
    ) -> None:
        """A commit to main during a rechunk survives; the rechunk is refused."""
        from canvod.store.store import BranchMovedError

        store, group, _ = store_with_data
        write = store._to_icechunk_throttled

        def write_after_other_writer(*args, **kwargs):
            store.set_root_attrs({"other_writer": "yes"}, branch="main")
            return write(*args, **kwargs)

        monkeypatch.setattr(store, "_to_icechunk_throttled", write_after_other_writer)

        with pytest.raises(BranchMovedError):
            store.rechunk_group(group, chunks={"epoch": 360, "sid": -1})

        assert store.get_root_attrs()["other_writer"] == "yes"
        assert f"{group}_rechunked_temp" in store.repo.list_branches()

    def test_rechunk_refuses_existing_temp_branch(self, store_with_data) -> None:
        store, group, _ = store_with_data
        store.repo.create_branch(
            f"{group}_rechunked_temp", store.repo.lookup_branch("main")
        )

        with pytest.raises(ValueError, match="already exists"):
            store.rechunk_group(group, chunks={"epoch": 360, "sid": -1})
