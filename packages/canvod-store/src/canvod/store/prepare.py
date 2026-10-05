"""The last step before every write of a dataset into a store group."""

from __future__ import annotations

from typing import Any

import numpy as np
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


class GroupCoordinatesMismatchError(Exception):
    """An append does not carry the same labels as the store group.

    The labels of every dimension but the append dimension (e.g. ``sid``)
    are stored once for the whole group. An append with other labels of the
    same length would overwrite them for the data already in the group.
    Usually a setting changed between runs (e.g.
    ``processing.params.aggregate_glonass_fdma``, which renames the GLONASS
    sids, or the sid selection).

    Deliberately not a ``ValueError``, like
    :class:`GroupVariablesMismatchError`.
    """


class EpochTimeSystemError(Exception):
    """Epochs that are not GPS time, or a group not known to be GPS time.

    Every stored epoch is GPS time (``epoch.attrs["time_system"] == "GPS"``),
    the time scale of the orbits and clocks. Groups written before canVODpy
    recorded the time scale do not say theirs: SBF and NMEA epochs were UTC
    then, 18 s off GPS time, so appending GPS-time epochs would mix scales.

    Deliberately not a ``ValueError``, like
    :class:`GroupVariablesMismatchError`.
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
        the group. An append is checked with :func:`check_append_variables`
        and :func:`check_append_coordinates`.

    Raises
    ------
    EpochTimeSystemError
        See :func:`check_epoch_time_system`.
    """
    check_epoch_time_system(ds, store, group)
    if append_dim is not None:
        check_append_variables(ds, store, group, append_dim)
        check_append_coordinates(ds, store, group, append_dim)
    attrs, _ = split_preprocessing(ds.attrs)
    ds = ds.copy(deep=False)
    ds.attrs = attrs
    return prepare_times(ds, store, group)


def check_epoch_time_system(ds: xr.Dataset, store: Any, group: str) -> None:
    """Refuse epochs that are not GPS time, or a group not in GPS time.

    Data without an ``epoch`` coordinate are not checked. A group that does
    not exist yet, or has no ``epoch`` array, is only checked through ``ds``.

    Raises
    ------
    EpochTimeSystemError
        If the ``epoch`` coordinate of ``ds`` is not GPS time, or if the
        group's ``epoch`` is not, or does not record its time scale.
    """
    if "epoch" not in ds.coords:
        return
    new = ds["epoch"].attrs.get("time_system")
    if new != "GPS":
        msg = (
            f"Cannot write to group '{group}': the epochs are in time system "
            f"{new!r}, but every stored epoch is GPS time ('GPS', recorded in "
            "epoch.attrs['time_system'] by the readers)."
        )
        raise EpochTimeSystemError(msg)
    try:
        zgroup = zarr.open_group(store, mode="r", path=group)
    except FileNotFoundError, zarr.errors.GroupNotFoundError:
        return
    if "epoch" not in set(zgroup.array_keys()):
        return
    stored = zgroup["epoch"].attrs.get("time_system")
    if stored != "GPS":
        said = (
            "does not record its time scale: it was written before canVODpy "
            "stored every epoch in GPS time, when SBF and NMEA epochs were UTC"
            if stored is None
            else f"is in time system {stored!r}"
        )
        msg = (
            f"Cannot write to group '{group}': its epochs {said}. The new "
            "epochs are GPS time, and one group cannot mix time scales. "
            "Write to a new store, or rebuild this one from the raw files."
        )
        raise EpochTimeSystemError(msg)


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


def check_append_coordinates(
    ds: xr.Dataset, store: Any, group: str, append_dim: str
) -> None:
    """Refuse an append whose labels differ from the group's.

    Compares the coordinate of every dimension of ``ds`` but ``append_dim``
    (e.g. ``sid``) with the one stored in the group, label by label and in
    order. A group that does not exist yet, or a dimension the group has no
    coordinate for, is not checked.

    Raises
    ------
    GroupCoordinatesMismatchError
        If a coordinate of ``ds`` has other labels, or another order, than
        the group's.
    """
    try:
        zgroup = zarr.open_group(store, mode="r", path=group)
    except FileNotFoundError, zarr.errors.GroupNotFoundError:
        return
    stored_names = set(zgroup.array_keys())
    for dim in ds.dims:
        if dim == append_dim or dim not in ds.coords or dim not in stored_names:
            continue
        array = zgroup[str(dim)]
        if not isinstance(array, zarr.Array):
            continue
        stored = [str(v) for v in np.asarray(array[...])]
        new = [str(v) for v in ds[dim].values]
        if stored == new:
            continue
        if len(stored) != len(new):
            what = f"{len(new)} labels, the group has {len(stored)}"
        else:
            differing = [(a, b) for a, b in zip(stored, new, strict=True) if a != b]
            examples = ", ".join(f"{a!r} -> {b!r}" for a, b in differing[:3])
            what = (
                f"other labels than the group's at {len(differing)} of "
                f"{len(stored)} positions (e.g. {examples})"
            )
        msg = (
            f"Cannot append to group '{group}': the new '{dim}' coordinate "
            f"has {what}. The labels are stored once for the whole group, so "
            "the append would relabel the data already in it. Restore the "
            "settings the group was written with (e.g. "
            "processing.params.aggregate_glonass_fdma or the sid selection), "
            "or write to a new store."
        )
        raise GroupCoordinatesMismatchError(msg)


def _dimension_names(array: zarr.Array) -> tuple[str, ...]:
    """Dimension names of a Zarr v3 array, or of a v2 array written by xarray."""
    metadata = array.metadata
    if metadata.zarr_format == 3:
        return tuple(str(d) for d in metadata.dimension_names or ())
    names = array.attrs.get("_ARRAY_DIMENSIONS", [])
    return tuple(str(d) for d in names) if isinstance(names, list) else ()
