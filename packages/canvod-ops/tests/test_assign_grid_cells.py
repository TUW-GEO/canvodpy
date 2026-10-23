"""Tests for assigning the data already in a store group to grid cells (A22).

Covers the two cases of adding cells to stored data: all data at once, and
data appended afterwards by a run, which must carry the same cells.
"""

from __future__ import annotations

import numpy as np
import pytest
import xarray as xr

from canvod.config.models import (
    GridAssignmentConfig,
    PreprocessingConfig,
    PreprocessingMismatchError,
)
from canvod.grids import add_cell_ids_to_ds_fast, create_hemigrid
from canvod.ops import assign_grid_cells_in_store, preprocess_files
from canvod.store import open_gnss_store
from canvod.store.prepare import GroupVariablesMismatchError
from canvod.store_metadata.testing import create_test_store, give_test_metadata

_GROUP = "canopy_01"
_CELLS = "cell_id_equal_area_10.0deg"
_GRID = PreprocessingConfig(
    grid_assignment=GridAssignmentConfig(
        grid_type="equal_area", angular_resolution=10.0
    )
)


def _file(day: int, preprocessing: PreprocessingConfig | None) -> xr.Dataset:
    """One file of a day, preprocessed as a run with ``preprocessing`` does."""
    rng = np.random.default_rng(day)
    n, sids = 6, ["G01|L1|C", "G02|L1|C", "G05|L1|C"]
    epochs = np.datetime64(f"2025-01-0{day}T00:00:00", "ns") + np.arange(
        n
    ) * np.timedelta64(5, "s")
    ds = xr.Dataset(
        {
            "SNR": (("epoch", "sid"), rng.uniform(20, 50, (n, 3))),
            "phi": (("epoch", "sid"), rng.uniform(0, 2 * np.pi, (n, 3))),
            "theta": (("epoch", "sid"), rng.uniform(0, np.pi / 2.2, (n, 3))),
        },
        coords={"epoch": ("epoch", epochs, {"time_system": "GPS"}), "sid": sids},
        attrs={"File Hash": f"hash{day}"},
    )
    [(_, out)] = preprocess_files([(f"day{day}", ds)], preprocessing)
    return out


@pytest.fixture
def store(tmp_path):
    store = open_gnss_store(create_test_store(tmp_path / "site" / "gnss_store"))
    give_test_metadata(store.store_path)
    store.write_initial_group(_file(1, None), _GROUP)
    store.append_to_group(_file(2, None), _GROUP)
    return store


def test_assigns_all_stored_observations(store) -> None:
    rows_before = store.metadata_row_count(_GROUP)

    assign_grid_cells_in_store(store, _GROUP, "equal_area", 10.0)

    group = store.read_group(_GROUP).compute()
    grid = create_hemigrid("equal_area", angular_resolution=10.0)
    expected = add_cell_ids_to_ds_fast(group[["phi", "theta"]], grid, "x")
    np.testing.assert_array_equal(group[_CELLS].values, expected["cell_id_x"].values)
    assert store.metadata_row_count(_GROUP) == rows_before + 1


def test_run_with_the_same_grid_appends(store) -> None:
    assign_grid_cells_in_store(store, _GROUP, "equal_area", 10.0)
    new = _file(3, _GRID)

    store.check_preprocessing_matches(_GROUP, new)
    store.append_to_group(new, _GROUP)

    group = store.read_group(_GROUP)
    assert group[_CELLS].shape == group["SNR"].shape
    assert np.isfinite(group[_CELLS].values[-1]).all()


def test_run_without_the_grid_refused(store) -> None:
    assign_grid_cells_in_store(store, _GROUP, "equal_area", 10.0)
    new = _file(3, None)

    with pytest.raises(PreprocessingMismatchError):
        store.check_preprocessing_matches(_GROUP, new)
    with pytest.raises(GroupVariablesMismatchError):
        store.append_to_group(new, _GROUP)


def test_second_assignment_of_the_same_grid_refused(store) -> None:
    assign_grid_cells_in_store(store, _GROUP, "equal_area", 10.0)
    with pytest.raises(ValueError, match="already has"):
        assign_grid_cells_in_store(store, _GROUP, "equal_area", 10.0)


def test_store_dataset_with_cell_ids_keeps_log_book(store) -> None:
    from canvod.grids import store_dataset_with_cell_ids

    rows_before = store.metadata_row_count(_GROUP)
    ds = store.read_group(_GROUP).compute()
    grid = create_hemigrid("equal_area", angular_resolution=10.0)
    ds = add_cell_ids_to_ds_fast(ds, grid, "x")

    with pytest.warns(FutureWarning, match="assign_grid_cells_in_store"):
        store_dataset_with_cell_ids(ds, store, _GROUP)

    assert store.metadata_row_count(_GROUP) == rows_before + 1
    assert "cell_id_x" in store.read_group(_GROUP)
