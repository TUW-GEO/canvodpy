"""Tests for grid storage and loading operations.

Tests store_grid() and load_grid(), which persist GridData structures to
Icechunk stores, and the old canvod.grids names of both.

Tests cover:
- Storing equal-area grids
- Loading equal-area grids
- Round-trip integrity (store → load → compare)
- Storing HTM grids with vertex data
- Loading HTM grids with vertex reconstruction
- Metadata preservation
- Error handling for invalid inputs
- Concurrent grid access from multiple sessions
- Reporting through the log instead of print()
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import xarray as xr
from _helpers import new_vod_store
from canvod.grids import create_hemigrid

from canvod.store import load_grid, store_grid


@pytest.fixture
def vod_store(tmp_path: Path):
    """Create temporary VOD store for testing."""
    store_path = tmp_path / "test_site" / "vod_store"
    return new_vod_store(store_path)


@pytest.fixture
def small_equal_area_grid():
    """Create small equal-area grid for testing."""
    return create_hemigrid("equal_area", angular_resolution=15.0)


@pytest.fixture
def small_htm_grid():
    """Create small HTM grid for testing."""
    return create_hemigrid("htm", angular_resolution=10.0)


class TestStoreEqualAreaGrid:
    """Test storing equal-area grids."""

    def test_store_equal_area_grid(self, vod_store, small_equal_area_grid) -> None:
        """Store equal-area grid and verify group created."""
        grid = small_equal_area_grid
        grid_name = "test_equal_area_15deg"

        snapshot_id = store_grid(grid, vod_store, grid_name)

        # Verify snapshot ID returned
        assert snapshot_id is not None
        assert isinstance(snapshot_id, str)

        # Verify group created in store
        groups = vod_store.list_groups()
        assert "grids" in groups

    def test_store_creates_correct_group_path(
        self, vod_store, small_equal_area_grid
    ) -> None:
        """Verify grid stored at correct path: grids/{grid_name}."""
        grid = small_equal_area_grid
        grid_name = "equal_area_test"

        store_grid(grid, vod_store, grid_name)

        # Check that data is accessible at expected path
        with vod_store.readonly_session() as session:
            ds = xr.open_zarr(
                session.store,
                group=f"grids/{grid_name}",
                consolidated=False,
            )
            assert ds is not None
            assert "cell_phi" in ds.data_vars

    def test_stored_grid_has_required_variables(
        self, vod_store, small_equal_area_grid
    ) -> None:
        """Verify stored grid has all required variables."""
        grid = small_equal_area_grid
        grid_name = "test_grid"

        store_grid(grid, vod_store, grid_name)

        # Load and check variables
        with vod_store.readonly_session() as session:
            ds = xr.open_zarr(
                session.store,
                group=f"grids/{grid_name}",
                consolidated=False,
            )

            # Required variables for all grids
            assert "cell_phi" in ds.data_vars
            assert "cell_theta" in ds.data_vars
            assert "vertices_phi" in ds.data_vars
            assert "vertices_theta" in ds.data_vars
            assert "n_vertices" in ds.data_vars


class TestLoadEqualAreaGrid:
    """Test loading equal-area grids."""

    def test_load_equal_area_grid(self, vod_store, small_equal_area_grid) -> None:
        """Load equal-area grid and verify structure."""
        original_grid = small_equal_area_grid
        grid_name = "test_load_grid"

        # Store grid
        store_grid(original_grid, vod_store, grid_name)

        # Load grid
        loaded_grid = load_grid(vod_store, grid_name)

        # Verify basic attributes
        assert loaded_grid is not None
        assert loaded_grid.grid_type == original_grid.grid_type
        assert loaded_grid.ncells == original_grid.ncells

    def test_loaded_grid_has_polars_dataframe(
        self, vod_store, small_equal_area_grid
    ) -> None:
        """Verify loaded grid has proper Polars DataFrame."""
        grid = small_equal_area_grid
        grid_name = "test_polars"

        store_grid(grid, vod_store, grid_name)
        loaded_grid = load_grid(vod_store, grid_name)

        import polars as pl

        assert isinstance(loaded_grid.grid, pl.DataFrame)
        assert len(loaded_grid.grid) == loaded_grid.ncells

    def test_loaded_grid_has_required_columns(
        self, vod_store, small_equal_area_grid
    ) -> None:
        """Verify loaded grid DataFrame has required columns."""
        grid = small_equal_area_grid
        grid_name = "test_columns"

        store_grid(grid, vod_store, grid_name)
        loaded_grid = load_grid(vod_store, grid_name)

        required_cols = [
            "cell_id",
            "phi",
            "theta",
            "phi_min",
            "phi_max",
            "theta_min",
            "theta_max",
        ]
        for col in required_cols:
            assert col in loaded_grid.grid.columns


class TestGridRoundTrip:
    """Test store → load → compare for data integrity."""

    def test_grid_round_trip_cell_count(self, vod_store, small_equal_area_grid) -> None:
        """Verify cell count preserved in round-trip."""
        original_grid = small_equal_area_grid
        grid_name = "roundtrip_test"

        store_grid(original_grid, vod_store, grid_name)
        loaded_grid = load_grid(vod_store, grid_name)

        assert loaded_grid.ncells == original_grid.ncells

    def test_grid_round_trip_cell_centers(
        self, vod_store, small_equal_area_grid
    ) -> None:
        """Verify cell centers (phi, theta) preserved."""
        original_grid = small_equal_area_grid
        grid_name = "roundtrip_centers"

        store_grid(original_grid, vod_store, grid_name)
        loaded_grid = load_grid(vod_store, grid_name)

        # Compare cell centers
        orig_phi = original_grid.grid["phi"].to_numpy()
        load_phi = loaded_grid.grid["phi"].to_numpy()
        np.testing.assert_allclose(orig_phi, load_phi, rtol=1e-10)

        orig_theta = original_grid.grid["theta"].to_numpy()
        load_theta = loaded_grid.grid["theta"].to_numpy()
        np.testing.assert_allclose(orig_theta, load_theta, rtol=1e-10)

    def test_grid_round_trip_grid_type(self, vod_store, small_equal_area_grid) -> None:
        """Verify grid type preserved."""
        original_grid = small_equal_area_grid
        grid_name = "roundtrip_type"

        store_grid(original_grid, vod_store, grid_name)
        loaded_grid = load_grid(vod_store, grid_name)

        assert loaded_grid.grid_type == original_grid.grid_type
        assert loaded_grid.grid_type == "equal_area"


class TestStoreHTMGrid:
    """Test storing HTM grids with vertex data."""

    def test_store_htm_grid(self, vod_store, small_htm_grid) -> None:
        """Store HTM grid and verify."""
        grid = small_htm_grid
        grid_name = "test_htm_10deg"

        snapshot_id = store_grid(grid, vod_store, grid_name)

        assert snapshot_id is not None

        # Verify stored
        with vod_store.readonly_session() as session:
            ds = xr.open_zarr(
                session.store,
                group=f"grids/{grid_name}",
                consolidated=False,
            )
            assert "cell_phi" in ds.data_vars

    def test_htm_grid_has_vertex_columns(self, vod_store, small_htm_grid) -> None:
        """Verify HTM grid has vertex data stored."""
        grid = small_htm_grid
        grid_name = "test_htm_vertices"

        store_grid(grid, vod_store, grid_name)

        with vod_store.readonly_session() as session:
            ds = xr.open_zarr(
                session.store,
                group=f"grids/{grid_name}",
                consolidated=False,
            )

            # HTM grids should have vertices
            assert "vertices_phi" in ds.data_vars
            assert "vertices_theta" in ds.data_vars
            assert "n_vertices" in ds.data_vars


class TestLoadHTMGrid:
    """Test loading HTM grids."""

    def test_load_htm_grid(self, vod_store, small_htm_grid) -> None:
        """Load HTM grid and verify vertex structure."""
        original_grid = small_htm_grid
        grid_name = "test_load_htm"

        store_grid(original_grid, vod_store, grid_name)
        loaded_grid = load_grid(vod_store, grid_name)

        assert loaded_grid.grid_type == "htm"
        assert loaded_grid.ncells == original_grid.ncells

    def test_htm_grid_has_vertex_columns_after_load(
        self, vod_store, small_htm_grid
    ) -> None:
        """Verify HTM grid has vertex columns after loading."""
        grid = small_htm_grid
        grid_name = "test_htm_load_vertices"

        store_grid(grid, vod_store, grid_name)
        loaded_grid = load_grid(vod_store, grid_name)

        # Check for HTM vertex columns
        htm_cols = [c for c in loaded_grid.grid.columns if c.startswith("htm_vertex")]
        assert len(htm_cols) > 0  # Should have vertex columns


class TestGridMetadataPreservation:
    """Test metadata preservation through store/load cycle."""

    def test_grid_metadata_preserved(self, vod_store, small_equal_area_grid) -> None:
        """Verify metadata survives round-trip."""
        grid = small_equal_area_grid
        grid_name = "test_metadata"

        store_grid(grid, vod_store, grid_name)
        loaded_grid = load_grid(vod_store, grid_name)

        # Check metadata dict exists
        assert loaded_grid.metadata is not None
        assert isinstance(loaded_grid.metadata, dict)

    def test_angular_resolution_preserved(
        self, vod_store, small_equal_area_grid
    ) -> None:
        """Verify angular resolution in metadata."""
        grid = small_equal_area_grid
        grid_name = "test_angular_res"

        store_grid(grid, vod_store, grid_name)
        loaded_grid = load_grid(vod_store, grid_name)

        # Angular resolution should be stored in metadata
        assert "angular_resolution" in loaded_grid.metadata


class TestErrorHandling:
    """Test error handling for invalid inputs."""

    def test_load_nonexistent_grid_raises(self, vod_store) -> None:
        """Loading nonexistent grid should raise error."""
        with pytest.raises((KeyError, ValueError)):
            load_grid(vod_store, "nonexistent_grid")


class TestConcurrentAccess:
    """Test concurrent grid access from multiple sessions."""

    def test_concurrent_grid_reads(self, vod_store, small_equal_area_grid) -> None:
        """Read grid from multiple sessions simultaneously."""
        grid = small_equal_area_grid
        grid_name = "concurrent_test"

        # Store grid
        store_grid(grid, vod_store, grid_name)

        # Load from multiple sessions
        grid1 = load_grid(vod_store, grid_name)
        grid2 = load_grid(vod_store, grid_name)

        # Both should be valid and equal
        assert grid1.ncells == grid2.ncells
        assert grid1.grid_type == grid2.grid_type


class TestOldGridsNames:
    """The canvod.grids names are left over from development."""

    def test_store_and_load_warn_and_delegate(
        self, vod_store, small_equal_area_grid
    ) -> None:
        import canvod.grids

        with pytest.warns(FutureWarning, match="canvod.store.store_grid"):
            canvod.grids.store_grid(small_equal_area_grid, vod_store, "old_name")
        with pytest.warns(FutureWarning, match="canvod.store.load_grid"):
            grid = canvod.grids.load_grid(vod_store, "old_name")
        assert grid.ncells == small_equal_area_grid.ncells

    def test_analysis_storage_warns_and_returns_store_class(self, vod_store) -> None:
        from canvod.grids.analysis import AnalysisStorage as OldAnalysisStorage

        from canvod.store import AnalysisStorage

        with pytest.warns(FutureWarning, match="canvod.store.AnalysisStorage"):
            storage = OldAnalysisStorage(vod_store.store_path)
        assert isinstance(storage, AnalysisStorage)


def test_store_and_load_log_instead_of_printing(
    vod_store, small_equal_area_grid
) -> None:
    """store_grid() and load_grid() report through the log, not print()."""
    from structlog.testing import capture_logs

    with capture_logs() as logs:
        store_grid(small_equal_area_grid, vod_store, "logged")
        load_grid(vod_store, "logged")
    events = [(e["event"], e["group"], e["ncells"]) for e in logs]
    ncells = small_equal_area_grid.ncells
    assert events == [
        ("grid_stored", "grids/logged", ncells),
        ("grid_loaded", "grids/logged", ncells),
    ]
