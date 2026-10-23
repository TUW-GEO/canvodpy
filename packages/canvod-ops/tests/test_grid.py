"""Tests for grid assignment operation."""

import numpy as np
import xarray as xr

from canvod.ops.grid import GridAssignment, grid_assign


class TestGridAssignment:
    def test_skips_without_phi_theta(self, ds_no_phi_theta: xr.Dataset):
        """Should skip and return unchanged dataset when phi/theta missing."""
        op = GridAssignment()
        out, result = op(ds_no_phi_theta)

        assert "skipped" in result.notes
        xr.testing.assert_identical(out, ds_no_phi_theta)

    def test_assigns_cell_ids(self, sample_ds: xr.Dataset):
        """Should add cell_id variable when phi/theta present."""
        op = GridAssignment(grid_type="equal_area", angular_resolution=10.0)
        out, result = op(sample_ds)

        grid_name = "equal_area_10.0deg"
        cell_var = f"cell_id_{grid_name}"
        assert cell_var in out.data_vars
        assert out[cell_var].dims == ("epoch", "sid")
        assert result.op_name == "grid_assign"
        assert "skipped" not in result.notes

    def test_result_parameters(self, sample_ds: xr.Dataset):
        """OpResult should capture the grid parameters."""
        op = GridAssignment(grid_type="equal_area", angular_resolution=5.0)
        _, result = op(sample_ds)

        assert result.parameters["grid_type"] == "equal_area"
        assert result.parameters["angular_resolution"] == 5.0

    def test_convenience_function(self, sample_ds: xr.Dataset):
        """grid_assign convenience wrapper should work."""
        out = grid_assign(sample_ds, angular_resolution=10.0)
        cell_var = "cell_id_equal_area_10.0deg"
        assert cell_var in out.data_vars

    def test_phi_theta_as_data_variables(self, sample_ds: xr.Dataset):
        """The runs store phi/theta as data variables, not coordinates."""
        as_vars = sample_ds.reset_coords(["phi", "theta"])
        op = GridAssignment(grid_type="equal_area", angular_resolution=10.0)
        out, result = op(as_vars)
        expected, _ = op(sample_ds)
        assert "skipped" not in result.notes
        np.testing.assert_array_equal(
            out["cell_id_equal_area_10.0deg"].values,
            expected["cell_id_equal_area_10.0deg"].values,
        )
