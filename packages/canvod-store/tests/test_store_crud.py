"""Tests for basic CRUD operations and store lifecycle.

Tests cover:
- Store creation (RINEX and VOD)
- Store initialization and connection
- Session management (readonly/writable)
- Group operations (create/list/access)
- Basic write/read operations
- Commit workflow
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import xarray as xr
import zarr
from canvod.store_metadata.testing import create_test_store

from canvod.store import (
    MyIcechunkStore,
    open_gnss_store,
    open_vod_store,
)


class TestStoreOpening:
    """Test opening stores."""

    def test_open_gnss_store(self, tmp_path: Path) -> None:
        """Open a GNSS store."""
        store_path = create_test_store(tmp_path / "test_site" / "gnss_store")

        store = open_gnss_store(store_path)

        assert isinstance(store, MyIcechunkStore)
        assert store.store_path == store_path
        assert store.store_type == "gnss_store"

    def test_open_vod_store(self, tmp_path: Path) -> None:
        """Open a VOD store."""
        store_path = create_test_store(tmp_path / "test_site" / "vod_store")

        store = open_vod_store(store_path)

        assert isinstance(store, MyIcechunkStore)
        assert store.store_path == store_path
        assert store.store_type == "vod_store"

    def test_store_initialization_existing(self, tmp_path: Path) -> None:
        """Open a store twice and verify each has its own repo connection."""
        store_path = create_test_store(tmp_path / "test_site" / "vod_store")

        store1 = open_vod_store(store_path)
        repo1_id = id(store1.repo)

        # Re-open existing store
        store2 = MyIcechunkStore(store_path, store_type="vod_store")

        assert store2.repo is not None
        assert id(store2.repo) != repo1_id  # Different instance
        assert store2.store_path == store_path


class TestSessionManagement:
    """Test session context managers."""

    def test_readonly_session_context_manager(self, tmp_path: Path) -> None:
        """Test readonly session with context manager."""
        store_path = tmp_path / "test_site" / "vod_store"
        store = open_vod_store(create_test_store(store_path))

        # Need to create root group first
        with store.writable_session() as wsession:
            root = zarr.open(wsession.store, mode="w")
            wsession.commit("Initialize root")

        with store.readonly_session() as session:
            assert session is not None
            assert hasattr(session, "store")
            # Session should be open within context
            root = zarr.open(session.store, mode="r")
            assert isinstance(root, zarr.Group)

    def test_writable_session_context_manager(self, tmp_path: Path) -> None:
        """Test writable session with context manager."""
        store_path = tmp_path / "test_site" / "vod_store"
        store = open_vod_store(create_test_store(store_path))

        with store.writable_session() as session:
            assert session is not None
            assert hasattr(session, "store")
            # Session should be open and writable
            root = zarr.open(session.store, mode="w")
            assert isinstance(root, zarr.Group)


class TestGroupOperations:
    """Test group creation and listing."""

    def test_list_groups_empty_store(self, tmp_path: Path) -> None:
        """List groups in newly created store."""
        store_path = tmp_path / "test_site" / "vod_store"
        store = open_vod_store(create_test_store(store_path))

        groups = store.list_groups()

        assert isinstance(groups, list)
        assert len(groups) == 0  # New store should have no groups

    def test_create_and_list_group(self, tmp_path: Path) -> None:
        """Create group and verify it appears in listing."""
        store_path = tmp_path / "test_site" / "vod_store"
        store = open_vod_store(create_test_store(store_path))

        # Create a group by writing data
        with store.writable_session() as session:
            root = zarr.open(session.store, mode="w")
            group = root.create_group("test_group")
            # Zarr v3 requires shape argument
            group.create_array("dummy", shape=(3,), dtype="i4")
            group["dummy"][:] = [1, 2, 3]
            session.commit("Created test group")

        # List groups
        groups = store.list_groups()

        assert "test_group" in groups
        assert len(groups) == 1

    def test_get_branch_names(self, tmp_path: Path) -> None:
        """Get list of branches in store."""
        store_path = tmp_path / "test_site" / "vod_store"
        store = open_vod_store(create_test_store(store_path))

        branches = store.get_branch_names()

        assert isinstance(branches, list)
        assert "main" in branches  # Default branch should exist


class TestWriteReadOperations:
    """Test basic write and read operations."""

    def test_write_dataset_to_group(self, tmp_path: Path) -> None:
        """Write xarray Dataset to store."""
        store_path = tmp_path / "test_site" / "vod_store"
        store = open_vod_store(create_test_store(store_path))

        # Create sample dataset
        ds = xr.Dataset(
            {
                "temperature": (["x", "y"], np.random.rand(10, 20)),
                "pressure": (["x", "y"], np.random.rand(10, 20)),
            },
            coords={"x": np.arange(10), "y": np.arange(20)},
        )

        # Write dataset
        with store.writable_session() as session:
            root = zarr.open(session.store, mode="w")
            group = root.create_group("test_data")
            ds.to_zarr(group.store, group="test_data", mode="w")
            session.commit("Added test dataset")

        # Verify group exists
        groups = store.list_groups()
        assert "test_data" in groups

    def test_read_dataset_from_group(self, tmp_path: Path) -> None:
        """Read back Dataset and verify integrity."""
        store_path = tmp_path / "test_site" / "vod_store"
        store = open_vod_store(create_test_store(store_path))

        # Create and write dataset
        original_ds = xr.Dataset(
            {
                "temperature": (["x", "y"], np.random.rand(5, 10)),
            },
            coords={"x": np.arange(5), "y": np.arange(10)},
        )

        with store.writable_session() as session:
            root = zarr.open(session.store, mode="w")
            group = root.create_group("test_data")
            original_ds.to_zarr(group.store, group="test_data", mode="w")
            session.commit("Added test dataset")

        # Read back
        with store.readonly_session() as session:
            root = zarr.open(session.store, mode="r")
            loaded_ds = xr.open_zarr(root.store, group="test_data", consolidated=False)

            # Verify structure
            assert "temperature" in loaded_ds.data_vars
            assert loaded_ds["temperature"].shape == (5, 10)
            # Coord order may vary, check both exist
            assert set(loaded_ds.coords) == {"x", "y"}


class TestCommitWorkflow:
    """Test commit workflow with sessions."""

    def test_commit_creates_snapshot(self, tmp_path: Path) -> None:
        """Create session, write, commit, and verify snapshot."""
        store_path = tmp_path / "test_site" / "vod_store"
        store = open_vod_store(create_test_store(store_path))

        # Write and commit
        with store.writable_session() as session:
            root = zarr.open(session.store, mode="w")
            group = root.create_group("snapshot_test")
            # Zarr v3 requires shape argument
            group.create_array("data", shape=(5,), dtype="i4")
            group["data"][:] = [1, 2, 3, 4, 5]
            commit_id = session.commit("Test snapshot commit")

            assert commit_id is not None

        # Verify data persisted after commit
        with store.readonly_session() as session:
            root = zarr.open(session.store, mode="r")
            assert "snapshot_test" in list(root.group_keys())

    def test_uncommitted_changes_not_visible(self, tmp_path: Path) -> None:
        """Verify uncommitted changes are not visible in readonly session."""
        store_path = tmp_path / "test_site" / "vod_store"
        store = open_vod_store(create_test_store(store_path))

        # Write but don't commit
        with store.writable_session() as session:
            root = zarr.open(session.store, mode="w")
            root.create_group("uncommitted_group")
            # Exit without commit

        # Verify group not visible
        groups = store.list_groups()
        assert "uncommitted_group" not in groups
