"""Store times keep their value whatever the sampling of later writes.

xarray fixes a datetime unit at a group's first write and silently writes
times that do not fit it at wrong values on append (30 s epochs into a group
in minutes landed months later, 2026-10-05).
"""

import icechunk
import numpy as np
import pytest
import xarray as xr
import zarr
from icechunk.xarray import to_icechunk

from canvod.store.time_encoding import (
    TIME_UNITS,
    check_times_fit,
    prepare_times,
    with_time_units,
)


def _ds(start: str, n: int, step_s: int) -> xr.Dataset:
    epochs = np.datetime64(start, "ns") + np.arange(n) * np.timedelta64(step_s, "s")
    return xr.Dataset(
        {"SNR": (("epoch",), np.arange(n, dtype="float32"))},
        coords={"epoch": epochs},
    )


@pytest.fixture
def repo(tmp_path):
    return icechunk.Repository.create(icechunk.local_filesystem_storage(str(tmp_path)))


def _write(repo, ds, prepare=True, **kwargs):
    session = repo.writable_session("main")
    if prepare:
        ds = prepare_times(ds, session.store, "g")
    to_icechunk(ds, session, group="g", **kwargs)
    session.commit("w")


def _epochs(repo):
    session = repo.readonly_session(branch="main")
    return xr.open_zarr(session.store, group="g", consolidated=False).epoch.values


def test_new_group_stores_nanoseconds_so_any_sampling_appends(repo):
    _write(repo, _ds("2025-01-01", 3, 60), mode="w")
    _write(repo, _ds("2025-01-03", 3, 30), append_dim="epoch")
    session = repo.readonly_session(branch="main")
    assert (
        zarr.open_group(session.store, mode="r")["g/epoch"].attrs["units"] == TIME_UNITS
    )
    np.testing.assert_array_equal(
        _epochs(repo)[3:], _ds("2025-01-03", 3, 30).epoch.values
    )


def test_append_that_does_not_fit_an_existing_unit_is_refused(repo):
    # A group written before this fix: unit inferred from whole minutes.
    _write(repo, _ds("2025-01-01", 3, 60), prepare=False, mode="w")
    with pytest.raises(ValueError, match="not whole minutes"):
        _write(repo, _ds("2025-01-03", 3, 30), append_dim="epoch")
    assert len(_epochs(repo)) == 3


def test_append_that_fits_an_existing_unit_is_written(repo):
    _write(repo, _ds("2025-01-01", 3, 60), prepare=False, mode="w")
    _write(repo, _ds("2025-01-03", 3, 60), append_dim="epoch")
    np.testing.assert_array_equal(
        _epochs(repo)[3:], _ds("2025-01-03", 3, 60).epoch.values
    )


def test_missing_group_is_not_checked(repo):
    check_times_fit(_ds("2025-01-01", 3, 1), repo.readonly_session("main").store, "g")


def test_encoding_argument_gets_the_time_unit():
    ds = _ds("2025-01-01", 3, 60)
    merged = with_time_units(ds, {"epoch": {"chunks": (3,)}, "SNR": {"chunks": (3,)}})
    assert merged["epoch"] == {"chunks": (3,), "units": TIME_UNITS, "dtype": "int64"}
    assert merged["SNR"] == {"chunks": (3,)}


def test_second_resolution_times_are_kept(repo):
    """xarray writes datetime64[s] as NaT in a nanosecond unit."""
    ds = _ds("2025-01-01", 3, 5)
    ds = ds.assign_coords(epoch=ds.epoch.values.astype("datetime64[s]"))
    _write(repo, ds, mode="w")
    np.testing.assert_array_equal(
        _epochs(repo), ds.epoch.values.astype("datetime64[ns]")
    )
