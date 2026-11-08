"""Comprehensive tests for equal-area grid implementation.

Tests focus on equal-area specific properties and behavior,
including area uniformity, rectangular structure, and coordinate systems.

Tests cover:
- Grid creation with various resolutions
- Cell area uniformity (equal-area property)
- Grid structure and columns
- Vertex extraction
- Dataset conversion
- Patch generation for visualization
- Metadata structure
"""

from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from canvod.grids import create_hemigrid


class TestEqualAreaCreation:
    """Test equal-area grid creation."""

    @pytest.mark.parametrize(
        "angular_resolution",
        [5.0, 10.0, 15.0, 20.0, 30.0],
    )
    def test_equal_area_creation_valid_resolutions(
        self, angular_resolution: float
    ) -> None:
        """Create grids with range of valid resolutions."""
        grid = create_hemigrid("equal_area", angular_resolution)

        assert grid is not None
        assert grid.grid_type == "equal_area"
        assert grid.ncells > 0

        # Coarser resolution should have fewer cells
        if angular_resolution == 30.0:
            assert grid.ncells < 100
        elif angular_resolution == 5.0:
            assert grid.ncells > 500

    def test_equal_area_minimum_resolution(self) -> None:
        """Test grid creation with minimum reasonable resolution."""
        grid = create_hemigrid("equal_area", angular_resolution=45.0)

        # Very coarse grid should still work
        assert grid.ncells > 0
        assert grid.ncells < 50

    def test_equal_area_high_resolution(self) -> None:
        """Test grid creation with high resolution."""
        grid = create_hemigrid("equal_area", angular_resolution=2.0)

        # Fine grid should have many cells
        assert grid.ncells > 2000


class TestEqualAreaCellUniformity:
    """Test that equal-area grids have uniform cell areas."""

    def test_equal_area_cells_have_similar_area(self) -> None:
        """Verify cells have similar solid angles (equal-area property)."""
        grid = create_hemigrid("equal_area", angular_resolution=10.0)

        solid_angles = grid.get_solid_angles()

        # Calculate statistics
        mean_sa = np.mean(solid_angles)
        std_sa = np.std(solid_angles)
        cv = std_sa / mean_sa  # Coefficient of variation

        # Equal-area grids should have low variation
        assert cv < 0.25, f"CV {cv:.2%} too high for equal-area grid"

        # Check that most cells are within 20% of mean
        within_20pct = np.abs(solid_angles - mean_sa) < (0.2 * mean_sa)
        fraction_within = np.sum(within_20pct) / len(solid_angles)

        assert fraction_within > 0.80, "Most cells should be within 20% of mean"

    def test_equal_area_no_extreme_outliers(self) -> None:
        """Verify no cells are extremely large or small."""
        grid = create_hemigrid("equal_area", angular_resolution=15.0)

        solid_angles = grid.get_solid_angles()
        mean_sa = np.mean(solid_angles)

        # No cell should be more than 2x or less than 0.5x the mean
        assert np.all(solid_angles < 2.0 * mean_sa)
        assert np.all(solid_angles > 0.5 * mean_sa)


class TestEqualAreaGridStructure:
    """Test equal-area grid DataFrame structure."""

    def test_equal_area_grid_structure(self) -> None:
        """Verify DataFrame has correct structure."""
        grid = create_hemigrid("equal_area", angular_resolution=10.0)

        # Check it's a Polars DataFrame
        assert isinstance(grid.grid, pl.DataFrame)

        # Check required columns
        required = [
            "cell_id",
            "phi",
            "theta",
            "phi_min",
            "phi_max",
            "theta_min",
            "theta_max",
        ]
        for col in required:
            assert col in grid.grid.columns

    def test_equal_area_cell_ids_sequential(self) -> None:
        """Verify cell IDs are sequential from 0."""
        grid = create_hemigrid("equal_area", angular_resolution=10.0)

        cell_ids = grid.grid["cell_id"].to_numpy()

        # Should be 0, 1, 2, ..., ncells-1
        expected = np.arange(grid.ncells)
        np.testing.assert_array_equal(cell_ids, expected)

    def test_equal_area_coordinates_valid_ranges(self) -> None:
        """Verify coordinates are in valid ranges."""
        grid = create_hemigrid("equal_area", angular_resolution=10.0)

        phi = grid.grid["phi"].to_numpy()
        theta = grid.grid["theta"].to_numpy()

        # Phi in [0, 2π)
        assert np.all(phi >= 0.0)
        assert np.all(phi < 2 * np.pi)

        # Theta in [0, π/2] for hemisphere
        assert np.all(theta >= 0.0)
        assert np.all(theta <= np.pi / 2)

    def test_equal_area_boundaries_consistent(self) -> None:
        """Verify phi/theta boundaries are consistent with centers."""
        grid = create_hemigrid("equal_area", angular_resolution=10.0)

        phi = grid.grid["phi"].to_numpy()
        phi_min = grid.grid["phi_min"].to_numpy()
        phi_max = grid.grid["phi_max"].to_numpy()

        theta = grid.grid["theta"].to_numpy()
        theta_min = grid.grid["theta_min"].to_numpy()
        theta_max = grid.grid["theta_max"].to_numpy()

        # Centers should be between min and max (most cases)
        # Handle phi wrapping around 2π
        non_wrapping = phi_max > phi_min
        assert np.all(
            (phi[non_wrapping] >= phi_min[non_wrapping])
            & (phi[non_wrapping] <= phi_max[non_wrapping])
        )

        # Theta should never wrap
        assert np.all((theta >= theta_min) & (theta <= theta_max))


class TestEqualAreaVertices:
    """Test vertex extraction for equal-area grids."""

    def test_equal_area_vertices_extracted(self) -> None:
        """Verify vertices can be extracted."""
        from canvod.grids import extract_grid_vertices

        grid = create_hemigrid("equal_area", angular_resolution=15.0)

        x, y, z = extract_grid_vertices(grid)

        # Should have vertices for all cells
        assert len(x) > 0
        assert len(y) > 0
        assert len(z) > 0

        # All arrays same length
        assert len(x) == len(y) == len(z)

    def test_equal_area_vertices_on_unit_sphere(self) -> None:
        """Verify vertices lie on unit sphere."""
        from canvod.grids import extract_grid_vertices

        grid = create_hemigrid("equal_area", angular_resolution=20.0)

        x, y, z = extract_grid_vertices(grid)

        # Sample a few vertices
        for i in range(0, len(x), 10):
            r = np.sqrt(x[i] ** 2 + y[i] ** 2 + z[i] ** 2)
            assert np.isclose(r, 1.0, rtol=1e-5)


class TestEqualAreaConversion:
    """Test conversion operations."""

    def test_equal_area_to_dataset(self) -> None:
        """Test grid_to_dataset conversion."""
        from canvod.grids import grid_to_dataset

        grid = create_hemigrid("equal_area", angular_resolution=15.0)

        ds = grid_to_dataset(grid)

        # Check xarray Dataset structure
        assert "cell_phi" in ds.data_vars
        assert "cell_theta" in ds.data_vars
        assert "vertices_phi" in ds.data_vars
        assert "vertices_theta" in ds.data_vars

        # Check dimensions
        assert len(ds["cell_phi"]) == grid.ncells

    def test_equal_area_dataset_has_attributes(self) -> None:
        """Verify Dataset has grid metadata as attributes."""
        from canvod.grids import grid_to_dataset

        grid = create_hemigrid("equal_area", angular_resolution=10.0)

        ds = grid_to_dataset(grid)

        # Should have grid_type attribute
        assert "grid_type" in ds.attrs
        assert ds.attrs["grid_type"] == "equal_area"


class TestEqualAreaPatches:
    """Test patch generation for visualization."""

    def test_equal_area_patches_generated(self) -> None:
        """Verify get_patches returns patch objects."""
        grid = create_hemigrid("equal_area", angular_resolution=20.0)

        patches = grid.get_patches()

        # Should return Polars Series
        assert isinstance(patches, pl.Series)
        assert len(patches) == grid.ncells

    def test_equal_area_patches_are_rectangles(self) -> None:
        """Verify patches are matplotlib Rectangle objects."""
        from matplotlib.patches import Rectangle

        grid = create_hemigrid("equal_area", angular_resolution=20.0)

        patches = grid.get_patches()

        # Sample first patch
        first_patch = patches[0]
        assert isinstance(first_patch, Rectangle)


class TestEqualAreaEdgeCases:
    """Test edge cases and boundaries."""

    def test_equal_area_single_cell_at_zenith(self) -> None:
        """Verify zenith cell (θ=0) is handled correctly."""
        grid = create_hemigrid("equal_area", angular_resolution=10.0)

        # Find zenith cell (smallest theta)
        theta_vals = grid.grid["theta"].to_numpy()
        zenith_idx = np.argmin(theta_vals)
        zenith_cell = grid.grid.row(zenith_idx, named=True)

        # Zenith cell should have theta near 0
        assert zenith_cell["theta"] < 0.1

        # Should have phi defined (though arbitrary at zenith)
        assert 0.0 <= zenith_cell["phi"] < 2 * np.pi

    def test_equal_area_horizon_cells(self) -> None:
        """Verify cells near horizon (θ=π/2) handled correctly."""
        grid = create_hemigrid("equal_area", angular_resolution=10.0)

        # Find cells near horizon
        theta_vals = grid.grid["theta"].to_numpy()
        horizon_mask = theta_vals > (np.pi / 2 - 0.2)
        horizon_cells = grid.grid.filter(pl.col("theta") > (np.pi / 2 - 0.2))

        # Should have some cells near horizon
        assert len(horizon_cells) > 0
        assert horizon_mask.sum() == len(horizon_cells)

        # All should have valid phi values
        phi_vals = horizon_cells["phi"].to_numpy()
        assert np.all(phi_vals >= 0.0)
        assert np.all(phi_vals < 2 * np.pi)
