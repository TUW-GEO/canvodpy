"""Tests for MyIcechunkStore's cross-group fork/merge VOD batch write path.

`write_or_append_vod_groups_batch` extends the same cross-group
parallelization `RinexDataProcessor._write_receiver_batch_forked` uses for
GNSS receiver groups (see
`canvodpy/tests/test_cross_group_batch_write.py`) to VOD analysis groups.

Note on commit count -- simpler than the GNSS case, not the same: a VOD
write is exactly one dataset per group per call (not many files per group
per day), so a brand-new group's pre-pass write *is* its entire
contribution to the batch -- there's never leftover data to append via a
fork afterward. A batch of only brand-new groups costs exactly one commit
(the pre-pass alone, no fork/merge phase). A batch of only pre-existing
groups also costs exactly one commit (the fork/merge phase alone, no
pre-pass). Only a *mixed* batch costs two.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from _helpers import make_synthetic_vod_dataset, new_vod_store

from canvod.store import MyIcechunkStore
from canvod.store.store import VodWriteItem


@pytest.fixture
def store(tmp_path: Path) -> MyIcechunkStore:
    store_path = tmp_path / "throwaway_vod_store"
    store_path.mkdir()
    return new_vod_store(store_path)


def _item(
    group_name: str,
    slot: int,
    day: str = "2025-03-28",
    source_id: str = "src",
) -> VodWriteItem:
    ds = make_synthetic_vod_dataset(slot=slot, day=day, seed=hash(source_id) % 1000)
    return VodWriteItem(
        group_name=group_name,
        dataset=ds,
        source_file_hashes={"canopy_01": f"hash_{source_id}"},
        source_gnss_stores={"canopy_01": "/fake/gnss_store"},
        calculator_name="tau_omega",
        commit_message=f"VOD {group_name} {source_id}",
    )


def test_case_a_steady_state_appends_to_two_pre_existing_groups(
    store: MyIcechunkStore,
) -> None:
    """Two pre-existing VOD groups, appended to concurrently in one batch."""
    store.write_or_append_vod_groups_batch(
        [
            _item("tau_omega/canopy_01_vs_reference_01", slot=0, source_id="seed_a"),
            _item("tau_omega/canopy_02_vs_reference_01", slot=0, source_id="seed_b"),
        ]
    )
    # list_groups() only enumerates top-level Zarr group keys -- both
    # analysis groups nest under the shared "tau_omega" calculator group.
    assert set(store.list_groups() or []) == {"tau_omega"}
    assert store.group_exists("tau_omega/canopy_01_vs_reference_01")
    assert store.group_exists("tau_omega/canopy_02_vs_reference_01")

    n_snapshots_before = len(list(store.repo.ancestry(branch="main")))
    results = store.write_or_append_vod_groups_batch(
        [
            _item("tau_omega/canopy_01_vs_reference_01", slot=1, source_id="day2_a"),
            _item("tau_omega/canopy_02_vs_reference_01", slot=1, source_id="day2_b"),
        ]
    )
    n_snapshots_after = len(list(store.repo.ancestry(branch="main")))

    assert n_snapshots_after == n_snapshots_before + 1, (
        "a batch touching only pre-existing groups must be exactly one "
        "shared commit, not one per group"
    )
    assert results["tau_omega/canopy_01_vs_reference_01"].written
    assert results["tau_omega/canopy_02_vs_reference_01"].written

    ds1 = store.read_group("tau_omega/canopy_01_vs_reference_01").compute()
    assert ds1.sizes["epoch"] == 360  # seed(180) + append(180)
    assert store.metadata_row_count("tau_omega/canopy_01_vs_reference_01") == 2
    assert store.metadata_row_count("tau_omega/canopy_02_vs_reference_01") == 2


def test_case_b_new_groups_pre_pass_only_no_fork_needed(
    store: MyIcechunkStore,
) -> None:
    """A batch of only brand-new VOD groups costs exactly one commit.

    Unlike the GNSS receiver-group case, there's no "remaining data" left
    to fork/merge afterward -- the pre-pass write of the (only) dataset per
    group is that group's entire contribution to the batch.
    """
    n_snapshots_before = len(list(store.repo.ancestry(branch="main")))
    results = store.write_or_append_vod_groups_batch(
        [
            _item("tau_omega/canopy_01_vs_reference_01", slot=0, source_id="a"),
            _item("tau_omega/canopy_02_vs_reference_01", slot=0, source_id="b"),
        ]
    )
    n_snapshots_after = len(list(store.repo.ancestry(branch="main")))

    assert n_snapshots_after == n_snapshots_before + 1, (
        "a batch creating only brand-new VOD groups must cost exactly one "
        "commit (the pre-pass alone) -- there's no fork/merge phase since "
        "nothing is left to append afterward"
    )
    # list_groups() only enumerates top-level Zarr group keys -- both
    # analysis groups nest under the shared "tau_omega" calculator group.
    assert set(store.list_groups() or []) == {"tau_omega"}
    assert store.group_exists("tau_omega/canopy_01_vs_reference_01")
    assert store.group_exists("tau_omega/canopy_02_vs_reference_01")
    assert results["tau_omega/canopy_01_vs_reference_01"].written
    assert results["tau_omega/canopy_01_vs_reference_01"].snapshot_id is not None
    assert results["tau_omega/canopy_02_vs_reference_01"].snapshot_id is not None
    assert store.metadata_row_count("tau_omega/canopy_01_vs_reference_01") == 1
    assert store.metadata_row_count("tau_omega/canopy_02_vs_reference_01") == 1


def test_case_mixed_new_and_existing_costs_two_commits(
    store: MyIcechunkStore,
) -> None:
    """One new group + one pre-existing group in the same batch: two commits.

    The pre-pass (new group) must commit on its own clean session before
    the fork/merge phase (existing group) opens a fresh one -- empirically,
    `Session.merge()` silently drops a fork's data if the base session had
    its own pending uncommitted writes before `.fork()` was called (see
    `write_or_append_vod_groups_batch`'s docstring).
    """
    store.write_or_append_vod_groups_batch(
        [_item("tau_omega/canopy_01_vs_reference_01", slot=0, source_id="seed")]
    )
    n_snapshots_before = len(list(store.repo.ancestry(branch="main")))

    results = store.write_or_append_vod_groups_batch(
        [
            _item("tau_omega/canopy_01_vs_reference_01", slot=1, source_id="day2"),
            _item("tau_omega/canopy_02_vs_reference_01", slot=0, source_id="new"),
        ]
    )
    n_snapshots_after = len(list(store.repo.ancestry(branch="main")))

    assert n_snapshots_after == n_snapshots_before + 2
    assert results["tau_omega/canopy_01_vs_reference_01"].written
    assert results["tau_omega/canopy_02_vs_reference_01"].written
    ds1 = store.read_group("tau_omega/canopy_01_vs_reference_01").compute()
    assert ds1.sizes["epoch"] == 360
    ds2 = store.read_group("tau_omega/canopy_02_vs_reference_01").compute()
    assert ds2.sizes["epoch"] == 180


def test_dedup_skips_identical_source_hash(store: MyIcechunkStore) -> None:
    """Re-submitting the exact same source-hash combination is skipped."""
    item = _item("tau_omega/canopy_01_vs_reference_01", slot=0, source_id="dup")
    store.write_or_append_vod_groups_batch([item])
    n_snapshots_before = len(list(store.repo.ancestry(branch="main")))

    item_again = _item("tau_omega/canopy_01_vs_reference_01", slot=0, source_id="dup")
    results = store.write_or_append_vod_groups_batch([item_again])
    n_snapshots_after = len(list(store.repo.ancestry(branch="main")))

    assert n_snapshots_after == n_snapshots_before, "duplicate write must not commit"
    assert results["tau_omega/canopy_01_vs_reference_01"].written is False
    assert results["tau_omega/canopy_01_vs_reference_01"].skip_reason == "hash_match"


def test_case_fail_fast_no_partial_merge(
    store: MyIcechunkStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If one group's forked write raises, nothing merges or commits."""
    store.write_or_append_vod_groups_batch(
        [
            _item("tau_omega/canopy_01_vs_reference_01", slot=0, source_id="seed_a"),
            _item("tau_omega/canopy_02_vs_reference_01", slot=0, source_id="seed_b"),
        ]
    )
    n_snapshots_before = len(list(store.repo.ancestry(branch="main")))

    real_write = MyIcechunkStore._write_vod_into_fork

    def _boom(self: MyIcechunkStore, fork_session, plan):
        if plan.item.group_name == "tau_omega/canopy_02_vs_reference_01":
            raise RuntimeError("simulated mid-batch failure")
        return real_write(self, fork_session, plan)

    monkeypatch.setattr(MyIcechunkStore, "_write_vod_into_fork", _boom)

    with pytest.raises(RuntimeError, match="simulated mid-batch failure"):
        store.write_or_append_vod_groups_batch(
            [
                _item(
                    "tau_omega/canopy_01_vs_reference_01", slot=1, source_id="day2_a"
                ),
                _item(
                    "tau_omega/canopy_02_vs_reference_01", slot=1, source_id="day2_b"
                ),
            ]
        )

    n_snapshots_after = len(list(store.repo.ancestry(branch="main")))
    assert n_snapshots_after == n_snapshots_before, "no commit must land on failure"

    ds1 = store.read_group("tau_omega/canopy_01_vs_reference_01").compute()
    assert ds1.sizes["epoch"] == 180  # still just the seed
    ds2 = store.read_group("tau_omega/canopy_02_vs_reference_01").compute()
    assert ds2.sizes["epoch"] == 180  # still just the seed


def test_log_book_rows_match_their_commit(store: MyIcechunkStore) -> None:
    """Every log-book row records the message and run_id of its commit.

    Covers the pre-pass (new group) and the fork/merge phase (existing
    group) in one mixed batch, inside a run context.
    """
    from canvod.utils.logging import reset_run_id, set_run_id

    store.write_or_append_vod_groups_batch(
        [_item("tau_omega/canopy_01_vs_reference_01", slot=0, source_id="seed")]
    )
    token = set_run_id("TestSite-20260930-120000")
    try:
        store.write_or_append_vod_groups_batch(
            [
                _item("tau_omega/canopy_01_vs_reference_01", slot=1, source_id="d2"),
                _item("tau_omega/canopy_02_vs_reference_01", slot=0, source_id="n"),
            ]
        )
    finally:
        reset_run_id(token)

    snapshots = list(store.repo.ancestry(branch="main"))
    messages = {s.message for s in snapshots}
    with store.readonly_session("main") as session:
        for group in (
            "tau_omega/canopy_01_vs_reference_01",
            "tau_omega/canopy_02_vs_reference_01",
        ):
            rows = store.read_metadata_table(session, group)
            assert set(rows["commit_msg"]) <= messages, group
    assert rows["run_id"].to_list() == ["TestSite-20260930-120000"]

    append_commit = next(s for s in snapshots if s.message.startswith("[v"))
    assert append_commit.message.endswith("(run=TestSite-20260930-120000)")
    assert "d2" in append_commit.message
    assert append_commit.metadata["groups"] == "tau_omega/canopy_01_vs_reference_01"
    assert "hash_d2" in append_commit.metadata["source_file_hashes"]
