"""Time encoding of the stores: one unit that fits every sampling.

xarray chooses the unit of a datetime variable at the first write of a group
(e.g. ``minutes since 2025-01-01`` when all epochs are whole minutes) and keeps
it for every append. Times that do not fit that unit are encoded in another
unit and written as if they were in the stored one: 30 s epochs appended to a
group in minutes land months later, and xarray only warns (seen 2026-10-05,
A12). New groups therefore store times in nanoseconds since 1970-01-01, and
every write into an existing group first checks that its times fit the unit
already on disk.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import xarray as xr
import zarr
from zarr.errors import GroupNotFoundError

#: Unit of every datetime variable in a new store group.
TIME_UNITS = "nanoseconds since 1970-01-01"

_UNIT_NS = {
    "nanoseconds": 1,
    "microseconds": 1_000,
    "milliseconds": 1_000_000,
    "seconds": 1_000_000_000,
    "minutes": 60_000_000_000,
    "hours": 3_600_000_000_000,
    "days": 86_400_000_000_000,
}


def time_encoding() -> dict[str, Any]:
    """Encoding of a datetime variable in a new group."""
    return {"units": TIME_UNITS, "dtype": "int64"}


def with_time_encoding(ds: xr.Dataset) -> xr.Dataset:
    """Return ``ds`` with :data:`TIME_UNITS` on every datetime variable.

    It takes effect when a group is created; on an append, xarray keeps
    the unit already on disk (see :func:`check_times_fit`). Datetimes of
    another resolution (e.g. ``datetime64[s]``) are converted to
    nanoseconds first: xarray writes them as NaT in a nanosecond unit.
    """
    ds = ds.copy(deep=False)
    for name, var in list(ds.variables.items()):
        if var.dtype.kind != "M":
            continue
        converted = var.astype("datetime64[ns]")
        converted.encoding = {**var.encoding, **time_encoding()}
        if name in ds.coords:
            ds = ds.assign_coords({name: converted})
        else:
            ds[name] = converted
    return ds


def check_times_fit(ds: xr.Dataset, store: Any, group: str) -> None:
    """Refuse times that the existing ``group`` cannot store faithfully.

    Parameters
    ----------
    ds : xr.Dataset
        Data about to be written into ``group``.
    store : zarr store
        The (session or fork) store the data are written to.
    group : str
        Store group; nothing is checked if it does not exist yet.

    Raises
    ------
    ValueError
        If a datetime variable of ``ds`` holds times that are not whole
        multiples of the unit of the stored variable.
    """
    try:
        root = zarr.open_group(store, mode="r")
    except GroupNotFoundError:
        return  # empty store
    stored_group = root.get(group)
    if not isinstance(stored_group, zarr.Group):
        return
    for name, var in ds.variables.items():
        stored = stored_group.get(str(name))
        if var.dtype.kind != "M" or not isinstance(stored, zarr.Array):
            continue
        units = stored.attrs.get("units")
        if not isinstance(units, str) or stored.dtype.kind not in "iu":
            continue
        unit, _, reference = units.partition(" since ")
        step = _UNIT_NS.get(unit.strip())
        if step is None or step == 1:
            continue
        ns = np.asarray(var.values, dtype="datetime64[ns]")
        ns = ns[~np.isnat(ns)].astype(np.int64)
        offset = ns - pd.Timestamp(reference.strip()).as_unit("ns").value
        bad = np.flatnonzero(offset % step)
        if bad.size:
            first = np.datetime64(int(ns[bad[0]]), "ns")
            msg = (
                f"Group '{group}' stores '{name}' in '{units}', but the new data "
                f"have times that are not whole {unit.strip()} (e.g. {first}); "
                "they would be written at wrong times. Write them to a new "
                f"store (new stores use '{TIME_UNITS}')."
            )
            raise ValueError(msg)


def prepare_times(ds: xr.Dataset, store: Any, group: str) -> xr.Dataset:
    """Check ``ds`` against ``group`` and give it the store's time encoding.

    Call this right before every write into a store group.
    """
    check_times_fit(ds, store, group)
    return with_time_encoding(ds)


def with_time_units(
    ds: xr.Dataset, encoding: dict[str, dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    """Add the time encoding to an ``encoding=`` mapping for ``ds``.

    An ``encoding=`` argument replaces a variable's own encoding, so the
    time unit must be part of it.
    """
    merged = {name: dict(enc) for name, enc in encoding.items()}
    for name, var in ds.variables.items():
        if var.dtype.kind == "M":
            merged[str(name)] = {**merged.get(str(name), {}), **time_encoding()}
    return merged
