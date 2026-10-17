"""VOD results written as day blocks (#276, ADR 0016).

A VOD write item with ``cadences`` goes into the day blocks of its group:
one slot per epoch of the day at the cadence of the GNSS data, the whole
batch in one commit, and a day written again replaces what it held.
"""

from __future__ import annotations

import unittest.mock
from pathlib import Path

import numpy as np
import pytest
import xarray as xr
from _helpers import make_synthetic_vod_dataset, new_vod_store
from canvod.store_metadata.layout import LayoutError
from canvod.store_metadata.summary import summarize_store

from canvod.store import MyIcechunkStore
from canvod.store.day_blocks import day_blocks, drop_empty_slots
from canvod.store.manager import GnssResearchSite
from canvod.store.store import VodWriteItem

GROUP = "tau_omega/canopy_01_vs_reference_01"
OTHER = "tau_omega/canopy_02_vs_reference_01"
DAY = "2025-03-28"
CADENCE_S = 5.0


@pytest.fixture
def store(tmp_path: Path) -> MyIcechunkStore:
    store_path = tmp_path / "vod_store"
    store_path.mkdir()
    return new_vod_store(store_path)


def _item(
    group_name: str,
    slot: int,
    source_id: str,
    day: str = DAY,
    seed: int = 0,
) -> VodWriteItem:
    ds = make_synthetic_vod_dataset(slot=slot, day=day, seed=seed)
    return VodWriteItem(
        group_name=group_name,
        dataset=ds,
        source_file_hashes={"canopy_01": f"hash_{source_id}"},
        source_gnss_stores={"canopy_01": "/fake/gnss_store"},
        calculator_name="tau_omega",
        commit_message=f"VOD {group_name} {source_id}",
        cadences={np.datetime64(day, "D"): CADENCE_S},
    )


def _snapshots(store: MyIcechunkStore) -> int:
    return len(list(store.repo.ancestry(branch="main")))


def _blocks(store: MyIcechunkStore, group: str) -> dict:
    with store.readonly_session("main") as session:
        return day_blocks(session.store, group)


def test_batch_is_one_commit_into_day_blocks(store: MyIcechunkStore) -> None:
    """Two new groups, one day each: one commit, a block of a full day each."""
    before = _snapshots(store)
    results = store.write_or_append_vod_groups_batch(
        [_item(GROUP, slot=0, source_id="a"), _item(OTHER, slot=0, source_id="b")]
    )

    assert _snapshots(store) == before + 1
    assert results[GROUP].written
    assert results[OTHER].written
    for group in (GROUP, OTHER):
        (block,) = _blocks(store, group).values()
        assert block.cadence_s == CADENCE_S
        assert block.stop - block.start == 86400 / CADENCE_S
        assert store.metadata_row_count(group) == 1


def test_written_values_read_back_without_empty_slots(
    store: MyIcechunkStore,
) -> None:
    """Apart from the empty slots, the group holds exactly the result."""
    item = _item(GROUP, slot=2, source_id="a")
    store.write_or_append_vod_groups_batch([item])

    full = store.read_group(GROUP).compute()
    assert full.sizes["epoch"] == 86400 / CADENCE_S
    read = store.read_group(GROUP, drop_empty=True).compute()
    expected = item.dataset
    np.testing.assert_array_equal(read.epoch.values, expected.epoch.values)
    for name in ("VOD", "phi", "theta"):
        xr.testing.assert_allclose(
            read[name].reset_coords(drop=True),
            expected[name].reset_coords(drop=True).astype(read[name].dtype),
        )


def test_site_reads_vod_without_empty_slots_by_default(
    store: MyIcechunkStore,
) -> None:
    """``read_vod_analysis`` leaves the empty slots out, as receiver reads do."""
    item = _item(GROUP, slot=2, source_id="a")
    store.write_or_append_vod_groups_batch([item])
    site = object.__new__(GnssResearchSite)
    site.vod_store = store
    site._logger = unittest.mock.MagicMock()
    calculator, analysis = GROUP.split("/")

    read = site.read_vod_analysis(analysis, calculator)
    full = site.read_vod_analysis(analysis, calculator, drop_empty=False)

    assert read.sizes["epoch"] == item.dataset.sizes["epoch"]
    assert full.sizes["epoch"] == 86400 / CADENCE_S


def test_shorter_rewrite_leaves_nothing_of_the_earlier_result(
    store: MyIcechunkStore,
) -> None:
    """A day written again with a shorter result holds only the new one.

    The new result covers the second half of the earlier one's span, so a
    write of its span alone would keep the earlier first half.
    """
    store.write_or_append_vod_groups_batch([_item(GROUP, slot=0, source_id="old")])
    new = _item(GROUP, slot=0, source_id="new", seed=7)
    n = new.dataset.sizes["epoch"]
    new.dataset = new.dataset.isel(epoch=slice(n // 2, None))
    store.write_or_append_vod_groups_batch([new])

    read = store.read_group(GROUP, drop_empty=True).compute()
    np.testing.assert_array_equal(read.epoch.values, new.dataset.epoch.values)
    xr.testing.assert_allclose(
        read["VOD"].reset_coords(drop=True),
        new.dataset["VOD"].reset_coords(drop=True).astype(read["VOD"].dtype),
    )
    summary = summarize_store(store.store_path)
    assert summary["summaries.total_epochs"] == read.sizes["epoch"]


def test_rewriting_a_day_replaces_it(store: MyIcechunkStore) -> None:
    """Recomputed VOD of a day overwrites its slots: no duplicate epochs."""
    store.write_or_append_vod_groups_batch([_item(GROUP, slot=0, source_id="old")])
    blocks_before = _blocks(store, GROUP)
    before = _snapshots(store)

    new = _item(GROUP, slot=0, source_id="new", seed=7)
    results = store.write_or_append_vod_groups_batch([new])

    assert _snapshots(store) == before + 1
    assert results[GROUP].written
    assert _blocks(store, GROUP) == blocks_before
    read = store.read_group(GROUP, drop_empty=True).compute()
    assert read.sizes["epoch"] == new.dataset.sizes["epoch"]
    assert np.unique(read.epoch.values).size == read.sizes["epoch"]
    np.testing.assert_allclose(
        read["VOD"].values, new.dataset["VOD"].values.astype(read["VOD"].dtype)
    )
    assert store.metadata_row_count(GROUP) == 2


def test_same_sources_are_skipped(store: MyIcechunkStore) -> None:
    """A day computed again from the same GNSS files is not written."""
    store.write_or_append_vod_groups_batch([_item(GROUP, slot=0, source_id="a")])
    before = _snapshots(store)

    results = store.write_or_append_vod_groups_batch(
        [_item(GROUP, slot=0, source_id="a")]
    )

    assert _snapshots(store) == before
    assert results[GROUP].written is False
    assert results[GROUP].skip_reason == "hash_match"


def test_each_day_gets_its_own_block(store: MyIcechunkStore) -> None:
    """Days written one after the other, a commit and a block per day."""
    before = _snapshots(store)
    for day in ("2025-03-28", "2025-03-29"):
        store.write_or_append_vod_groups_batch(
            [_item(GROUP, slot=0, source_id=day, day=day)]
        )

    assert _snapshots(store) == before + 2
    assert sorted(_blocks(store, GROUP)) == [
        np.datetime64("2025-03-28", "D"),
        np.datetime64("2025-03-29", "D"),
    ]


def test_summary_counts_a_rewritten_day_once(store: MyIcechunkStore) -> None:
    """The snapshot summary counts the epochs with data of the latest write."""
    store.write_or_append_vod_groups_batch([_item(GROUP, slot=0, source_id="old")])
    new = _item(GROUP, slot=1, source_id="new", seed=7)
    store.write_or_append_vod_groups_batch([new])
    store.write_or_append_vod_groups_batch([_item(OTHER, slot=0, source_id="b")])

    other = drop_empty_slots(_item(OTHER, slot=0, source_id="b").dataset, OTHER)
    expected = (
        drop_empty_slots(new.dataset, GROUP).sizes["epoch"] + other.sizes["epoch"]
    )
    summary = summarize_store(store.store_path)
    assert summary["summaries.total_epochs"] == expected


def test_result_of_two_days_is_refused(store: MyIcechunkStore) -> None:
    """A day-block write takes one day; nothing is committed otherwise."""
    one = make_synthetic_vod_dataset(slot=0, day="2025-03-28")
    two = make_synthetic_vod_dataset(slot=0, day="2025-03-29")
    item = _item(GROUP, slot=0, source_id="a")
    item.dataset = xr.concat([one, two], dim="epoch")
    item.cadences = {
        np.datetime64("2025-03-28", "D"): CADENCE_S,
        np.datetime64("2025-03-29", "D"): CADENCE_S,
    }
    before = _snapshots(store)

    with pytest.raises(LayoutError, match="takes one day"):
        store.write_or_append_vod_groups_batch([item])
    assert _snapshots(store) == before


def _site(store: MyIcechunkStore) -> GnssResearchSite:
    """A site with the VOD store ``store`` and the analysis of ``GROUP``."""
    site = object.__new__(GnssResearchSite)
    site.vod_store = store
    site._logger = unittest.mock.MagicMock()
    site._site_config = unittest.mock.MagicMock(
        vod_analyses={GROUP.split("/")[1]: unittest.mock.MagicMock()}
    )
    site.ensure_store_metadata = unittest.mock.MagicMock()
    return site


def test_site_stores_one_vod_day_into_its_block(store: MyIcechunkStore) -> None:
    """``store_vod_analysis`` with the day's cadence writes the day's block."""
    item = _item(GROUP, slot=0, source_id="a")
    calculator, analysis = GROUP.split("/")

    written = _site(store).store_vod_analysis(
        item.dataset,
        analysis,
        calculator,
        source_file_hashes=item.source_file_hashes,
        source_gnss_stores=item.source_gnss_stores,
        cadences=item.cadences,
    )

    assert written
    (block,) = _blocks(store, GROUP).values()
    assert block.cadence_s == CADENCE_S


def test_site_refuses_vod_without_cadence_on_day_blocks(
    store: MyIcechunkStore,
) -> None:
    """Without the day's cadence nothing is appended to a day-block group."""
    store.write_or_append_vod_groups_batch([_item(GROUP, slot=0, source_id="a")])
    later = _item(GROUP, slot=0, source_id="b", day="2025-03-29")
    calculator, analysis = GROUP.split("/")
    before = _snapshots(store)

    with pytest.raises(LayoutError, match="day blocks"):
        _site(store).store_vod_analysis(
            later.dataset,
            analysis,
            calculator,
            source_file_hashes=later.source_file_hashes,
            source_gnss_stores=later.source_gnss_stores,
        )
    assert _snapshots(store) == before
