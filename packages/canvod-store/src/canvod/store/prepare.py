"""The last step before every write of a dataset into a store group."""

from __future__ import annotations

from typing import Any

import xarray as xr
import zarr
import zarr.errors
from canvod.config.models import split_preprocessing

from canvod.store.time_encoding import prepare_times


class GroupVariablesMismatchError(Exception):
    """An append does not carry the same variables as the store group.

    Appending a dataset that lacks a variable of the group, or has one the
    group lacks, leaves that variable shorter than the others along the
    append dimension: the group can no longer be opened. Usually a setting
    changed between runs (e.g. ``processing.preprocessing.grid_assignment``
    or ``store_sbf_raw_observables``).

    Deliberately not a ``ValueError``: a run stops on it instead of skipping
    the receiver-day, because every later day would be refused the same way.
    """


def prepare_write(
    ds: xr.Dataset, store: Any, group: str, *, append_dim: str | None
) -> xr.Dataset:
    """Return ``ds`` as it is written into ``group``.

    Drops the in-memory preprocessing record (it goes into the log book, see
    ``canvod.config.models.PREPROCESSING_ATTR``), so stored data have the
    signature of data without preprocessing, and checks and sets the time
    encoding (:func:`~canvod.store.time_encoding.prepare_times`). Call it
    right before every write into a store group.

    Parameters
    ----------
    ds : xr.Dataset
        Data to write.
    store
        Zarr store of the session (or fork) that writes.
    group : str
        Store group to write into.
    append_dim : str | None
        The dimension the write appends along (``append_dim=`` of the write),
        or ``None`` for a write that creates, replaces or fills a region of
        the group. An append is checked with :func:`check_append_variables`.
    """
    if append_dim is not None:
        check_append_variables(ds, store, group, append_dim)
    attrs, _ = split_preprocessing(ds.attrs)
    ds = ds.copy(deep=False)
    ds.attrs = attrs
    return prepare_times(ds, store, group)


def check_append_variables(
    ds: xr.Dataset, store: Any, group: str, append_dim: str
) -> None:
    """Refuse an append whose variables along ``append_dim`` differ from the group's.

    A group that does not exist yet is not checked (the append creates it).

    Raises
    ------
    GroupVariablesMismatchError
        If ``ds`` lacks a variable of the group along ``append_dim``, or has
        one the group lacks.
    """
    try:
        zgroup = zarr.open_group(store, mode="r", path=group)
    except FileNotFoundError, zarr.errors.GroupNotFoundError:
        return
    stored = {
        name
        for name, array in zgroup.arrays()
        if name != append_dim and append_dim in _dimension_names(array)
    }
    if not stored:
        return
    new = {
        str(name)
        for name, var in ds.variables.items()
        if name != append_dim and append_dim in var.dims
    }
    missing = sorted(stored - new)
    extra = sorted(new - stored)
    if missing or extra:
        parts = []
        if missing:
            parts.append(f"lack {missing}, which the group has")
        if extra:
            parts.append(f"have {extra}, which the group lacks")
        msg = (
            f"Cannot append to group '{group}': the new data "
            + " and ".join(parts)
            + f" along '{append_dim}'. The variable would no longer be as long "
            "as the others, and the group could no longer be opened. Restore "
            "the settings the group was written with (e.g. "
            "processing.preprocessing.grid_assignment), or write to a new store."
        )
        raise GroupVariablesMismatchError(msg)


def _dimension_names(array: zarr.Array) -> tuple[str, ...]:
    """Dimension names of a Zarr v3 array, or of a v2 array written by xarray."""
    metadata = array.metadata
    if metadata.zarr_format == 3:
        return tuple(str(d) for d in metadata.dimension_names or ())
    names = array.attrs.get("_ARRAY_DIMENSIONS", [])
    return tuple(str(d) for d in names) if isinstance(names, list) else ()
