"""Growing a store's day blocks in one small commit per batch (ADR 0016)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import xarray as xr
from _helpers import new_gnss_store
from canvod.store_metadata import io
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


def _racing(store, monkeypatch, races: int) -> list[float]:
    """Another run grows a day of its own before each of ``races`` sessions."""
    sleeps: list[float] = []
    monkeypatch.setattr(io.time, "sleep", sleeps.append)
    rival = MyIcechunkStore(store.store_path)
    opened = store.repo.writable_session
    rival_days = iter(DAY_3 + np.arange(1, races + 1))

    def writable_session(branch: str):
        session = opened(branch)
        day = next(rival_days, None)
        if day is not None:
            rival.grow_day_blocks({GROUP: {day: 5}}, message="rival")
        return session

    monkeypatch.setattr(store.repo, "writable_session", writable_session)
    return sleeps


def test_a_growth_that_lost_four_conflicts_wins_the_fifth(store, monkeypatch) -> None:
    sleeps = _racing(store, monkeypatch, races=4)

    store.grow_day_blocks({GROUP: {DAY_2: 5}}, message="grow")

    assert DAY_2 in _blocks(store)
    assert len(sleeps) == 4
    assert all(a < b for a, b in zip(sleeps, sleeps[1:], strict=False))


def test_a_growth_that_loses_five_conflicts_fails(store, monkeypatch) -> None:
    sleeps = _racing(store, monkeypatch, races=5)

    with pytest.raises(RuntimeError, match="conflicted 5 times"):
        store.grow_day_blocks({GROUP: {DAY_2: 5}}, message="grow")
    assert len(sleeps) == 4


# ── A grow keeps the snapshot summary (ADR 0014) ─────────────────────────────

REFERENCE = "reference_01_canopy_01"
NEW_YEARS_EVE = np.datetime64("2025-12-31", "D")


def _row_for(region, name: str) -> dict:
    return {**_row(region), "fname": f"/data/{name}", "rinex_hash": name}


@pytest.fixture
def two_receivers(tmp_path: Path) -> MyIcechunkStore:
    """Canopy and reference, each with one file of the last day of 2025."""
    path = tmp_path / "gnss_store"
    path.mkdir()
    store = new_gnss_store(path)
    ds = _template(NEW_YEARS_EVE)
    with store.writable_session("main") as session:
        for group in (GROUP, REFERENCE):
            add_day_block(session, group, NEW_YEARS_EVE, 5, template=ds)
            region = write_file_region(session, group, ds)
            store.append_metadata_bulk(
                group, [_row_for(region, f"{group}.rnx")], session=session
            )
        commit_with_rebase(
            session, "last day", store_path=store.store_path, config=store.settings
        )
    return store


def _root_attrs(store: MyIcechunkStore) -> dict:
    import zarr

    with store.readonly_session("main") as session:
        return dict(zarr.open_group(session.store, mode="r").attrs)


def _recomputed_summary(store: MyIcechunkStore, committed_at: str) -> dict:
    import zarr
    from canvod.store_metadata.snapshot import snapshot_summary

    with store.readonly_session("main") as session:
        root = zarr.open_group(session.store, mode="r")
        return snapshot_summary(root, store.repo.get_metadata(), committed_at)


def test_a_grow_keeps_the_summary_a_recompute_gives(two_receivers) -> None:
    from canvod.store_metadata.snapshot import SNAPSHOT_SUMMARY_ATTR

    store = two_receivers
    before = _root_attrs(store)

    store.grow_day_blocks(
        {
            GROUP: {DAY_1 + 365: 5, DAY_2 + 365: 5},  # into 2026
            REFERENCE: {DAY_1 + 365: 5},
        },
        message="grow",
    )

    after = _root_attrs(store)
    kept = after[SNAPSHOT_SUMMARY_ATTR]
    updated = kept["temporal"]["updated"]
    assert kept == _recomputed_summary(store, updated)
    assert set(kept["receivers"]) == {"canopy_01", "reference_01"}
    assert kept["receivers"]["reference_01"]  # its epochs, sids, range
    assert kept["temporal"]["collected_end"].startswith("2025-12-31")
    # The snapshot changed, so its modification date did.
    assert updated != before[SNAPSHOT_SUMMARY_ATTR]["temporal"]["updated"]
    assert after["date_modified"] == updated


def test_keeping_the_summary_refuses_a_commit_that_writes_data(two_receivers) -> None:
    store = two_receivers
    ds = _template(NEW_YEARS_EVE)
    with store.writable_session("main") as session:
        write_file_region(session, GROUP, ds.assign(SNR=ds.SNR * 2))
        with pytest.raises(ValueError, match="SNR"):
            commit_with_rebase(
                session,
                "data",
                store_path=store.store_path,
                config=store.settings,
                keep_summary=True,
            )


def test_keeping_the_summary_refuses_a_root_without_one(two_receivers) -> None:
    import zarr
    from canvod.store_metadata.snapshot import SNAPSHOT_SUMMARY_ATTR

    store = two_receivers
    # A snapshot whose root has no summary, as an old store's would be.
    session = store.repo.writable_session("main")
    root = zarr.open_group(session.store, mode="a")
    root.attrs.put({k: v for k, v in root.attrs.items() if k != SNAPSHOT_SUMMARY_ATTR})
    session.commit("drop the summary")

    with store.writable_session("main") as session:
        add_day_block(session, GROUP, DAY_1 + 365, 5, template=None)
        with pytest.raises(ValueError, match="no snapshot summary"):
            commit_with_rebase(
                session,
                "grow",
                store_path=store.store_path,
                config=store.settings,
                keep_summary=True,
            )


def _refused_keeping_the_summary(store: MyIcechunkStore, change, match: str) -> None:
    """``change(session)`` then a commit keeping the summary: refused."""
    with store.writable_session("main") as session:
        change(session)
        with pytest.raises(ValueError, match=match):
            commit_with_rebase(
                session,
                "grow",
                store_path=store.store_path,
                config=store.settings,
                keep_summary=True,
            )


def _group(session, path: str = GROUP):
    import zarr

    return zarr.open_group(session.store, mode="r+", path=path)


@pytest.mark.parametrize(
    "rewrite",
    [
        pytest.param(
            lambda attrs: attrs["day_block_index"]["2025-12-31"].update(
                cadence_ns=attrs["day_block_index"]["2025-12-31"]["cadence_ns"] * 2
            ),
            id="an existing day's block",
        ),
        pytest.param(
            lambda attrs: attrs.update(epoch_layout="append"), id="the layout"
        ),
    ],
)
def test_keeping_the_summary_refuses_a_changed_block_index(
    two_receivers, rewrite
) -> None:
    def change(session) -> None:
        add_day_block(session, GROUP, DAY_1 + 365, 5, template=None)
        group = _group(session)
        attrs = dict(group.attrs)
        rewrite(attrs)
        group.attrs.put(attrs)

    _refused_keeping_the_summary(two_receivers, change, GROUP)


def test_keeping_the_summary_refuses_epochs_of_an_appending_group(
    two_receivers,
) -> None:
    import zarr

    store = two_receivers
    # A group written by appending: no day-block layout in its attributes.
    session = store.repo.writable_session("main")
    zarr.open_group(session.store, mode="a").create_group("appended").create_array(
        "epoch", shape=(4,), chunks=(4,), dtype="i8", dimension_names=["epoch"]
    )[:] = np.arange(4)
    session.commit("an appending group")

    def change(session) -> None:
        _group(session, "appended")["epoch"][:] = np.arange(4) + 10

    _refused_keeping_the_summary(store, change, "chunks of /appended/epoch")


@pytest.mark.parametrize(
    "rewrite",
    [
        pytest.param(
            lambda epoch: epoch.attrs.update(units="seconds since 2000-01-01"),
            id="the epoch units",
        ),
        pytest.param(
            lambda epoch: epoch.resize((epoch.shape[0] - 1,)),
            id="a shrunk epoch axis",
        ),
    ],
)
def test_keeping_the_summary_refuses_changed_array_metadata(
    two_receivers, rewrite
) -> None:
    def change(session) -> None:
        rewrite(_group(session)["epoch"])

    _refused_keeping_the_summary(two_receivers, change, f"the array {GROUP}/epoch")


def test_keeping_the_summary_refuses_new_repository_metadata(two_receivers) -> None:
    store = two_receivers

    def change(session) -> None:
        add_day_block(session, GROUP, DAY_1 + 365, 5, template=None)

    with store.writable_session("main") as session:
        change(session)
        with pytest.raises(ValueError, match="changes the repository metadata"):
            commit_with_rebase(
                session,
                "grow",
                store_path=store.store_path,
                config=store.settings,
                repository=store.repo.get_metadata(),
                keep_summary=True,
            )
