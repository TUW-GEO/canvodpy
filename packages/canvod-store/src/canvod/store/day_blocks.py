"""Day blocks: the layout of a group's epoch axis (ADR 0016).

A group's epoch axis is a sequence of day blocks, one per day, each holding
every slot of the day at the day's cadence: ``ceil(86400 s / cadence)``
slots, 00:00 plus a multiple of the cadence. Each block is padded to a whole
number of epoch chunks, so days never share a chunk and every cadence fits;
the cadence may change from one day to the next. Blocks are added at the end
of the axis in the order the days are first written. The group's block index
(:data:`~canvod.store_metadata.layout.DAY_BLOCK_INDEX_ATTR`) gives each
day's block. An epoch goes to the nearest slot. The coordinate holds the
real time of the epoch where there are data and the grid time in empty
slots; padding slots hold the last nanoseconds before the next day, so the
coordinate never has missing values and keeps rising within the block.
Variables hold their missing value in empty and padding slots: NaN for
floating-point variables, the declared ``_FillValue`` for integer ones.
Loading drops the padding.

The functions take an Icechunk session (or fork) for writes and its Zarr
store for reads; the caller commits.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
import xarray as xr
import zarr
import zarr.errors
from canvod.readers.gnss_specs.metadata import INTEGER_FILL_VALUE
from canvod.store_metadata import RESERVED_GROUP
from canvod.store_metadata.layout import (
    DAY_BLOCK_INDEX_ATTR,
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
#: Command that moves a store written by appending to day blocks.
MIGRATE_LAYOUT_COMMAND = "canvodpy store migrate-layout SITE --store gnss|vod"
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
    """One day's block: positions ``start:stop`` of the group's epoch axis.

    The first ``slots`` positions are the day's slots; the rest, up to
    ``stop``, pad the block to whole epoch chunks.
    """

    day: np.datetime64
    start: int
    stop: int
    cadence_ns: int
    slots: int

    @property
    def cadence_s(self) -> float:
        """The block's cadence in seconds."""
        return self.cadence_ns / 1e9


@dataclass(frozen=True)
class FileRegion:
    """What :func:`write_file_region` stored of one file."""

    epochs: int
    start: np.datetime64
    end: np.datetime64


def cadence_ns(cadence_s: float) -> int:
    """Check a day block's cadence and return it in nanoseconds.

    Any cadence from 1 ns to one day fits: a day holds
    ``ceil(86400 s / cadence)`` slots, padded to whole epoch chunks.

    Raises
    ------
    CadenceError
        If the cadence is not positive or longer than a day.
    """
    step = round(cadence_s * 1e9)
    if step <= 0 or step > _DAY_NS:
        msg = (
            f"A cadence of {cadence_s:g} s cannot be stored: a day block "
            "needs a cadence longer than 0 s and no longer than one day."
        )
        raise CadenceError(msg)
    return step


def day_slots(step: int) -> int:
    """The number of slots of a day at a cadence of ``step`` ns."""
    return -(-_DAY_NS // step)


def _padded(slots: int, epoch_chunk: int) -> int:
    """``slots`` rounded up to whole chunks of ``epoch_chunk`` epochs."""
    return -(-slots // epoch_chunk) * epoch_chunk


def _block_times(block: DayBlock) -> np.ndarray:
    """The grid times of ``block``, padding included, in ns since 1970.

    Slot ``k`` is 00:00 plus ``k`` cadences; the padding slots are the last
    nanoseconds before the next day. The last slot can hold a real time
    after its grid time (an epoch near midnight goes to it), so padding
    right after the grid time could come before that real time.
    """
    day_ns = int(block.day.astype("M8[ns]").astype(np.int64))
    grid = day_ns + np.arange(block.slots, dtype=np.int64) * block.cadence_ns
    pad = block.stop - block.start - block.slots
    if not pad:
        return grid
    padding = day_ns + _DAY_NS - pad + np.arange(pad, dtype=np.int64)
    return np.concatenate([grid, padding])


def _open_group(store: Any, group: str) -> zarr.Group | None:
    try:
        return zarr.open_group(store, mode="r", path=group)
    except FileNotFoundError, zarr.errors.GroupNotFoundError:
        return None


def data_groups(store: Any) -> list[str]:
    """The groups of the store that hold epochs, at any depth.

    A VOD group sits below its calculator (``tau_omega/...``). The groups
    inside a data group (its ``metadata/``) are not data groups.
    """
    try:
        root = zarr.open_group(store, mode="r")
    except FileNotFoundError, zarr.errors.GroupNotFoundError:
        return []
    found: list[str] = []
    below = [(name, group) for name, group in root.groups() if name != RESERVED_GROUP]
    while below:
        path, group = below.pop()
        if "epoch" in set(group.array_keys()):
            found.append(path)
        else:
            below.extend((f"{path}/{name}", sub) for name, sub in group.groups())
    return sorted(found)


def holds_day_blocks(store: Any, group: str) -> bool:
    """Whether ``group`` exists and is made of day blocks."""
    zgroup = _open_group(store, group)
    return zgroup is not None and is_day_block_group(zgroup.attrs)


def _require_day_blocks(zgroup: zarr.Group, group: str) -> None:
    if not is_day_block_group(zgroup.attrs):
        msg = (
            f"Group '{group}' was written by appending files to its epoch "
            "axis, not as day blocks, so it cannot take day-block writes. "
            f"Move the store to day blocks first:\n  {MIGRATE_LAYOUT_COMMAND}"
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


def _index(zgroup: zarr.Group, group: str) -> dict[str, dict[str, int]]:
    """The block index of a day-block group (``DAY_BLOCK_INDEX_ATTR``)."""
    index = zgroup.attrs.get(DAY_BLOCK_INDEX_ATTR)
    if not isinstance(index, Mapping):
        msg = (
            f"Group '{group}' is made of day blocks but has no block index "
            f"('{DAY_BLOCK_INDEX_ATTR}' attribute). It was written by a "
            "development version of canVODpy; give it its block index "
            f"with:\n  {MIGRATE_LAYOUT_COMMAND}"
        )
        raise LayoutError(msg)
    out: dict[str, dict[str, int]] = {}
    for day, entry in index.items():
        fields = dict(entry) if isinstance(entry, Mapping) else {}
        if set(fields) != {"start", "stop", "slots", "cadence_ns"} or not all(
            isinstance(value, int) for value in fields.values()
        ):
            msg = f"The block index of group '{group}' is damaged at {day}."
            raise LayoutError(msg)
        out[str(day)] = {
            str(key): value for key, value in fields.items() if isinstance(value, int)
        }
    return out


def _blocks_from_index(
    index: Mapping[str, Mapping[str, int]], length: int, group: str
) -> dict[np.datetime64, DayBlock]:
    """The blocks of a block index, checked against the epoch axis length.

    Raises
    ------
    LayoutError
        If the blocks do not tile the epoch axis, or a block's slots do not
        fit it.
    """
    blocks = {
        np.datetime64(day, "D"): DayBlock(
            np.datetime64(day, "D"),
            int(entry["start"]),
            int(entry["stop"]),
            int(entry["cadence_ns"]),
            int(entry["slots"]),
        )
        for day, entry in index.items()
    }
    position = 0
    for block in sorted(blocks.values(), key=lambda b: b.start):
        if (
            block.start != position
            or block.cadence_ns <= 0
            or block.slots != day_slots(block.cadence_ns)
            or not block.slots <= block.stop - block.start
        ):
            msg = (
                f"The block index of group '{group}' does not fit its epoch "
                f"axis at {block.day}."
            )
            raise LayoutError(msg)
        position = block.stop
    if position != length:
        msg = (
            f"The block index of group '{group}' covers {position} epochs; "
            f"its epoch axis has {length}."
        )
        raise LayoutError(msg)
    return blocks


def day_blocks(store: Any, group: str) -> dict[np.datetime64, DayBlock]:
    """The day blocks of ``group``, by day; empty if the group does not exist.

    Raises
    ------
    LayoutError
        If the group is not made of day blocks, or its block index does not
        fit its epoch axis.
    """
    zgroup = _open_group(store, group)
    if zgroup is None:
        return {}
    _require_day_blocks(zgroup, group)
    length = int(_epoch_array(zgroup, group).shape[0])
    return _blocks_from_index(_index(zgroup, group), length, group)


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


def fill_encoding(var: xr.Variable | xr.DataArray, name: str) -> dict[str, Any]:
    """Take the missing value of a variable out of its attributes, for its encoding.

    Returns the CF ``_FillValue`` and the Zarr ``fill_value``, both
    :func:`fill_value`, and removes ``_FillValue`` from ``var.attrs``.
    xarray refuses a ``_FillValue`` in both the attributes and the encoding,
    which an append to a stored array would otherwise give.
    """
    fill = fill_value(var, name)
    var.attrs.pop("_FillValue", None)
    return {"_FillValue": fill, "fill_value": fill}


def _create_group(
    session: Any,
    group: str,
    template: xr.Dataset,
    epoch_chunk: int,
    dim_chunks: Mapping[str, int] | None = None,
    *,
    keep_subgroups: bool = False,
) -> None:
    """Create ``group`` with the variables of ``template`` and no epochs.

    Dimensions other than ``epoch`` get the chunk sizes of ``dim_chunks``;
    a dimension it leaves out, or gives ``-1``, is one chunk. With
    ``keep_subgroups``, the group exists without arrays (they were
    deleted) and its subgroups, such as ``metadata/``, stay; otherwise
    the group is created anew.
    """
    empty = template.isel(epoch=slice(0, 0)).copy()
    empty.attrs = {
        **empty.attrs,
        EPOCH_LAYOUT_ATTR: DAY_BLOCKS,
        DAY_BLOCK_INDEX_ATTR: {},
    }
    sizes = {str(dim): size for dim, size in empty.sizes.items()}
    for dim, size in (dim_chunks or {}).items():
        if dim != "epoch" and dim in sizes and size != -1:
            sizes[dim] = int(size)
    encoding: dict[str, dict[str, Any]] = {}
    for name, var in empty.variables.items():
        if not var.dims:
            continue
        chunks = tuple(
            epoch_chunk if dim == "epoch" else sizes[str(dim)] for dim in var.dims
        )
        encoding[str(name)] = {"chunks": chunks}
        if "epoch" in var.dims and name != "epoch":
            encoding[str(name)].update(fill_encoding(var, str(name)))
    empty = prepare_write(empty, session.store, group, append_dim=None)
    to_icechunk(
        empty,
        session,
        group=group,
        mode="a" if keep_subgroups else "w",
        encoding=with_time_units(empty, encoding),
    )


def add_day_block(
    session: Any,
    group: str,
    day: np.datetime64,
    cadence_s: float,
    template: xr.Dataset | None,
    epoch_chunk: int = 180,
    dim_chunks: Mapping[str, int] | None = None,
) -> DayBlock:
    """Give ``day`` a block in ``group``, or return the block it has.

    Creates the group from the variables and labels of ``template`` (a file
    of the day) if it does not exist yet, with chunks of ``epoch_chunk``
    epochs and, along the other dimensions, of ``dim_chunks`` (for example
    ``{"sid": 64}``; ``-1`` or a dimension left out is one chunk); without
    a template the group must exist. An existing group
    keeps the chunks it was created with (:func:`stored_epoch_chunk`). A new
    block is added at the end of the epoch axis, padded to whole chunks; its
    slots hold their grid times and missing values. A day that has a block
    keeps it, so files written again land in the same slots, and a block
    grown for a day that failed later is reused.

    Raises
    ------
    CadenceError
        If the cadence is not positive or longer than a day (see
        :func:`cadence_ns`), or the day has a block at a coarser cadence: its
        slots cannot take the new epochs.
    LayoutError
        If ``group`` exists but is not made of day blocks, or does not exist
        and no ``template`` is given.
    """
    day = np.datetime64(day, "D")
    existing = _open_group(session.store, group)
    if existing is not None:
        _require_day_blocks(existing, group)
        epoch_chunk = int(_epoch_array(existing, group).chunks[0])
    step = cadence_ns(cadence_s)
    if existing is None:
        if template is None:
            msg = (
                f"Group '{group}' does not exist yet, so {day} cannot get a "
                "block without a file to take the group's variables from; "
                "the group's first write creates it."
            )
            raise LayoutError(msg)
        _create_group(session, group, template, epoch_chunk, dim_chunks)
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
    slots = day_slots(step)
    start = int(_epoch_array(zgroup, group).shape[0])
    block = DayBlock(day, start, start + _padded(slots, epoch_chunk), step, slots)
    for _, array in zgroup.arrays():
        dims = _dimension_names(array)
        if "epoch" not in dims:
            continue
        axis = dims.index("epoch")
        shape = list(array.shape)
        shape[axis] += block.stop - block.start
        array.resize(tuple(shape))
    # A fresh handle: the one from before the resize has the old shape.
    _epoch_array(zgroup, group)[block.start : block.stop] = _block_times(block)
    index = _index(zgroup, group)
    index[str(day)] = {
        "start": block.start,
        "stop": block.stop,
        "slots": block.slots,
        "cadence_ns": block.cadence_ns,
    }
    zgroup.attrs.update({DAY_BLOCK_INDEX_ATTR: index})
    return block


def clear_day_block(session: Any, group: str, block: DayBlock) -> None:
    """Empty every slot of ``block``: missing values at the grid times.

    A write replaces only the slots from its first to its last epoch
    (:func:`write_file_region`); a result that replaces a whole day, such
    as the VOD of the day, clears the day's block first, so nothing of an
    earlier write stays outside its span.

    Raises
    ------
    LayoutError
        If ``group`` is not made of day blocks.
    """
    zgroup = zarr.open_group(session.store, mode="r+", path=group)
    _require_day_blocks(zgroup, group)
    _clear_slots(zgroup, group, block, 0, block.slots)


def _clear_slots(
    zgroup: zarr.Group, group: str, block: DayBlock, first: int, stop: int
) -> None:
    """Empty slots ``first`` to ``stop`` (exclusive) of ``block``."""
    for name, array in zgroup.arrays():
        dims = _dimension_names(array)
        if name == "epoch" or "epoch" not in dims:
            continue
        where = [slice(None)] * len(dims)
        where[dims.index("epoch")] = slice(block.start + first, block.start + stop)
        array[tuple(where)] = array.fill_value
    day_ns = int(block.day.astype("M8[ns]").astype(np.int64))
    _epoch_array(zgroup, group)[block.start + first : block.start + stop] = (
        day_ns + np.arange(first, stop) * block.cadence_ns
    )


def _span_slots(
    blocks: Mapping[np.datetime64, DayBlock],
    start: np.datetime64,
    last: np.datetime64,
) -> list[tuple[DayBlock, int, int]]:
    """The slots from ``start`` to ``last`` (both included), block by block.

    ``start`` and ``last`` are a file's first and last epoch and go to their
    nearest slots as epochs do. Days without a block hold nothing and are
    left out.
    """
    start_ns = int(np.datetime64(start, "ns").astype(np.int64))
    last_ns = int(np.datetime64(last, "ns").astype(np.int64))
    out = []
    for day_number in range(start_ns // _DAY_NS, last_ns // _DAY_NS + 1):
        block = blocks.get(np.datetime64(day_number, "D"))
        if block is None:
            continue
        day_ns = day_number * _DAY_NS
        offsets = np.array([max(start_ns, day_ns), min(last_ns, day_ns + _DAY_NS - 1)])
        first, final = _slots(offsets - day_ns, block).tolist()
        out.append((block, first, final + 1))
    return out


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
    earlier: Sequence[tuple[np.datetime64, np.datetime64]] = (),
    keep: Sequence[tuple[np.datetime64, np.datetime64]] = (),
) -> FileRegion:
    """Write a file's epochs into the blocks of their days.

    Each epoch goes to its nearest slot; the slots between the file's first
    and last epoch that it has no epoch for are written as empty (missing
    values, grid times). Every day of the file needs a block
    (:func:`add_day_block`).

    Parameters
    ----------
    blocks
        The group's day blocks (:func:`day_blocks`), when the caller has
        them: reading them reads the group's whole epoch axis.
    chunks
        The epoch chunks the write may touch, numbered along the group's
        epoch axis; ``None`` allows all. A write into a fork passes the
        chunks its task owns (see :class:`ChunkOwnershipError`).
    earlier
        The ``(first epoch, last epoch)`` of the file's earlier writes, from
        its log-book rows: their slots outside the file's new span are
        emptied, so nothing of an earlier write stays when the file now has
        fewer epochs at its start or end. Empty for a first write: only the
        slots from the file's first to its last epoch are written.
    keep
        The ``(first epoch, last epoch)`` of other stored files: their slots
        are never emptied, also where an earlier write of this file
        reached into them.

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

    written = [
        (block, int(slots.min()), int(slots.max()) + 1) for block, _, slots in regions
    ]
    kept = [span for first, last in keep for span in _span_slots(blocks, first, last)]
    cleared = _outside(
        [span for first, last in earlier for span in _span_slots(blocks, first, last)],
        written + kept,
    )
    if chunks is not None:
        _check_chunks(session, group, regions, chunks)
        _check_chunks(
            session,
            group,
            [
                (block, None, np.array([first, stop - 1]))
                for block, first, stop in cleared
            ],
            chunks,
        )

    if cleared:
        zgroup = zarr.open_group(session.store, mode="r+", path=group)
        for block, first, stop in cleared:
            _clear_slots(zgroup, group, block, first, stop)
    for block, idx, slots in regions:
        _write_region(session, group, ds, block, idx, slots)

    return FileRegion(
        epochs=int(epochs.size),
        start=np.datetime64(int(epochs.min()), "ns"),
        end=np.datetime64(int(epochs.max()), "ns"),
    )


def _outside(
    spans: list[tuple[DayBlock, int, int]],
    holes: list[tuple[DayBlock, int, int]],
) -> list[tuple[DayBlock, int, int]]:
    """The slots of ``spans`` outside every one of ``holes``, block by block."""
    out = []
    for block, first, stop in spans:
        pieces = [(first, stop)]
        for other, low, high in holes:
            if other.day != block.day:
                continue
            pieces = [
                (a, b)
                for p_first, p_stop in pieces
                for a, b in ((p_first, min(p_stop, low)), (max(p_first, high), p_stop))
                if a < b
            ]
        out += [(block, a, b) for a, b in pieces]
    return out


def _check_chunks(
    session: Any,
    group: str,
    regions: Sequence[tuple[DayBlock, Any, np.ndarray]],
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
    # times (the group stores them in TIME_UNITS, see _epoch_array).
    zgroup = zarr.open_group(session.store, mode="r+", path=group)
    _epoch_array(zgroup, group)[where] = times


def load_group(
    store: Any,
    group: str,
    *,
    drop_empty: bool = False,
    chunks: dict[str, Any] | None = None,
    time_slice: slice | None = None,
) -> xr.Dataset:
    """Open a group with its epochs in time order.

    Integer variables keep their dtype: their empty slots hold their
    ``_FillValue`` (kept in ``encoding``), not NaN. The padding slots of a
    day-block group are dropped. The layout attributes stay in the store:
    data read from a group and written elsewhere must not claim a layout.

    Parameters
    ----------
    store
        Zarr store of a session.
    group : str
        Group to open.
    drop_empty : bool, default False
        Drop the empty slots of a day-block group (:func:`drop_empty_slots`),
        after ``time_slice``; a group written by appending has none.
    chunks : dict, optional
        Dask chunks; the stored chunks if ``None``.
    time_slice : slice, optional
        Label-based time selection, as ``ds.sel(epoch=time_slice)``. A
        day-block group then reads only the blocks of the days it reaches,
        so reading a day takes the same time however many days are stored.
    """
    ds = xr.open_zarr(
        store,
        group=group,
        chunks={} if chunks is None else chunks,
        consolidated=False,
        # The epoch index is built after selecting the blocks: building it
        # first reads every epoch of the group.
        create_default_indexes=False,
    )
    day_blocked = is_day_block_group(ds.attrs)
    if day_blocked:
        zgroup = zarr.open_group(store, mode="r", path=group)
        blocks = _blocks_from_index(_index(zgroup, group), ds.sizes["epoch"], group)
        kept = (
            list(blocks.values())
            if time_slice is None
            else _blocks_reached(blocks.values(), time_slice)
        )
        ds = ds.isel(epoch=_slot_positions(kept))
    ds = _with_default_indexes(ds)
    ds.attrs.pop(EPOCH_LAYOUT_ATTR, None)
    ds.attrs.pop(DAY_BLOCK_INDEX_ATTR, None)
    ds = restore_integers(ds)
    if not ds.indexes["epoch"].is_monotonic_increasing:
        ds = ds.sortby("epoch")
    if time_slice is not None:
        ds = ds.sel(epoch=time_slice)
    if drop_empty and day_blocked:
        ds = drop_empty_slots(ds, group)
    return ds


def _with_default_indexes(ds: xr.Dataset) -> xr.Dataset:
    """``ds`` with the index xarray builds on opening, for each dimension."""
    dims = [dim for dim in ds.dims if dim in ds.coords and dim not in ds.xindexes]
    ds = ds.assign_coords({dim: ds[dim].load() for dim in dims})
    for dim in dims:
        ds = ds.set_xindex([dim])
    return ds


def _blocks_reached(blocks: Collection[DayBlock], time_slice: slice) -> list[DayBlock]:
    """The blocks holding an epoch that ``time_slice`` can select.

    Every epoch of a block lies in its day (:func:`_slots`), so a block is
    reached when the slice reaches its day. The days' bounds are compared
    the way ``sel`` compares epochs, partial date strings included.
    """
    ordered = sorted(blocks, key=lambda b: b.day)
    one_day = np.timedelta64(1, "D")
    bounds = pd.DatetimeIndex(
        [
            bound
            for block in ordered
            for bound in (
                block.day.astype("M8[ns]"),
                (block.day + one_day).astype("M8[ns]") - np.timedelta64(1, "ns"),
            )
        ]
    )
    first, stop = bounds.slice_locs(time_slice.start, time_slice.stop)
    # Bounds first..stop-1 lie inside the selection. Day k (bounds 2k and
    # 2k+1) is reached unless it ends before the selection or starts after.
    return [
        block for k, block in enumerate(ordered) if 2 * k + 1 >= first and 2 * k < stop
    ]


def restore_integers(ds: xr.Dataset) -> xr.Dataset:
    """``ds`` with its integer variables back as integers.

    Opening a group masks the ``_FillValue`` of integer variables, which
    turns them into floats with NaN; this puts the fill value back.
    """
    for name in list(ds.variables):
        var = ds[name]
        dtype = var.encoding.get("dtype")
        if (
            dtype is not None
            and np.issubdtype(np.dtype(dtype), np.integer)
            and var.dtype.kind == "f"
            and "_FillValue" in var.encoding
        ):
            restored = var.fillna(var.encoding["_FillValue"]).astype(dtype)
            restored.encoding = var.encoding
            ds[name] = restored
    return ds


def _slot_positions(blocks: Collection[DayBlock]) -> np.ndarray:
    """The positions of the blocks' slots on the epoch axis, day by day.

    The padding is left out; the days come in time order, whatever order
    their blocks have on the axis.
    """
    ordered = sorted(blocks, key=lambda b: b.day)
    if not ordered:
        return np.empty(0, dtype=np.int64)
    return np.concatenate(
        [np.arange(b.start, b.start + b.slots, dtype=np.int64) for b in ordered]
    )


def to_stored_axis(ds: xr.Dataset, store: Any, group: str) -> xr.Dataset:
    """Variables of ``ds``, as :func:`load_group` reads them, on the stored axis.

    The reverse of :func:`load_group`: each day's slots go back into the
    day's block, and the padding gets each variable's missing value
    (:func:`fill_value`). Variables without ``epoch`` stay as they are; the
    ``epoch`` coordinate is left out, since the stored one stays.

    Raises
    ------
    LayoutError
        If ``group`` is not made of day blocks.
    ValueError
        If ``ds`` does not have one epoch per slot of the group.
    """
    zgroup = zarr.open_group(store, mode="r", path=group)
    _require_day_blocks(zgroup, group)
    length = int(_epoch_array(zgroup, group).shape[0])
    blocks = _blocks_from_index(_index(zgroup, group), length, group)
    positions = _slot_positions(blocks.values())
    if ds.sizes.get("epoch") != positions.size:
        msg = (
            f"Group '{group}' has {positions.size} slots, the data "
            f"{ds.sizes.get('epoch', 0)} epochs."
        )
        raise ValueError(msg)
    source = np.zeros(length, dtype=np.int64)
    source[positions] = np.arange(positions.size)
    is_slot = np.zeros(length, dtype=bool)
    is_slot[positions] = True
    slot = xr.DataArray(is_slot, dims="epoch")

    ds = ds.drop_vars("epoch", errors="ignore")
    out = ds.isel(epoch=source)
    for name, var in ds.data_vars.items():
        if "epoch" in var.dims:
            fill = fill_value(var, str(name))
            out[name] = xr.where(slot, out[name], fill, keep_attrs=True).astype(
                var.dtype
            )
    return out


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
