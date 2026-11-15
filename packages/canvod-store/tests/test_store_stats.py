"""``get_store_stats``: the groups that hold data, and the store's compression."""

from __future__ import annotations

import logging
from pathlib import Path

import icechunk
import numpy as np
import pytest
from _helpers import make_synthetic_vod_dataset, new_vod_store

from canvod.store import MyIcechunkStore
from canvod.store.store import VodWriteItem

GROUP = "tau_omega/canopy_01_vs_reference_01"
DAY = "2025-03-28"


@pytest.fixture
def store(tmp_path: Path) -> MyIcechunkStore:
    store_path = tmp_path / "vod_store"
    store_path.mkdir()
    store = new_vod_store(store_path)
    store.write_or_append_vod_groups_batch(
        [
            VodWriteItem(
                group_name=GROUP,
                dataset=make_synthetic_vod_dataset(slot=0, day=DAY, seed=0),
                source_file_hashes={"canopy_01": "hash_a"},
                source_gnss_stores={"canopy_01": "/fake/gnss_store"},
                calculator_name="tau_omega",
                commit_message="VOD",
                cadences={np.datetime64(DAY, "D"): 5.0},
            )
        ]
    )
    return store


def test_a_vod_analysis_gets_its_stats_without_a_warning(
    store: MyIcechunkStore, caplog: pytest.LogCaptureFixture
) -> None:
    """The analysis sits below its calculator; the calculator group holds
    no epochs and is not asked for any."""
    with caplog.at_level(logging.WARNING):
        stats = store.get_store_stats()

    assert "Failed to get stats" not in caplog.text
    assert stats["total_groups"] == 1
    assert stats[f"group_{GROUP}"]["has_temporal_data"]
    assert "group_tau_omega" not in stats


def test_the_compression_is_the_store_s_own(store: MyIcechunkStore) -> None:
    """A store opened with another compression level still reports the
    level it keeps with its repository."""
    kept = icechunk.Repository.fetch_config(store.location.storage())
    assert kept is not None
    other = 22 if kept.compression.level != 22 else 1

    stats = MyIcechunkStore(
        store.store_path, store_type="vod_store", compression_level=other
    ).get_store_stats()

    assert stats["compression_level"] == kept.compression.level
    assert stats["compression_algorithm"] == "Zstd"
