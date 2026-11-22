"""Per-cell analysis bins cells by their polar angle ``cell_theta``."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from canvod.grids.analysis.per_cell_analysis import (
    PerCellVODAnalyzer,
    _compute_single_heatmap,
)

OVERHEAD_VOD = 1.0


@pytest.fixture
def percell():
    """Three cells: overhead (θ = 0°), mid-sky (45°), near the horizon (85°).

    Only the overhead cell has VOD 1.0, so it shows where that cell lands.
    """
    theta = np.array([0.0, 45.0, 85.0])
    vod = np.array([OVERHEAD_VOD, 0.5, 0.2])
    time = pd.date_range("2025-01-01", periods=4, freq="D")
    return xr.Dataset(
        {
            "cell_timeseries": (["cell", "time"], np.repeat(vod[:, None], 4, axis=1)),
            "cell_theta": (["cell"], theta),
            "cell_phi": (["cell"], np.zeros(3)),
        },
        coords={"cell": np.arange(3), "time": time},
    )


def test_the_overhead_cell_is_in_the_first_bin_of_the_radial_distribution(percell):
    radial = PerCellVODAnalyzer(percell)._compute_radial_distribution(percell)
    assert radial["bin_labels"][0] == "0-5°"
    np.testing.assert_allclose(radial["binned_data"][0], [OVERHEAD_VOD])


def test_the_overhead_cell_is_in_the_first_row_of_the_theta_time_heatmap(percell):
    heatmap, _ = PerCellVODAnalyzer(percell)._compute_single_theta_time_heatmap(
        percell, "daily", theta_bins=18
    )
    np.testing.assert_allclose(heatmap[0], OVERHEAD_VOD)
    np.testing.assert_allclose(heatmap[17], 0.2)


def test_the_overhead_cell_is_in_the_first_row_of_the_heatmap(percell):
    heatmap = _compute_single_heatmap(percell, theta_bins=18)
    np.testing.assert_allclose(heatmap[0], OVERHEAD_VOD)
    np.testing.assert_allclose(heatmap[17], 0.2)
