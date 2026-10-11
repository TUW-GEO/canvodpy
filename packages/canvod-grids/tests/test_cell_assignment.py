"""Tests for cell assignment operations.

Each observation is assigned to the grid cell that contains it.

Tests cover:
- add_cell_ids_to_ds_fast() - eager and dask
- the deprecated add_cell_ids_to_vod_fast() / add_cell_ids_to_vod()
- containment for every grid type, also where the nearest cell center
  belongs to another cell
- Edge case coordinates (zenith, horizon, wrapping)
"""

from __future__ import annotations

import numpy as np
import pytest
import xarray as xr

from canvod.grids import create_hemigrid
from canvod.grids._internal.cell_lookup import cell_lookup
from canvod.grids.operations import (
    add_cell_ids_to_ds_fast,
    add_cell_ids_to_vod,
    add_cell_ids_to_vod_fast,
)


@pytest.fixture
def sample_grid():
    """Create sample grid for testing."""
    return create_hemigrid("equal_area", angular_resolution=10.0)


@pytest.fixture
def sample_vod_dataset():
    """Create sample VOD xarray Dataset."""
    np.random.seed(42)
    n_epochs = 10
    n_sids = 10

    # Random points on hemisphere
    phi = np.random.uniform(0, 2 * np.pi, (n_epochs, n_sids))
    theta = np.random.uniform(0, np.pi / 2, (n_epochs, n_sids))
    vod = np.random.uniform(0, 1, (n_epochs, n_sids))

    return xr.Dataset(
        {
            "VOD": (["epoch", "sid"], vod),
        },
        coords={
            "phi": (["epoch", "sid"], phi),
            "theta": (["epoch", "sid"], theta),
            "epoch": np.arange(n_epochs),
            "sid": np.arange(n_sids),
        },
    )


class TestCellAssignmentBasic:
    """Test basic cell assignment functionality."""

    def test_add_cell_ids_to_vod_fast(self, sample_grid, sample_vod_dataset) -> None:
        """Test cell assignment."""
        result = add_cell_ids_to_ds_fast(sample_vod_dataset, sample_grid, "test_grid")

        # Should return Dataset with cell_id variable
        assert isinstance(result, xr.Dataset)
        assert "cell_id_test_grid" in result.variables

        # All observations should have assigned IDs
        cell_ids = result["cell_id_test_grid"].values
        assert cell_ids.shape == sample_vod_dataset["VOD"].shape

        # Valid cell IDs should be within grid range
        valid_ids = cell_ids[np.isfinite(cell_ids)]
        assert np.all(valid_ids >= 0)
        assert np.all(valid_ids < sample_grid.ncells)

    def test_cell_ids_are_described(self, sample_grid, sample_vod_dataset) -> None:
        """The cell ids say which grid they index (ACDD 1.3)."""
        result = add_cell_ids_to_ds_fast(sample_vod_dataset, sample_grid, "test_grid")

        assert result["cell_id_test_grid"].attrs == {
            "long_name": "Cell of the test_grid grid",
            "coverage_content_type": "referenceInformation",
        }

    def test_cell_assignment_preserves_original_data(
        self, sample_grid, sample_vod_dataset
    ) -> None:
        """Verify original data is preserved."""
        result = add_cell_ids_to_ds_fast(sample_vod_dataset, sample_grid, "test_grid")

        # Original variables should be present
        assert "VOD" in result.variables
        assert "phi" in result.coords
        assert "theta" in result.coords

        # Values should match original
        np.testing.assert_array_equal(
            result["VOD"].values, sample_vod_dataset["VOD"].values
        )


def _hemisphere_points(n: int = 20000) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(0)
    return rng.uniform(0, 2 * np.pi, n), np.arccos(rng.uniform(0, 1, n))


def _xyz(phi: np.ndarray, theta: np.ndarray) -> np.ndarray:
    return np.column_stack(
        [np.sin(theta) * np.cos(phi), np.sin(theta) * np.sin(phi), np.cos(theta)]
    )


class TestContainment:
    """The assigned cell contains the observation."""

    @pytest.mark.parametrize(
        "grid_type", ["equal_area", "equal_angle", "equirectangular"]
    )
    @pytest.mark.parametrize("phi_rotation", [0.0, 37.0])
    def test_ring_grids_use_cell_bounds(self, grid_type, phi_rotation) -> None:
        grid = create_hemigrid(
            grid_type, angular_resolution=5.0, phi_rotation=phi_rotation
        )
        phi, theta = _hemisphere_points()
        ids = cell_lookup(grid)(phi, theta)
        assert np.all(np.isfinite(ids)), "the grid covers the whole hemisphere"
        cells = grid.grid[ids.astype(int)]
        assert np.all(theta >= cells["theta_min"].to_numpy())
        assert np.all(theta <= cells["theta_max"].to_numpy())
        width = (cells["phi_max"] - cells["phi_min"]).to_numpy()
        assert np.all((phi - cells["phi_min"].to_numpy()) % (2 * np.pi) < width)

    def test_nearest_center_of_another_cell(self) -> None:
        """Near a cell corner the nearest center can belong to another cell."""
        grid = create_hemigrid("equal_area", angular_resolution=10.0)
        # Zenith cap [0°, 5°]; the first band [5°, 15°] starts with the
        # sector phi [0°, 60°] (cell 1, center theta 10°, phi 30°). A point
        # at theta 5.1°, phi 1° lies in cell 1 but is 5.1° from the cap
        # center and more than 5.1° from the center of cell 1.
        center = grid.grid.row(1, named=True)
        point = (np.deg2rad(1.0), np.deg2rad(5.1))
        assert (
            np.arccos(_xyz(np.array([point[0]]), np.array([point[1]])) @ [0, 0, 1])[0]
            < np.arccos(
                _xyz(np.array([point[0]]), np.array([point[1]]))
                @ _xyz(np.array([center["phi"]]), np.array([center["theta"]]))[0]
            )[0]
        )
        ids = cell_lookup(grid)(np.array([point[0]]), np.array([point[1]]))
        assert ids[0] == 1

    @pytest.mark.parametrize("grid_type", ["htm", "geodesic"])
    @pytest.mark.parametrize("phi_rotation", [0.0, 37.0])
    def test_triangle_grids_use_triangles(self, grid_type, phi_rotation) -> None:
        grid = create_hemigrid(
            grid_type, angular_resolution=10.0, phi_rotation=phi_rotation
        )
        phi, theta = _hemisphere_points()
        ids = cell_lookup(grid)(phi, theta)
        assert np.all(np.isfinite(ids))
        if grid_type == "htm":
            vertices = np.stack(
                [
                    np.asarray(grid.grid[c].to_list())
                    for c in ("htm_vertex_0", "htm_vertex_1", "htm_vertex_2")
                ],
                axis=1,
            )
        else:
            index = np.asarray(grid.grid["geodesic_vertices"].to_list())
            vertices = np.asarray(grid.vertices)[index]
        # The vertices are not rotated; rotate the observations back.
        p = _xyz(phi - np.deg2rad(phi_rotation), theta)
        v = vertices[ids.astype(int)]
        v0, v1, v2 = v[:, 0], v[:, 1], v[:, 2]
        side = np.sign(np.einsum("ij,ij->i", np.cross(v0, v1), v2))
        for a, b in ((v0, v1), (v1, v2), (v2, v0)):
            assert np.all(side * np.einsum("ij,ij->i", np.cross(a, b), p) >= -1e-12)

    def test_fibonacci_uses_voronoi_cells(self) -> None:
        from scipy.spatial import cKDTree

        grid = create_hemigrid("fibonacci", angular_resolution=10.0)
        phi, theta = _hemisphere_points()
        ids = cell_lookup(grid)(phi, theta)
        sites = np.asarray(grid.voronoi.points)
        nearest_site = cKDTree(sites).query(_xyz(phi, theta))[1]
        inside = np.isfinite(ids)
        cell_sites = np.asarray(grid.points_xyz)[ids[inside].astype(int)]
        np.testing.assert_allclose(sites[nearest_site[inside]], cell_sites)
        # Outside: the nearest site lies below the horizon, so no cell.
        assert np.all(sites[nearest_site[~inside], 2] < 0)

    def test_healpix_uses_pixels(self) -> None:
        hp = pytest.importorskip("healpy")
        grid = create_hemigrid("healpix", angular_resolution=10.0, nside=8)
        phi, theta = _hemisphere_points()
        ids = cell_lookup(grid)(phi, theta)
        assert np.all(np.isfinite(ids))
        pixels = grid.grid["healpix_ipix"].to_numpy()[ids.astype(int)]
        np.testing.assert_array_equal(pixels, hp.ang2pix(8, theta, phi))

    def test_outside_the_cutoff_is_nan(self) -> None:
        grid = create_hemigrid("equal_area", angular_resolution=5.0, cutoff_theta=10)
        ids = cell_lookup(grid)(np.zeros(2), np.deg2rad([79.9, 80.1]))
        assert np.isfinite(ids[0])
        assert np.isnan(ids[1])

    def test_loaded_triangle_grid_without_geometry_raises(self) -> None:
        from canvod.grids.core import GridData

        grid = create_hemigrid("geodesic", angular_resolution=10.0)
        stripped = GridData(
            grid=grid.grid,
            theta_lims=grid.theta_lims,
            phi_lims=grid.phi_lims,
            cell_ids=grid.cell_ids,
            grid_type="geodesic",
        )
        with pytest.raises(ValueError, match="create_hemigrid"):
            cell_lookup(stripped)


class TestAddCellIdsToDsFast:
    """Test Dask variant for xarray Datasets."""

    def test_add_cell_ids_to_ds_fast(self, sample_grid) -> None:
        """Test Dask variant with (epoch, sid) dask-backed dataset."""
        import dask.array as da

        np.random.seed(42)
        n_epochs = 5
        n_sids = 10

        phi = np.random.uniform(0, 2 * np.pi, (n_epochs, n_sids))
        theta = np.random.uniform(0, np.pi / 2, (n_epochs, n_sids))
        vod = np.random.uniform(0, 1, (n_epochs, n_sids))

        ds = xr.Dataset(
            {
                "vod": (["epoch", "sid"], da.from_array(vod, chunks=(5, 10))),
            },
            coords={
                "phi": (["epoch", "sid"], da.from_array(phi, chunks=(5, 10))),
                "theta": (["epoch", "sid"], da.from_array(theta, chunks=(5, 10))),
                "epoch": np.arange(n_epochs),
                "sid": np.arange(n_sids),
            },
        )

        result = add_cell_ids_to_ds_fast(ds, sample_grid, "test_grid")

        # Should have cell_id variable
        assert "cell_id_test_grid" in result.variables

        # Should preserve original data
        assert "vod" in result.variables
        assert "phi" in result.coords
        assert "theta" in result.coords

        # Cell IDs should be computable and valid
        cell_ids = result["cell_id_test_grid"].values
        assert cell_ids.shape == (n_epochs, n_sids)
        valid = cell_ids[np.isfinite(cell_ids)]
        assert np.all(valid >= 0)
        assert np.all(valid < sample_grid.ncells)


class TestEdgeCaseCoordinates:
    """Test edge cases and boundary coordinates."""

    def test_edge_case_zenith(self, sample_grid) -> None:
        """Test point at zenith (θ=0)."""
        zenith_ds = xr.Dataset(
            {"VOD": (["epoch", "sid"], [[0.5]])},
            coords={
                "phi": (["epoch", "sid"], [[0.0]]),
                "theta": (["epoch", "sid"], [[0.0]]),
                "epoch": [0],
                "sid": [0],
            },
        )

        result = add_cell_ids_to_ds_fast(zenith_ds, sample_grid, "test")

        # Should be assigned to valid cell
        cell_id = result["cell_id_test"].values[0, 0]
        assert np.isfinite(cell_id)
        assert 0 <= cell_id < sample_grid.ncells

    def test_edge_case_horizon(self, sample_grid) -> None:
        """Test points near horizon (θ≈π/2)."""
        horizon_ds = xr.Dataset(
            {"VOD": (["epoch", "sid"], [[0.5, 0.6, 0.7, 0.8]])},
            coords={
                "phi": (["epoch", "sid"], [[0.0, np.pi / 2, np.pi, 3 * np.pi / 2]]),
                "theta": (
                    ["epoch", "sid"],
                    [[np.pi / 2, np.pi / 2, np.pi / 2, np.pi / 2]],
                ),
                "epoch": [0],
                "sid": [0, 1, 2, 3],
            },
        )

        result = add_cell_ids_to_ds_fast(horizon_ds, sample_grid, "test")

        # All should be assigned
        cell_ids = result["cell_id_test"].values[0, :]
        assert len(cell_ids) == 4

        # All IDs should be valid
        assert np.all(np.isfinite(cell_ids))
        assert np.all(cell_ids >= 0)
        assert np.all(cell_ids < sample_grid.ncells)

    def test_edge_case_phi_wrapping(self, sample_grid) -> None:
        """Test points near phi=0/2π boundary."""
        wrap_ds = xr.Dataset(
            {"VOD": (["epoch", "sid"], [[0.5, 0.6, 0.7]])},
            coords={
                "phi": (["epoch", "sid"], [[0.0, 0.01, 2 * np.pi - 0.01]]),
                "theta": (["epoch", "sid"], [[np.pi / 4, np.pi / 4, np.pi / 4]]),
                "epoch": [0],
                "sid": [0, 1, 2],
            },
        )

        result = add_cell_ids_to_ds_fast(wrap_ds, sample_grid, "test")

        # Should handle wrapping correctly
        cell_ids = result["cell_id_test"].values[0, :]
        assert len(cell_ids) == 3

        # All should be valid
        assert np.all(np.isfinite(cell_ids))
        assert np.all(cell_ids >= 0)
        assert np.all(cell_ids < sample_grid.ncells)

    def test_nan_coordinates(self, sample_grid) -> None:
        """Test handling of NaN coordinates."""
        nan_ds = xr.Dataset(
            {"VOD": (["epoch", "sid"], [[0.5, 0.6, 0.7]])},
            coords={
                "phi": (["epoch", "sid"], [[0.5, np.nan, 1.0]]),
                "theta": (["epoch", "sid"], [[0.5, 0.6, np.nan]]),
                "epoch": [0],
                "sid": [0, 1, 2],
            },
        )

        result = add_cell_ids_to_ds_fast(nan_ds, sample_grid, "test")

        cell_ids = result["cell_id_test"].values[0, :]

        # First should be assigned, others should be NaN
        assert np.isfinite(cell_ids[0])
        assert np.isnan(cell_ids[1])
        assert np.isnan(cell_ids[2])


class TestSingleImplementation:
    """One implementation: dtype, dimension order, deprecated names."""

    def test_float64(self, sample_grid, sample_vod_dataset) -> None:
        result = add_cell_ids_to_ds_fast(sample_vod_dataset, sample_grid, "g")
        assert result["cell_id_g"].dtype == np.float64

    def test_data_variables_and_sid_epoch_order(
        self, sample_grid, sample_vod_dataset
    ) -> None:
        expected = add_cell_ids_to_ds_fast(sample_vod_dataset.copy(), sample_grid, "g")[
            "cell_id_g"
        ]
        as_vars = sample_vod_dataset.reset_coords(["phi", "theta"])
        as_vars["phi"] = as_vars["phi"].transpose("sid", "epoch")
        result = add_cell_ids_to_ds_fast(as_vars, sample_grid, "g")["cell_id_g"]
        assert result.dims == ("epoch", "sid")
        np.testing.assert_array_equal(result.values, expected.values)

    def test_dask_matches_eager(self, sample_grid, sample_vod_dataset) -> None:
        expected = add_cell_ids_to_ds_fast(sample_vod_dataset.copy(), sample_grid, "g")[
            "cell_id_g"
        ]
        lazy = sample_vod_dataset.chunk({"epoch": 3})
        result = add_cell_ids_to_ds_fast(lazy, sample_grid, "g")["cell_id_g"]
        assert result.chunks is not None
        np.testing.assert_array_equal(result.values, expected.values)

    def test_data_var_argument_deprecated(
        self, sample_grid, sample_vod_dataset
    ) -> None:
        with pytest.warns(FutureWarning, match="data_var"):
            add_cell_ids_to_ds_fast(sample_vod_dataset, sample_grid, "g", "VOD")

    @pytest.mark.parametrize("func", [add_cell_ids_to_vod_fast, add_cell_ids_to_vod])
    def test_deprecated_names_delegate(
        self, func, sample_grid, sample_vod_dataset
    ) -> None:
        expected = add_cell_ids_to_ds_fast(sample_vod_dataset.copy(), sample_grid, "g")[
            "cell_id_g"
        ]
        with pytest.warns(FutureWarning, match="add_cell_ids_to_ds_fast"):
            result = func(sample_vod_dataset.copy(), sample_grid, "g")
        np.testing.assert_array_equal(result["cell_id_g"].values, expected.values)
