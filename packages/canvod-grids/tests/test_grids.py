"""Tests for grid implementations."""

import numpy as np
import polars as pl
import pytest

from canvod.grids import (
    GRID_BUILDERS,
    EqualAreaBuilder,
    GridData,
    GridType,
    HTMBuilder,
    create_hemigrid,
)


class TestGridBuilders:
    """``GRID_BUILDERS`` is the one table of grid types and their builders."""

    def test_every_grid_type_has_a_builder(self):
        assert set(GRID_BUILDERS) == set(GridType)

    def test_create_hemigrid_uses_the_table(self, monkeypatch):
        monkeypatch.setitem(GRID_BUILDERS, GridType.HTM, EqualAreaBuilder)
        grid = create_hemigrid("htm", angular_resolution=10.0)
        expected = EqualAreaBuilder(angular_resolution=10.0).build()
        assert grid.grid.equals(expected.grid)

    @pytest.mark.parametrize(
        ("name", "grid_type"),
        [
            ("HTM", GridType.HTM),
            ("Equal_Area", GridType.EQUAL_AREA),
            ("rectangular", GridType.EQUIRECTANGULAR),
        ],
    )
    def test_names_are_case_insensitive_and_rectangular_is_equirectangular(
        self, name, grid_type
    ):
        grid = create_hemigrid(name, angular_resolution=10.0)
        expected = GRID_BUILDERS[grid_type](angular_resolution=10.0).build()
        assert grid.grid.equals(expected.grid)

    def test_unknown_type_lists_the_types(self):
        with pytest.raises(ValueError, match=r"Unknown grid type: hex.*fibonacci"):
            create_hemigrid("hex")


class TestGridCreation:
    """Test basic grid creation."""

    def test_equal_area_grid(self):
        """Test equal area grid creation."""
        grid = create_hemigrid("equal_area", angular_resolution=10.0)

        assert isinstance(grid, GridData)
        assert grid.grid_type == "equal_area"
        assert grid.ncells > 0
        assert len(grid.grid) == grid.ncells

        # Check required columns
        assert "phi" in grid.grid.columns
        assert "theta" in grid.grid.columns
        assert "phi_min" in grid.grid.columns
        assert "phi_max" in grid.grid.columns
        assert "theta_min" in grid.grid.columns
        assert "theta_max" in grid.grid.columns
        assert "cell_id" in grid.grid.columns

    def test_equal_angle_grid(self):
        """Test equal angle grid creation."""
        grid = create_hemigrid("equal_angle", angular_resolution=15.0)

        assert grid.grid_type == "equal_angle"
        assert grid.ncells > 0

    def test_rectangular_grid(self):
        """Test rectangular grid creation."""
        grid1 = create_hemigrid("rectangular", angular_resolution=20.0)
        grid2 = create_hemigrid("equirectangular", angular_resolution=20.0)

        assert grid1.grid_type == "equirectangular"
        assert grid2.grid_type == "equirectangular"
        assert grid1.ncells == grid2.ncells

    def test_geodesic_grid(self):
        """Test geodesic grid creation."""
        grid = create_hemigrid("geodesic", angular_resolution=15.0)

        assert grid.grid_type == "geodesic"
        assert grid.ncells > 0

        # Check for geodesic-specific columns
        assert "geodesic_vertices" in grid.grid.columns
        assert "geodesic_subdivision" in grid.grid.columns

    def test_htm_grid(self):
        """Test HTM grid creation."""
        grid = create_hemigrid("HTM", angular_resolution=10.0)

        assert grid.grid_type == "htm"
        assert grid.ncells > 0

        # Check for HTM-specific columns
        assert "htm_id" in grid.grid.columns
        assert "htm_level" in grid.grid.columns
        assert "htm_vertex_0" in grid.grid.columns

    def test_invalid_grid_type(self):
        """Test that invalid grid type raises error."""
        with pytest.raises(ValueError, match="Unknown grid type"):
            create_hemigrid("invalid_type")


class TestGridBuilder:
    """Test grid builder classes directly."""

    def test_equal_area_builder(self):
        """Test EqualAreaBuilder."""
        builder = EqualAreaBuilder(angular_resolution=10.0)
        grid = builder.build()

        assert grid.grid_type == "equal_area"
        assert grid.ncells > 0

    def test_builder_with_cutoff(self):
        """Test builder with theta cutoff."""
        builder = EqualAreaBuilder(angular_resolution=10.0, cutoff_theta=10.0)
        grid = builder.build()

        # cutoff_theta is an elevation mask: the grid starts at the zenith
        # and ends 10 deg above the horizon
        assert grid.grid["theta_min"].min() == 0.0
        assert grid.grid["theta_max"].max() == pytest.approx(np.deg2rad(80.0))

    def test_builder_with_rotation(self):
        """Test builder with phi rotation."""
        builder = EqualAreaBuilder(angular_resolution=10.0, phi_rotation=45.0)
        grid = builder.build()

        assert grid.ncells > 0


class TestGridProperties:
    """Test grid properties and methods."""

    def test_grid_coords(self):
        """Test coords property."""
        grid = create_hemigrid("equal_area", angular_resolution=15.0)
        coords = grid.coords

        assert isinstance(coords, pl.DataFrame)
        assert "phi" in coords.columns
        assert "theta" in coords.columns
        assert len(coords) == grid.ncells

    def test_solid_angles(self):
        """Test solid angle calculation."""
        grid = create_hemigrid("equal_area", angular_resolution=15.0)
        solid_angles = grid.get_solid_angles()

        assert len(solid_angles) == grid.ncells
        assert np.all(solid_angles > 0)

        # Total solid angle should be approximately 2π (hemisphere)
        # Note: Will be less than 2π due to not covering to exact horizon
        total = np.sum(solid_angles)
        expected = 2 * np.pi
        # Allow 20% tolerance due to discretization and horizon cutoff
        assert total > expected * 0.8
        assert total < expected * 1.05

    def test_grid_stats(self):
        """Test grid statistics."""
        grid = create_hemigrid("equal_area", angular_resolution=10.0)
        stats = grid.get_grid_stats()

        assert "total_cells" in stats
        assert "grid_type" in stats
        assert "solid_angle_mean_sr" in stats
        assert "solid_angle_std_sr" in stats
        assert "hemisphere_solid_angle_sr" in stats

        assert stats["total_cells"] == grid.ncells
        assert stats["grid_type"] == "equal_area"
        assert np.isclose(stats["hemisphere_solid_angle_sr"], 2 * np.pi)


class TestGridResolution:
    """Test grid resolution scaling."""

    def test_resolution_scaling(self):
        """Test that finer resolution creates more cells."""
        grid_coarse = create_hemigrid("equal_area", angular_resolution=20.0)
        grid_fine = create_hemigrid("equal_area", angular_resolution=10.0)

        assert grid_fine.ncells > grid_coarse.ncells

    def test_htm_level_scaling(self):
        """Test HTM level scaling."""
        grid_level1 = create_hemigrid("HTM", htm_level=1)
        grid_level2 = create_hemigrid("HTM", htm_level=2)

        # Each level multiplies triangles by 4
        assert grid_level2.ncells > grid_level1.ncells

    def test_geodesic_subdivision_scaling(self):
        """Test geodesic subdivision scaling."""
        grid_sub1 = create_hemigrid("geodesic", subdivision_level=1)
        grid_sub2 = create_hemigrid("geodesic", subdivision_level=2)

        assert grid_sub2.ncells > grid_sub1.ncells


class TestGridCoordinates:
    """Test grid coordinate conventions."""

    def test_phi_range(self):
        """Test phi is in [0, 2π)."""
        grid = create_hemigrid("equal_area", angular_resolution=10.0)

        phi_vals = grid.grid["phi"]
        assert phi_vals.min() >= 0
        assert phi_vals.max() < 2 * np.pi

    def test_theta_range(self):
        """Test theta is in [0, π/2]."""
        grid = create_hemigrid("equal_area", angular_resolution=10.0)

        theta_vals = grid.grid["theta"]
        assert theta_vals.min() >= 0
        assert theta_vals.max() <= np.pi / 2

    def test_cell_bounds(self):
        """Test cell bounds are consistent."""
        grid = create_hemigrid("equal_area", angular_resolution=10.0)

        for row in grid.grid.iter_rows(named=True):
            # phi bounds
            assert row["phi_min"] <= row["phi"] <= row["phi_max"]
            # theta bounds
            assert row["theta_min"] <= row["theta"] <= row["theta_max"]


class TestSpecializedGrids:
    """Test specialized grid types."""

    @pytest.mark.parametrize("grid_type", ["geodesic", "HTM"])
    def test_triangular_grids(self, grid_type):
        """Test triangular grid types."""
        grid = create_hemigrid(grid_type, angular_resolution=15.0)

        assert grid.ncells > 0
        assert grid.grid_type in ["geodesic", "htm"]

    def test_htm_with_custom_level(self):
        """Test HTM with custom level."""
        grid = create_hemigrid("HTM", htm_level=3)
        builder = HTMBuilder(htm_level=3)

        assert grid.grid_type == "htm"
        info = builder.get_htm_info()
        assert info["htm_level"] == 3

    def test_geodesic_with_custom_subdivision(self):
        """Test geodesic with custom subdivision."""
        grid = create_hemigrid("geodesic", subdivision_level=2)

        assert grid.grid_type == "geodesic"
        # Check subdivision level is stored
        if grid.grid.height > 0:
            assert grid.grid["geodesic_subdivision"][0] == 2


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_very_fine_resolution(self):
        """Test very fine angular resolution."""
        # Should work but create many cells
        grid = create_hemigrid("equal_area", angular_resolution=2.0)
        assert grid.ncells > 100

    def test_very_coarse_resolution(self):
        """Test very coarse angular resolution."""
        grid = create_hemigrid("equal_area", angular_resolution=45.0)
        assert grid.ncells > 0
        assert grid.ncells < 50

    def test_zero_cutoff(self):
        """Test zero cutoff (default)."""
        grid = create_hemigrid("equal_area", cutoff_theta=0.0)
        # Should include cells near zenith
        assert grid.grid["theta"].min() < 0.1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
