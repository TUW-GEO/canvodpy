"""The reserved group ``canvod`` is never listed as data (ADR 0014)."""

from __future__ import annotations

import zarr
from canvod.store_metadata import RESERVED_GROUP
from canvod.store_metadata.testing import create_test_store

from canvod.store import MyIcechunkStore


def test_group_listings_leave_out_the_reserved_group(tmp_path):
    store = MyIcechunkStore(create_test_store(tmp_path / "store"))
    with store.writable_session() as session:
        root = zarr.open_group(session.store, mode="w")
        root.require_group(f"{RESERVED_GROUP}/environments")
        root.require_group("canopy_01")
        snapshot_id = session.commit("groups")

    assert store.list_groups() == ["canopy_01"]
    assert store.get_group_names() == {"main": ["canopy_01"]}
    assert store.get_snapshot_info(snapshot_id)["groups"] == ["canopy_01"]
