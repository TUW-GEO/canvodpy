"""A run on the test data writes a new store as day blocks (ADR 0016)."""

import icechunk
import numpy as np
import pytest
import zarr

from canvod.store import MyIcechunkStore
from canvod.store_metadata import read_metadata
from canvod.store_metadata.layout import is_day_block_group


@pytest.mark.integration
def test_one_day_is_stored_as_day_blocks_without_losing_epochs(fangorn_one_day):
    config, _ = fangorn_one_day
    store_path = config.processing.storage.get_gnss_store_path("fangorn")
    repo = icechunk.Repository.open(
        storage=icechunk.local_filesystem_storage(str(store_path))
    )
    store = MyIcechunkStore(store_path)
    groups = store.list_groups() or []
    assert groups

    root = zarr.open_group(repo.readonly_session(branch="main").store, mode="r")
    total = 0
    for group in groups:
        assert is_day_block_group(root[group].attrs), group
        full = store.read_group(group)
        assert full.sizes["epoch"] % 180 == 0
        assert bool(full.indexes["epoch"].is_monotonic_increasing)
        with store.readonly_session("main") as session:
            log = store.load_metadata(session.store, group)
        stored = log.filter(log["action"].is_in(["initial", "written"]))
        data = store.read_group(group, drop_empty=True)
        # Every epoch of every file has its own slot: none was lost.
        assert data.sizes["epoch"] == int(stored["epochs"].sum()) > 0
        assert np.unique(data.epoch.values).size == data.sizes["epoch"]
        assert data.epoch.values[0] == np.datetime64(stored["start"].min(), "ns")
        assert data.epoch.values[-1] == np.datetime64(stored["end"].max(), "ns")
        total += data.sizes["epoch"]

    # One group per receiver in this run, so the store's epochs are their sum.
    assert read_metadata(store_path).summaries.total_epochs == total
