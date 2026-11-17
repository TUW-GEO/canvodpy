"""Tests for canvod.grids.aggregation module."""

import sys

import numpy as np
import pandas as pd
import polars as pl
import pytest
import xarray as xr

from canvod.grids.aggregation import (
    CellAggregator,
    aggregate_data_to_grid,
    analyze_diurnal_patterns,
    analyze_spatial_patterns,
    compute_global_average,
    compute_percell_timeseries,
    compute_regional_average,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_vod_dataset(
    n_epochs: int = 10,
    n_sids: int = 5,
    cell_var: str = "cell_id_equal_area_2deg",
    n_cells: int = 4,
    seed: int = 42,
) -> xr.Dataset:
    """Create a synthetic VOD dataset with (epoch, sid) dims."""
    rng = np.random.default_rng(seed)
    epochs = pd.date_range("2024-01-01", periods=n_epochs, freq="h")
    sids = [f"G{i:02d}|L1C" for i in range(1, n_sids + 1)]

    vod = rng.uniform(0.1, 1.0, size=(n_epochs, n_sids))
    cell_ids = rng.integers(0, n_cells, size=(n_epochs, n_sids)).astype(float)

    return xr.Dataset(
        {
            "VOD": (["epoch", "sid"], vod),
            cell_var: (["epoch", "sid"], cell_ids),
        },
        coords={"epoch": epochs, "sid": sids},
    )


class _MockGrid:
    """Minimal mock for GridData used by aggregate_data_to_grid."""

    def __init__(self, ncells: int = 4):
        self._ncells = ncells

    @property
    def ncells(self) -> int:
        return self._ncells


# ---------------------------------------------------------------------------
# aggregate_data_to_grid
# ---------------------------------------------------------------------------


class TestAggregateDataToGrid:
    """Tests for aggregate_data_to_grid()."""

    def test_basic_aggregation_mean(self):
        ds = _make_vod_dataset(n_cells=4)
        grid = _MockGrid(ncells=4)
        result = aggregate_data_to_grid(ds, grid, stat="mean")

        assert isinstance(result, np.ndarray)
        assert result.shape == (4,)
        # At least some cells should have valid data
        assert np.any(np.isfinite(result))

    def test_basic_aggregation_median(self):
        ds = _make_vod_dataset(n_cells=4)
        grid = _MockGrid(ncells=4)
        result = aggregate_data_to_grid(ds, grid, stat="median")

        assert result.shape == (4,)
        assert np.any(np.isfinite(result))

    def test_basic_aggregation_std(self):
        ds = _make_vod_dataset(n_cells=4)
        grid = _MockGrid(ncells=4)
        result = aggregate_data_to_grid(ds, grid, stat="std")

        assert result.shape == (4,)

    def test_unsupported_stat_raises(self):
        ds = _make_vod_dataset()
        grid = _MockGrid()
        with pytest.raises(ValueError, match="Unsupported stat"):
            aggregate_data_to_grid(ds, grid, stat="max")

    def test_sid_filtering(self):
        ds = _make_vod_dataset(n_sids=5)
        grid = _MockGrid(ncells=4)
        result = aggregate_data_to_grid(
            ds, grid, sid=["G01|L1C", "G02|L1C"], stat="mean"
        )

        assert result.shape == (4,)

    def test_time_range_filtering(self):
        ds = _make_vod_dataset(n_epochs=20)
        grid = _MockGrid(ncells=4)
        result = aggregate_data_to_grid(
            ds,
            grid,
            time_range=("2024-01-01T05:00", "2024-01-01T10:00"),
            stat="mean",
        )

        assert result.shape == (4,)

    def test_no_sid_dimension_raises(self):
        """Dataset without sid dim should raise ValueError."""
        ds = xr.Dataset(
            {"VOD": (["epoch"], [1.0, 2.0])},
            coords={"epoch": pd.date_range("2024-01-01", periods=2, freq="h")},
        )
        ds["cell_id_equal_area_2deg"] = (["epoch"], [0.0, 1.0])
        grid = _MockGrid()
        with pytest.raises(ValueError, match="No SID dimension"):
            aggregate_data_to_grid(ds, grid)

    def test_nan_vod_values_excluded(self):
        """NaN VOD values should not contribute to aggregation."""
        ds = _make_vod_dataset(n_cells=2, n_sids=2, n_epochs=4)
        # Set all values in cell 0 to NaN
        vod = ds["VOD"].values.copy()
        cell_ids = ds["cell_id_equal_area_2deg"].values.copy()
        cell_ids[:] = 0.0
        cell_ids[0, 0] = 1.0
        vod[:, :] = np.nan
        vod[0, 0] = 0.5
        ds["VOD"] = (["epoch", "sid"], vod)
        ds["cell_id_equal_area_2deg"] = (["epoch", "sid"], cell_ids)

        grid = _MockGrid(ncells=2)
        result = aggregate_data_to_grid(ds, grid, stat="mean")

        assert result.shape == (2,)
        assert np.isnan(result[0])  # Cell 0 has all NaN
        assert np.isfinite(result[1])  # Cell 1 has one valid value


# ---------------------------------------------------------------------------
# CellAggregator
# ---------------------------------------------------------------------------


class TestCellAggregator:
    """Tests for CellAggregator static methods."""

    @pytest.fixture()
    def sample_df(self) -> pl.DataFrame:
        return pl.DataFrame(
            {
                "cell_id": [0, 0, 0, 1, 1, 2],
                "VOD": [0.1, 0.2, 0.3, 0.5, 0.6, 1.0],
            }
        )

    def test_aggregate_mean(self, sample_df):
        result = CellAggregator.aggregate_by_cell(sample_df, method="mean")
        assert "cell_id" in result.columns
        assert "VOD" in result.columns
        assert len(result) == 3

    def test_aggregate_median(self, sample_df):
        result = CellAggregator.aggregate_by_cell(sample_df, method="median")
        cell_0 = result.filter(pl.col("cell_id") == 0)["VOD"][0]
        assert cell_0 == pytest.approx(0.2)

    def test_aggregate_std(self, sample_df):
        result = CellAggregator.aggregate_by_cell(sample_df, method="std")
        assert len(result) == 3

    def test_aggregate_count(self, sample_df):
        result = CellAggregator.aggregate_by_cell(sample_df, method="count")
        cell_0_count = result.filter(pl.col("cell_id") == 0)["VOD"][0]
        assert cell_0_count == 3

    def test_missing_cell_id_column(self):
        df = pl.DataFrame({"value": [1.0, 2.0]})
        with pytest.raises(ValueError, match="cell_id"):
            CellAggregator.aggregate_by_cell(df)

    def test_missing_value_column(self):
        df = pl.DataFrame({"cell_id": [0, 1]})
        with pytest.raises(ValueError, match="VOD"):
            CellAggregator.aggregate_by_cell(df)

    def test_unknown_method(self, sample_df):
        with pytest.raises(ValueError, match="Unknown method"):
            CellAggregator.aggregate_by_cell(sample_df, method="max")

    def test_custom_value_var(self):
        df = pl.DataFrame({"cell_id": [0, 0, 1], "snr": [10.0, 20.0, 30.0]})
        result = CellAggregator.aggregate_by_cell(df, value_var="snr", method="mean")
        assert "snr" in result.columns
        assert len(result) == 2


# ---------------------------------------------------------------------------
# Analysis functions
# ---------------------------------------------------------------------------


class TestAnalysisFunctions:
    """Tests for compute_global_average, compute_regional_average, etc."""

    @pytest.fixture()
    def percell_ds(self) -> xr.Dataset:
        """Minimal per-cell time-series dataset."""
        n_cells, n_times = 4, 24
        rng = np.random.default_rng(0)
        times = pd.date_range("2024-01-01", periods=n_times, freq="h")
        cells = np.arange(n_cells)

        return xr.Dataset(
            {
                "cell_timeseries": (
                    ["cell", "time"],
                    rng.uniform(0.1, 1.0, (n_cells, n_times)),
                ),
                "cell_weights": (
                    ["cell", "time"],
                    rng.integers(1, 10, (n_cells, n_times)).astype(float),
                ),
            },
            coords={"cell": cells, "time": times},
        )

    def test_compute_global_average(self, percell_ds):
        result = compute_global_average(percell_ds)
        assert "global_timeseries" in result.data_vars
        assert "spatial_std" in result.data_vars
        assert "total_weights" in result.data_vars
        assert "active_cells" in result.data_vars
        assert result["global_timeseries"].dims == ("time",)

    def test_compute_regional_average(self, percell_ds):
        result = compute_regional_average(percell_ds, region_cells=[0, 1])
        assert result.dims == ("time",)
        assert len(result) == 24

    def test_analyze_diurnal_patterns(self, percell_ds):
        result = analyze_diurnal_patterns(percell_ds)
        assert "hour" in result.dims

    def test_analyze_spatial_patterns(self, percell_ds):
        result = analyze_spatial_patterns(percell_ds)
        assert "time" not in result.dims
        assert "cell" in result.dims


# ---------------------------------------------------------------------------
# compute_percell_timeseries
# ---------------------------------------------------------------------------


class _PolarsGrid:
    """Grid with a polars cell table, as GridData holds it (radians)."""

    def __init__(self, theta_deg: list[float], phi_deg: list[float]):
        self.grid = pl.DataFrame(
            {"theta": np.radians(theta_deg), "phi": np.radians(phi_deg)}
        )

    @property
    def ncells(self) -> int:
        return self.grid.height


class TestComputePercellTimeseries:
    """Cell angles of the per-cell time series, in degrees."""

    @pytest.fixture()
    def grid(self):
        return _PolarsGrid([10.0, 30.0, 50.0, 70.0], [0.0, 90.0, 180.0, 270.0])

    def test_cell_angles_of_all_cells(self, grid):
        result = compute_percell_timeseries(_make_vod_dataset(), grid)
        np.testing.assert_allclose(result["cell_theta"], [10.0, 30.0, 50.0, 70.0])
        np.testing.assert_allclose(result["cell_phi"], [0.0, 90.0, 180.0, 270.0])

    def test_cell_angles_of_a_theta_range(self, grid):
        result = compute_percell_timeseries(
            _make_vod_dataset(), grid, theta_range=(25.0, 55.0)
        )
        np.testing.assert_allclose(result["cell_theta"], [30.0, 50.0])
        np.testing.assert_allclose(result["cell_phi"], [90.0, 180.0])

    def test_runs_without_pyarrow(self, grid, monkeypatch):
        monkeypatch.setitem(sys.modules, "pyarrow", None)
        result = compute_percell_timeseries(_make_vod_dataset(), grid)
        np.testing.assert_allclose(result["cell_theta"], [10.0, 30.0, 50.0, 70.0])
