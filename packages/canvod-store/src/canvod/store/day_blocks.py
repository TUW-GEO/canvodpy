"""Day blocks: the layout of a group's epoch axis (ADR 0016).

A group's epoch axis is a sequence of day blocks, one per day, each holding
every slot of the day at the day's cadence. Blocks are added at the end of
the axis in the order the days are first written; a day is found by its
epoch coordinate. An epoch goes to the nearest slot (00:00 plus a multiple
of the cadence). The coordinate holds the real time of the epoch where there
are data and the grid time in empty slots, so it never has missing values.
Variables hold their missing value in empty slots: NaN for floating-point
variables, the declared ``_FillValue`` for integer ones.

The functions take an Icechunk session (or fork) for writes and its Zarr
store for reads; the caller commits.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np
import xarray as xr
import zarr
import zarr.errors
from canvod.readers.gnss_specs.metadata import INTEGER_FILL_VALUE
from canvod.store_metadata.layout import (
    DAY_BLOCKS,
    EPOCH_LAYOUT_ATTR,
    LayoutError,
    is_day_block_group,
)
from icechunk.xarray import to_icechunk
from zarr.core.metadata import ArrayV3Metadata

from canvod.store.prepare import (
    check_append_coordinates,
    check_append_variables,
    prepare_write,
)
from canvod.store.time_encoding import TIME_UNITS, with_time_units

_DAY_NS = 86_400 * 10**9
#: Setting that sets the cadence of aggregated data, named in errors.
AGGREGATION_SETTING = "processing.preprocessing.temporal_aggregation.freq"


class CadenceError(Exception):
    """A cadence a day block cannot have.

    Deliberately not a ``ValueError``: a run stops on it instead of skipping
    the file; the cadence comes from the settings or the files' names, so
    every later file of the day would be refused the same way.
    """


class SlotCollisionError(ValueError):
    """Two epochs of one file fall into one slot (ADR 0004: never drop data)."""


class ChunkOwnershipError(ValueError):
    """A write into a fork would touch an epoch chunk its task does not own.

    Icechunk merges forks chunk by chunk: of two forks that wrote one chunk,
    the one merged last replaces the other's chunk whole, so the data the
    other wrote there are lost without an error. Each task therefore owns
    the chunks its files' names give (:func:`span_chunks`), and a file whose
    epochs reach beyond them is refused.
    """


@dataclass(frozen=True)
class DayBlock:
    """One day's block: positions ``start:stop`` of the group's epoch axis."""

    day: np.datetime64
    start: int
    stop: int
    cadence_ns: int

    @property
    def cadence_s(self) -> float:
        """The block's cadence in seconds."""
        return self.cadence_ns / 1e9

    @property
    def slots(self) -> int:
        """Number of slots in the block."""
        return self.stop - self.start


@dataclass(frozen=True)
class FileRegion:
    """What :func:`write_file_region` stored of one file."""

    epochs: int
    start: np.datetime64
    end: np.datetime64


def cadence_ns(cadence_s: float, epoch_chunk: int) -> int:
    """Check a day block's cadence and return it in nanoseconds.

    A day must hold a whole number of slots and of epoch chunks, so the
    cadence must divide ``86400 / epoch_chunk`` seconds (480 s for chunks of
    180 epochs: 1 s, 5 s, 15 s, 30 s or 1 min, for example).

    Raises
    ------
    CadenceError
        If the cadence does not divide the length of one chunk.
    """
    step = round(cadence_s * 1e9)
    chunk_ns = _DAY_NS // epoch_chunk
    if step <= 0 or _DAY_NS % epoch_chunk or chunk_ns % step:
        msg = (
            f"A cadence of {cadence_s:g} s does not fit the store: each day "
            f"must hold whole chunks of {epoch_chunk} epochs, so the cadence "
            f"must divide {chunk_ns / 1e9:g} s (e.g. 1 s, 5 s, 15 s, 30 s or "
            f"1 min). Set {AGGREGATION_SETTING} to such a cadence to store "
            "these data."
        )
        raise CadenceError(msg)
    return step


def _open_group(store: Any, group: str) -> zarr.Group | None:
    try:
        return zarr.open_group(store, mode="r", path=group)
    except FileNotFoundError, zarr.errors.GroupNotFoundError:
        return None


def holds_day_blocks(store: Any, group: str) -> bool:
    """Whether ``group`` exists and is made of day blocks."""
    zgroup = _open_group(store, group)
    return zgroup is not None and is_day_block_group(zgroup.attrs)


def _require_day_blocks(zgroup: zarr.Group, group: str) -> None:
    if not is_day_block_group(zgroup.attrs):
        msg = (
            f"Group '{group}' was written by appending files to its epoch "
            "axis, not as day blocks, so it cannot take day-block writes."
        )
        raise LayoutError(msg)


def _epoch_array(zgroup: zarr.Group, group: str) -> zarr.Array:
    """The group's epoch coordinate array, stored in ``TIME_UNITS``."""
    epoch = zgroup["epoch"]
    if not isinstance(epoch, zarr.Array) or epoch.attrs.get("units") != TIME_UNITS:
        msg = f"Group '{group}' does not store its epochs in '{TIME_UNITS}'."
        raise LayoutError(msg)
    return epoch


def stored_epoch_chunk(store: Any, group: str) -> int:
    """The epochs per chunk of ``group``, as it was created.

    A group keeps the chunks it was created with; the settings may say
    otherwise by now, so whatever numbers chunks of an existing group
    takes them from here.

    Raises
    ------
    LayoutError
        If the group does not exist or does not store its epochs in
        ``TIME_UNITS``.
    """
    zgroup = _open_group(store, group)
    if zgroup is None:
        msg = f"Group '{group}' does not exist, so it has no epoch chunks."
        raise LayoutError(msg)
    return int(_epoch_array(zgroup, group).chunks[0])


def _epochs_ns(zgroup: zarr.Group, group: str) -> np.ndarray:
    """The group's epoch coordinate as nanoseconds since 1970."""
    return np.asarray(_epoch_array(zgroup, group)[...], dtype=np.int64)


def day_blocks(store: Any, group: str) -> dict[np.datetime64, DayBlock]:
    """The day blocks of ``group``, by day; empty if the group does not exist.

    Raises
    ------
    LayoutError
        If the group is not made of day blocks, or its epoch axis is not a
        sequence of whole days.
    """
    zgroup = _open_group(store, group)
    if zgroup is None:
        return {}
    _require_day_blocks(zgroup, group)
    epochs = _epochs_ns(zgroup, group)
    if epochs.size == 0:
        return {}
    days = epochs // _DAY_NS
    edges = np.flatnonzero(np.diff(days)) + 1
    starts = np.r_[0, edges]
    stops = np.r_[edges, days.size]
    blocks: dict[np.datetime64, DayBlock] = {}
    for start, stop in zip(starts.tolist(), stops.tolist(), strict=True):
        day = np.datetime64(int(days[start]), "D")
        length = stop - start
        if day in blocks or _DAY_NS % length:
            problem = "appears twice" if day in blocks else "is not a whole day"
            msg = (
                f"The epoch axis of group '{group}' is not a sequence of day "
                f"blocks: {day} {problem}."
            )
            raise LayoutError(msg)
        blocks[day] = DayBlock(day, start, stop, _DAY_NS // length)
    return blocks


def fill_value(var: xr.Variable | xr.DataArray, name: str) -> Any:
    """The missing value of a variable: declared, NaN, or the integer one.

    Raises
    ------
    ValueError
        If the variable is neither floating-point nor a signed integer and
        declares no ``_FillValue``.
    """
    declared = var.encoding.get("_FillValue", var.attrs.get("_FillValue"))
    if declared is not None:
        return declared
    if np.issubdtype(var.dtype, np.floating):
        return np.nan
    if np.issubdtype(var.dtype, np.signedinteger):
        return INTEGER_FILL_VALUE
    msg = (
        f"Variable '{name}' ({var.dtype}) declares no _FillValue, so empty "
        "slots would have no missing value."
    )
    raise ValueError(msg)


def _create_group(
    session: Any, group: str, template: xr.Dataset, epoch_chunk: int
) -> None:
    """Create ``group`` with the variables of ``template`` and no epochs."""
    empty = template.isel(epoch=slice(0, 0)).copy()
    empty.attrs = {**empty.attrs, EPOCH_LAYOUT_ATTR: DAY_BLOCKS}
    encoding: dict[str, dict[str, Any]] = {}
    for name, var in empty.variables.items():
        if not var.dims:
            continue
        chunks = tuple(
            epoch_chunk if dim == "epoch" else empty.sizes[dim] for dim in var.dims
        )
        encoding[str(name)] = {"chunks": chunks}
        if "epoch" in var.dims and name != "epoch":
            fill = fill_value(var, str(name))
            var.attrs.pop("_FillValue", None)
            encoding[str(name)].update({"_FillValue": fill, "fill_value": fill})
    empty = prepare_write(empty, session.store, group, append_dim=None)
    to_icechunk(
        empty,
        session,
        group=group,
        mode="w",
        encoding=with_time_units(empty, encoding),
    )


def add_day_block(
    session: Any,
    group: str,
    day: np.datetime64,
    cadence_s: float,
    template: xr.Dataset | None,
    epoch_chunk: int = 180,
) -> DayBlock:
    """Give ``day`` a block in ``group``, or return the block it has.

    Creates the group from the variables and labels of ``template`` (a file
    of the day) if it does not exist yet, with chunks of ``epoch_chunk``
    epochs; without a template the group must exist. An existing group
    keeps the chunks it was created with (:func:`stored_epoch_chunk`), and
    the cadence must fit those. A new block is added at the end of
    the epoch axis; its slots hold their grid times and missing values. A day
    that has a block keeps it, so files written again land in the same
    slots, and a block grown for a day that failed later is reused.

    Raises
    ------
    CadenceError
        If the cadence does not fit the chunks (see :func:`cadence_ns`), or
        the day has a block at a coarser cadence: its slots cannot take the
        new epochs.
    LayoutError
        If ``group`` exists but is not made of day blocks, or does not exist
        and no ``template`` is given.
    """
    day = np.datetime64(day, "D")
    existing = _open_group(session.store, group)
    if existing is not None:
        _require_day_blocks(existing, group)
        epoch_chunk = int(_epoch_array(existing, group).chunks[0])
    step = cadence_ns(cadence_s, epoch_chunk)
    if existing is None:
        if template is None:
            msg = (
                f"Group '{group}' does not exist yet, so {day} cannot get a "
                "block without a file to take the group's variables from; "
                "the group's first write creates it."
            )
            raise LayoutError(msg)
        _create_group(session, group, template, epoch_chunk)
    blocks = day_blocks(session.store, group)
    if day in blocks:
        block = blocks[day]
        if step < block.cadence_ns:
            msg = (
                f"{day} is stored in group '{group}' at a cadence of "
                f"{block.cadence_s:g} s; the new data are sampled every "
                f"{cadence_s:g} s, more often than its slots allow. A day keeps "
                "the cadence of its first write: process all of a day's files "
                "together, or write the day to a new store."
            )
            raise CadenceError(msg)
        return block

    zgroup = zarr.open_group(session.store, mode="r+", path=group)
    slots = _DAY_NS // step
    start = int(_epoch_array(zgroup, group).shape[0])
    for _, array in zgroup.arrays():
        dims = _dimension_names(array)
        if "epoch" not in dims:
            continue
        axis = dims.index("epoch")
        shape = list(array.shape)
        shape[axis] += slots
        array.resize(tuple(shape))
    day_ns = int(day.astype("M8[ns]").astype(np.int64))
    # A fresh handle: the one from before the resize has the old shape.
    _epoch_array(zgroup, group)[start : start + slots] = (
        day_ns + np.arange(slots) * step
    )
    return DayBlock(day, start, start + slots, step)


def _dimension_names(array: zarr.Array) -> tuple[str, ...]:
    if not isinstance(array.metadata, ArrayV3Metadata):
        msg = f"Array '{array.path}' is not a zarr v3 array; it has no dimension names."
        raise LayoutError(msg)
    return tuple(str(d) for d in array.metadata.dimension_names or ())


def _slots(offsets: np.ndarray, block: DayBlock) -> np.ndarray:
    """Nearest slot of each epoch, ``offsets`` in ns from the day's 00:00."""
    slots = (offsets + block.cadence_ns // 2) // block.cadence_ns
    return np.minimum(slots, block.slots - 1)


def span_chunks(
    block: DayBlock, start: np.datetime64, last: np.datetime64, epoch_chunk: int
) -> set[int]:
    """The epoch chunks of the slots from ``start`` to ``last`` in ``block``.

    Chunks are numbered along the group's whole epoch axis. ``start`` and
    ``last`` are the first and last epoch of a file, e.g. from its name, and
    go to their nearest slots as epochs do (:func:`write_file_region`).
    """
    day_ns = int(block.day.astype("M8[ns]").astype(np.int64))
    offsets = np.array(
        [
            int(np.datetime64(start, "ns").astype(np.int64)) - day_ns,
            int(np.datetime64(last, "ns").astype(np.int64)) - day_ns,
        ]
    )
    first, final = (block.start + _slots(offsets, block)).tolist()
    return set(range(first // epoch_chunk, final // epoch_chunk + 1))


def write_file_region(
    session: Any,
    group: str,
    ds: xr.Dataset,
    *,
    blocks: Mapping[np.datetime64, DayBlock] | None = None,
    chunks: Collection[int] | None = None,
) -> FileRegion:
    """Write a file's epochs into the blocks of their days.

    Each epoch goes to its nearest slot; the slots between the file's first
    and last epoch that it has no epoch for are written as empty (missing
    values, grid times), so writing a file again replaces what it wrote
    before. Every day of the file needs a block (:func:`add_day_block`).

    Parameters
    ----------
    blocks
        The group's day blocks (:func:`day_blocks`), when the caller has
        them: reading them reads the group's whole epoch axis.
    chunks
        The epoch chunks the write may touch, numbered along the group's
        epoch axis; ``None`` allows all. A write into a fork passes the
        chunks its task owns (see :class:`ChunkOwnershipError`).

    Raises
    ------
    SlotCollisionError
        If two epochs of the file fall into one slot; nothing is written.
    ChunkOwnershipError
        If the file's slots reach beyond ``chunks``; nothing is written.
    LayoutError
        If a day of the file has no block, or the group is not made of day
        blocks.
    GroupVariablesMismatchError, GroupCoordinatesMismatchError
        If the file's variables or labels differ from the group's (see
        :func:`~canvod.store.prepare.prepare_write`).
    """
    if blocks is None:
        blocks = day_blocks(session.store, group)
    # The checks of an append (same variables, same labels), without the
    # refusal of appends to day blocks that prepare_write makes.
    check_append_variables(ds, session.store, group, "epoch")
    check_append_coordinates(ds, session.store, group, "epoch")
    ds = prepare_write(ds, session.store, group, append_dim=None)
    epochs = ds["epoch"].values.astype("M8[ns]").astype(np.int64)
    days = epochs // _DAY_NS

    regions = []
    for day_number in np.unique(days):
        day = np.datetime64(int(day_number), "D")
        if day not in blocks:
            msg = f"{day} has no block in group '{group}'; add it first."
            raise LayoutError(msg)
        block = blocks[day]
        idx = np.flatnonzero(days == day_number)
        slots = _slots(epochs[idx] - day_number * _DAY_NS, block)
        order = np.argsort(slots, kind="stable")
        clash = np.flatnonzero(np.diff(slots[order]) == 0)
        if clash.size:
            a, b = idx[order[clash[0]]], idx[order[clash[0] + 1]]
            msg = (
                f"Two epochs of the file fall into one slot of the "
                f"{block.cadence_s:g} s cadence of {day} in group '{group}': "
                f"{np.datetime64(int(epochs[a]), 'ns')} and "
                f"{np.datetime64(int(epochs[b]), 'ns')}. A slot holds one epoch, "
                "so one of them would be lost; the file was not written."
            )
            raise SlotCollisionError(msg)
        regions.append((block, idx, slots))

    if chunks is not None:
        _check_chunks(session, group, regions, chunks)

    for block, idx, slots in regions:
        _write_region(session, group, ds, block, idx, slots)

    return FileRegion(
        epochs=int(epochs.size),
        start=np.datetime64(int(epochs.min()), "ns"),
        end=np.datetime64(int(epochs.max()), "ns"),
    )


def _check_chunks(
    session: Any,
    group: str,
    regions: list[tuple[DayBlock, np.ndarray, np.ndarray]],
    chunks: Collection[int],
) -> None:
    """Refuse regions that reach beyond the epoch chunks a fork may write."""
    epoch_chunk = stored_epoch_chunk(session.store, group)
    allowed = set(chunks)
    for block, _, slots in regions:
        # A region covers every slot from the file's first to its last one.
        positions = block.start + np.array([slots.min(), slots.max()])
        touched = set(
            range(
                int(positions[0]) // epoch_chunk, int(positions[1]) // epoch_chunk + 1
            )
        )
        outside = sorted(touched - allowed)
        if outside:
            msg = (
                f"The file's epochs on {block.day} reach epoch chunks "
                f"{outside} of group '{group}', beyond the chunks "
                f"{sorted(allowed)} its name gives, which another task may be "
                "writing; the file was not written. Its epochs disagree with "
                "the period in its name."
            )
            raise ChunkOwnershipError(msg)


def _write_region(
    session: Any,
    group: str,
    ds: xr.Dataset,
    block: DayBlock,
    idx: np.ndarray,
    slots: np.ndarray,
) -> None:
    """Write epochs ``idx`` of ``ds`` into ``slots`` of ``block``."""
    first, last = int(slots.min()), int(slots.max()) + 1
    at = slots - first
    day_ns = int(block.day.astype("M8[ns]").astype(np.int64))
    times = day_ns + np.arange(first, last) * block.cadence_ns
    times[at] = ds["epoch"].values.astype("M8[ns]").astype(np.int64)[idx]

    region_vars: dict[str, xr.Variable] = {}
    for name, var in ds.variables.items():
        if name == "epoch" or "epoch" not in var.dims:
            continue
        var = var.transpose("epoch", ...)
        values = np.full(
            (last - first, *var.shape[1:]), fill_value(var, str(name)), var.dtype
        )
        values[at] = np.asarray(var.values)[idx]
        region_vars[str(name)] = xr.Variable(var.dims, values, var.attrs)
    epoch = xr.Variable(
        "epoch", times.astype("M8[ns]"), ds["epoch"].attrs, encoding=ds.epoch.encoding
    )
    region = xr.Dataset(
        {n: v for n, v in region_vars.items() if n in ds.data_vars},
        coords={
            "epoch": epoch,
            **{n: v for n, v in region_vars.items() if n not in ds.data_vars},
        },
    )
    for var in region.variables.values():
        var.attrs.pop("_FillValue", None)
    where = slice(block.start + first, block.start + last)
    to_icechunk(region, session, group=group, region={"epoch": where})
    # The write leaves the stored index coordinate as it was; set the real
    # times (the group stores them in TIME_UNITS, see _epochs_ns).
    zgroup = zarr.open_group(session.store, mode="r+", path=group)
    _epoch_array(zgroup, group)[where] = times


def load_group(
    store: Any,
    group: str,
    *,
    drop_empty: bool = False,
    chunks: dict[str, Any] | None = None,
) -> xr.Dataset:
    """Open a group with its epochs in time order.

    Integer variables keep their dtype: their empty slots hold their
    ``_FillValue`` (kept in ``encoding``), not NaN. The layout attribute
    stays in the store: data read from a group and written elsewhere must
    not claim a layout.

    Parameters
    ----------
    store
        Zarr store of a session.
    group : str
        Group to open.
    drop_empty : bool, default False
        Drop the empty slots of a day-block group (:func:`drop_empty_slots`);
        a group written by appending has none. This reads the data of the
        whole group; to read part of it, select first and drop the empty
        slots of the selection.
    chunks : dict, optional
        Dask chunks; the stored chunks if ``None``.
    """
    ds = xr.open_zarr(
        store,
        group=group,
        chunks={} if chunks is None else chunks,
        consolidated=False,
    )
    day_blocked = is_day_block_group(ds.attrs)
    ds.attrs.pop(EPOCH_LAYOUT_ATTR, None)
    for name in list(ds.variables):
        var = ds[name]
        dtype = var.encoding.get("dtype")
        if (
            dtype is not None
            and np.issubdtype(np.dtype(dtype), np.integer)
            and var.dtype.kind == "f"
            and "_FillValue" in var.encoding
        ):
            # Masking turned the integers into floats with NaN; undo it.
            restored = var.fillna(var.encoding["_FillValue"]).astype(dtype)
            restored.encoding = var.encoding
            ds[name] = restored
    if not ds.indexes["epoch"].is_monotonic_increasing:
        ds = ds.sortby("epoch")
    if drop_empty and day_blocked:
        ds = drop_empty_slots(ds, group)
    return ds


def drop_empty_slots(ds: xr.Dataset, group: str) -> xr.Dataset:
    """``ds`` without its empty slots.

    A slot is empty when every floating-point data variable along ``epoch``
    is missing in it (integer variables hold their fill value there, which
    a stored flag may also have).

    Raises
    ------
    ValueError
        If ``ds`` has no floating-point data variable along ``epoch``.
    """
    floats = [
        var
        for var in ds.data_vars.values()
        if "epoch" in var.dims and np.issubdtype(var.dtype, np.floating)
    ]
    if not floats:
        msg = (
            f"Group '{group}' has no floating-point variable along epoch to "
            "tell empty slots by."
        )
        raise ValueError(msg)
    has_data = None
    for var in floats:
        other = [d for d in var.dims if d != "epoch"]
        present = var.notnull().any(dim=other) if other else var.notnull()
        has_data = present if has_data is None else has_data | present
    return ds.isel(epoch=np.flatnonzero(np.asarray(has_data)))
