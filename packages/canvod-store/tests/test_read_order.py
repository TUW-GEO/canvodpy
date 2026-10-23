"""Reading a group returns time order; time and day selection are exact (#311).

A group's ``epoch`` axis is in write order on disk: a file is appended at
the end of its group, so days processed out of order (2027, then 2025,
then 2026, or a late file of a day already processed) are stored out of
order. ``read_group`` puts them in time order, and its ``time_slice`` and
``date`` selection give the same result as on the same data in order.
"""

from __future__ import annotations

import numpy as np
import pytest
import xarray as xr
from _helpers import make_synthetic_dataset, new_gnss_store

_GROUP = "canopy_01"
_DAYS = ["2027-01-01", "2025-01-01", "2026-01-01"]


def _write(store, days: list[str], slots: tuple[int, ...] = (0,)) -> None:
    datasets = [
        make_synthetic_dataset(slot=slot, n_epochs=4, day=day)
        for day in days
        for slot in slots
    ]
    store.write_initial_group(datasets[0], _GROUP)
    for ds in datasets[1:]:
        store.append_to_group(ds, _GROUP)


@pytest.fixture
def out_of_order(tmp_path):
    store = new_gnss_store(tmp_path / "out_of_order")
    _write(store, _DAYS)
    return store


@pytest.fixture
def in_order(tmp_path):
    store = new_gnss_store(tmp_path / "in_order")
    _write(store, sorted(_DAYS))
    return store


def _epochs(ds) -> np.ndarray:
    return ds["epoch"].values


def test_group_is_stored_out_of_order(out_of_order) -> None:
    """The premise of these tests: the axis on disk is in write order."""
    with out_of_order.readonly_session("main") as session:
        stored = xr.open_zarr(session.store, group=_GROUP, consolidated=False)
        epochs = _epochs(stored)
    assert not np.all(epochs[:-1] < epochs[1:])


def test_group_written_out_of_order_reads_in_time_order(out_of_order) -> None:
    epochs = _epochs(out_of_order.read_group(_GROUP))
    assert len(epochs) == 12
    assert np.all(epochs[:-1] < epochs[1:])


def test_data_follows_its_epochs(out_of_order, in_order) -> None:
    got = out_of_order.read_group(_GROUP).compute()
    expected = in_order.read_group(_GROUP).compute()
    np.testing.assert_array_equal(_epochs(got), _epochs(expected))
    np.testing.assert_array_equal(got["S1C"].values, expected["S1C"].values)


@pytest.mark.parametrize(
    "time_slice",
    [
        slice("2025-01-01", "2026-01-01T00:00:10"),  # bounds not on an epoch
        slice("2025-01-01T00:00:00", "2026-01-01T00:00:05"),  # bounds on epochs
        slice("2026-01-01", None),
    ],
)
def test_time_slice_matches_data_in_order(out_of_order, in_order, time_slice) -> None:
    got = out_of_order.read_group(_GROUP, time_slice=time_slice)
    expected = in_order.read_group(_GROUP, time_slice=time_slice)
    assert len(_epochs(expected)) > 0
    np.testing.assert_array_equal(_epochs(got), _epochs(expected))


def test_date_selects_exactly_one_day(tmp_path) -> None:
    store = new_gnss_store(tmp_path / "days")
    _write(store, ["2025-01-02", "2025-01-01", "2025-01-03"])
    epochs = _epochs(store.read_group(_GROUP, date="2025002"))
    assert len(epochs) == 4
    assert epochs[0] == np.datetime64("2025-01-02T00:00:00")
    assert epochs[-1] < np.datetime64("2025-01-03T00:00:00")


def test_late_file_of_a_day_reads_in_time_order(tmp_path) -> None:
    store = new_gnss_store(tmp_path / "late")
    _write(store, ["2025-01-01"], slots=(1, 2, 0))
    epochs = _epochs(store.read_group(_GROUP, date="2025001"))
    assert len(epochs) == 12
    assert np.all(epochs[:-1] < epochs[1:])


def test_deduplicated_read_is_in_time_order(out_of_order) -> None:
    epochs = _epochs(out_of_order.read_group_deduplicated(_GROUP))
    assert len(epochs) == 12
    assert np.all(epochs[:-1] < epochs[1:])
