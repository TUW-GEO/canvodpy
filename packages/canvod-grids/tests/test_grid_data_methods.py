"""Tests for canvod.grids.core.grid_data.GridData methods."""

import numpy as np
import polars as pl
import pytest

from canvod.grids.core.grid_data import GridData

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_grid_data(n_cells: int = 4, grid_type: str = "equal_area") -> GridData:
    """Create a minimal GridData for testing."""
    theta_values = np.linspace(0.1, 1.0, n_cells)
    phi_values = np.linspace(0.0, 2 * np.pi, n_cells, endpoint=False)

    # Create bounds
    theta_min = theta_values - 0.05
    theta_max = theta_values + 0.05
    phi_min = phi_values - 0.1
    phi_max = phi_values + 0.1

    grid_df = pl.DataFrame(
        {
            "phi": phi_values,
            "theta": theta_values,
            "phi_min": phi_min,
            "phi_max": phi_max,
            "theta_min": theta_min,
            "theta_max": theta_max,
        }
    )

    theta_lims = np.array([0.0, 0.5, 1.0])
    phi_lims = [
        np.array([0.0, np.pi, 2 * np.pi]),
        np.array([0.0, np.pi, 2 * np.pi]),
    ]
    cell_ids = [np.array([0, 1]), np.array([2, 3])]

    return GridData(
        grid=grid_df,
        theta_lims=theta_lims,
        phi_lims=phi_lims,
        cell_ids=cell_ids,
        grid_type=grid_type,
    )


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------


class TestGridDataProperties:
    """Tests for GridData properties."""

    def test_ncells(self):
        gd = _make_grid_data(n_cells=6)
        assert gd.ncells == 6

    def test_coords(self):
        gd = _make_grid_data(n_cells=4)
        coords = gd.coords
        assert isinstance(coords, pl.DataFrame)
        assert "phi" in coords.columns
        assert "theta" in coords.columns
        assert len(coords) == 4

    def test_frozen(self):
        gd = _make_grid_data()
        with pytest.raises(AttributeError):
            gd.grid_type = "new_type"


# ---------------------------------------------------------------------------
# get_solid_angles
# ---------------------------------------------------------------------------


class TestGetSolidAngles:
    """Tests for GridData.get_solid_angles()."""

    def test_geometric_fallback(self):
        """Default equal_area grid should use geometric solid angles."""
        gd = _make_grid_data(n_cells=4)
        angles = gd.get_solid_angles()

        assert isinstance(angles, np.ndarray)
        assert len(angles) == 4
        assert np.all(np.isfinite(angles))

    def test_positive_values(self):
        gd = _make_grid_data(n_cells=4)
        angles = gd.get_solid_angles()
        assert np.all(angles > 0)

    def test_precomputed_solid_angles(self):
        """If solid_angles is already set, return it directly."""
        precomputed = np.array([0.1, 0.2, 0.3, 0.4])
        gd = _make_grid_data(n_cells=4)
        # Use object.__setattr__ on frozen dataclass
        gd_with_angles = GridData(
            grid=gd.grid,
            theta_lims=gd.theta_lims,
            phi_lims=gd.phi_lims,
            cell_ids=gd.cell_ids,
            grid_type=gd.grid_type,
            solid_angles=precomputed,
        )
        result = gd_with_angles.get_solid_angles()
        np.testing.assert_array_equal(result, precomputed)


# ---------------------------------------------------------------------------
# get_patches
# ---------------------------------------------------------------------------


class TestGetPatches:
    """Tests for GridData.get_patches()."""

    def test_returns_series(self):
        gd = _make_grid_data(n_cells=4)
        patches = gd.get_patches()
        assert isinstance(patches, pl.Series)
        assert len(patches) == 4
        assert patches.name == "Patches"


# ---------------------------------------------------------------------------
# get_grid_stats
# ---------------------------------------------------------------------------


class TestGetGridStats:
    """Tests for GridData.get_grid_stats()."""

    def test_stats_keys(self):
        gd = _make_grid_data(n_cells=4)
        stats = gd.get_grid_stats()

        assert stats["total_cells"] == 4
        assert stats["grid_type"] == "equal_area"
        assert "solid_angle_mean_sr" in stats
        assert "solid_angle_std_sr" in stats
        assert "solid_angle_cv_percent" in stats
        assert "total_solid_angle_sr" in stats
        assert "hemisphere_solid_angle_sr" in stats

    def test_stats_values(self):
        gd = _make_grid_data(n_cells=4)
        stats = gd.get_grid_stats()

        assert stats["solid_angle_mean_sr"] > 0
        assert stats["hemisphere_solid_angle_sr"] == pytest.approx(2 * np.pi)

    def test_cells_per_band(self):
        gd = _make_grid_data(n_cells=4)
        stats = gd.get_grid_stats()

        assert stats["cells_per_band"] == [2, 2]
        assert stats["theta_bands"] == 3  # len(theta_lims) = boundaries count


# ---------------------------------------------------------------------------
# _geometric_solid_angles
# ---------------------------------------------------------------------------


class TestGeometricSolidAngles:
    """Tests for the _geometric_solid_angles fallback."""

    def test_known_values(self):
        """Full hemisphere cell should have solid angle = 2π."""
        grid_df = pl.DataFrame(
            {
                "phi": [np.pi],
                "theta": [np.pi / 4],
                "phi_min": [0.0],
                "phi_max": [2 * np.pi],
                "theta_min": [0.0],
                "theta_max": [np.pi / 2],
            }
        )
        gd = GridData(
            grid=grid_df,
            theta_lims=np.array([0.0, np.pi / 2]),
            phi_lims=[np.array([0.0, 2 * np.pi])],
            cell_ids=[np.array([0])],
            grid_type="equal_area",
        )
        angles = gd._geometric_solid_angles()
        # cos(0) - cos(pi/2) = 1 - 0 = 1
        # delta_phi = 2pi
        # omega = 2pi * 1 = 2pi
        assert angles[0] == pytest.approx(2 * np.pi)


class TestHealpixWithoutHealpy:
    """HEALPix pixel areas come from nside alone; healpy is not needed."""

    @staticmethod
    def _healpix_grid(nside: int) -> GridData:
        gd = _make_grid_data(n_cells=4)
        return GridData(
            grid=gd.grid.with_columns(pl.lit(nside).alias("healpix_nside")),
            theta_lims=gd.theta_lims,
            phi_lims=gd.phi_lims,
            cell_ids=gd.cell_ids,
            grid_type="healpix",
        )

    def test_solid_angle_is_the_pixel_area(self):
        # nside 4: 192 pixels of equal area, 4π / 192 = π / 48 sr each
        angles = self._healpix_grid(4).get_solid_angles()
        np.testing.assert_allclose(angles, np.pi / 48)

    def test_stats(self):
        stats = self._healpix_grid(4).get_grid_stats()
        assert stats["healpix_npix_total"] == 192
        assert stats["healpix_pixel_area_sr"] == pytest.approx(np.pi / 48)
        # The square root of the pixel area, in arc minutes
        assert stats["healpix_resolution_arcmin"] == pytest.approx(
            np.degrees(np.sqrt(np.pi / 48)) * 60
        )
