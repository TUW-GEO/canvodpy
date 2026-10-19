"""Move a store written by appending files to day blocks (ADR 0016).

``canvodpy store migrate-layout`` calls :func:`migrate_layout`. Each data
group of the store (a group with an ``epoch`` array, at any depth) is moved:

- A group written by appending is written again as day blocks, day by
  day. An epoch stored more than once keeps the entry written last.
  A day's cadence is the finest step between its epochs, rounded to 1 ms;
  a day with a single epoch takes the finest cadence of the group. The
  group gets the epoch chunk and the dimension chunks given (those of the
  settings); its attributes, its log book and its other metadata
  (``metadata/``) stay.
- A group of day blocks without a block index (written by a development
  version of canVODpy) gets its index; its data stay as they are.
- A group of day blocks with its block index stays as it is.

The snapshot summary counts the epochs of a day-block group from the
``epochs`` column of its log book, so the migration fills it for every
stored row of a rewritten group: each epoch counts once, for the latest
row of the summary's keys (:func:`~canvod.store_metadata.summary.logged_keys`)
whose span holds it. Rows of earlier writes of a key count 0.

Everything goes into one commit, under the store's commit lock, onto the
snapshot the migration read: a commit of another run in between makes it
fail, and nothing is written. Snapshots from before keep the old layout and
stay readable.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr
import zarr
import zarr.errors
from canvod.store_metadata.collectors import collect_config_snapshot
from canvod.store_metadata.io import commit_lock, commit_with_rebase
from canvod.store_metadata.layout import (
    DAY_BLOCK_INDEX_ATTR,
    LayoutError,
    is_day_block_group,
)
from canvod.store_metadata.location import (
    MIGRATE_COMMAND,
    StoreLocation,
    open_repository,
    store_location,
)
from canvod.store_metadata.summary import logged_keys

from canvod.store.day_blocks import (
    _DAY_NS,
    CadenceError,
    _create_group,
    add_day_block,
    data_groups,
    day_blocks,
    day_slots,
    restore_integers,
    write_file_region,
)
from canvod.store.store import cleanse_dataset_attrs, normalize_encodings

#: What the migration does to a group.
REWRITE = "rewrite"
INDEX = "index"
NOTHING = "nothing"

#: Encoding of a variable kept when a group is written again; the rest
#: (chunks, codecs) is the stored group's and is set anew.
_KEPT_ENCODING = ("dtype", "_FillValue", "units", "calendar")

_MS = 1_000_000
_NO_EPOCHS = np.empty(0, dtype=np.int64)


@dataclass(frozen=True)
class GroupLayoutMigration:
    """What :func:`migrate_layout` does, or did, to one group.

    Attributes
    ----------
    group
        The group.
    action
        ``"rewrite"`` (written by appending, written again as day blocks),
        ``"index"`` (day blocks without a block index, which it gets) or
        ``"nothing"`` (day blocks already).
    cadences
        Each day's cadence in seconds, by day.
    epochs
        Epochs of a rewritten group, each once.
    duplicates
        Entries of a rewritten group dropped because a later entry of the
        same epoch was stored.
    unlogged
        Epochs of a rewritten group that no stored log-book row covers,
        so the snapshot summary does not count them; known after the
        migration.
    """

    group: str
    action: str
    cadences: dict[np.datetime64, float]
    epochs: int = 0
    duplicates: int = 0
    unlogged: int = 0
    # Positions on the stored axis of the epochs kept, and their times
    # (ns), in time order; the block index of a group that gets one.
    _kept: np.ndarray = field(default_factory=lambda: _NO_EPOCHS, repr=False)
    _times: np.ndarray = field(default_factory=lambda: _NO_EPOCHS, repr=False)
    _index: dict[str, dict[str, int]] = field(default_factory=dict, repr=False)


@dataclass(frozen=True)
class LayoutMigration:
    """The result of :func:`migrate_layout`.

    ``snapshot_id`` is ``None`` when every group was made of day blocks
    with its index already, so nothing was committed.
    """

    snapshot_id: str | None
    groups: list[GroupLayoutMigration]


def plan_layout_migration(
    store_path: StoreLocation | Path | str, branch: str = "main"
) -> list[GroupLayoutMigration]:
    """What :func:`migrate_layout` would do to each data group of a store.

    Reads only the groups' epochs and attributes.

    Raises
    ------
    ValueError
        If the store has no repository metadata (see :func:`migrate_layout`).
    LayoutError, CadenceError
        See :func:`migrate_layout`.
    """
    location = store_location(store_path)
    repo = open_repository(location)
    _require_repository_metadata(repo, location)
    store = repo.readonly_session(branch=branch).store
    return [_plan_group(store, group) for group in data_groups(store)]


def migrate_layout(
    store_path: StoreLocation | Path | str,
    *,
    epoch_chunk: int = 180,
    dim_chunks: dict[str, int] | None = None,
    config: Any = None,
    branch: str = "main",
) -> LayoutMigration:
    """Move every data group of a store to day blocks, in one commit.

    Parameters
    ----------
    store_path
        The store.
    epoch_chunk
        Epochs per chunk of a rewritten group.
    dim_chunks
        Chunk sizes of a rewritten group along its other dimensions, e.g.
        ``{"sid": 64}``; ``-1`` or a dimension left out is one chunk.
    config
        The settings recorded in the commit metadata; ``None`` loads them.
        They are recorded only: the migration changes no content setting.
    branch
        The branch to migrate.

    Raises
    ------
    ValueError
        If the store has no repository metadata: it needs
        ``canvodpy store migrate-metadata`` first.
    LayoutError
        If a day-block group has a damaged block index, or one cannot be
        rebuilt for it, or a group has no epochs to take a cadence from.
    CadenceError
        If two epochs of a day are less than half a millisecond apart.
    canvod.store.day_blocks.SlotCollisionError
        If two epochs of a day fall into one slot of the day's cadence.

    Nothing is written when an error is raised.
    """
    location = store_location(store_path)
    if config is None:
        from canvod.config import load_config

        config = load_config()
    with commit_lock(location):
        repo = open_repository(location)
        _require_repository_metadata(repo, location)
        session = repo.writable_session(branch)
        old = repo.readonly_session(snapshot_id=session.snapshot_id).store
        done = []
        for group in data_groups(old):
            plan = _plan_group(old, group)
            if plan.action == REWRITE:
                _rewrite_group(session, old, plan, epoch_chunk, dim_chunks)
                plan = replace(plan, unlogged=_count_epochs(session, plan))
            elif plan.action == INDEX:
                zgroup = zarr.open_group(session.store, mode="r+", path=group)
                zgroup.attrs.update({DAY_BLOCK_INDEX_ATTR: plan._index})
            done.append(plan)
        if all(plan.action == NOTHING for plan in done):
            return LayoutMigration(None, done)
        moved = [plan.group for plan in done if plan.action != NOTHING]
        snapshot_id = commit_with_rebase(
            session,
            f"Move groups {', '.join(moved)} to day blocks (migrate-layout)",
            store_path=location,
            config=collect_config_snapshot(config),
            rebase=False,
        )
    return LayoutMigration(snapshot_id, done)


def _require_repository_metadata(repo: Any, location: StoreLocation) -> None:
    if not repo.get_metadata():
        msg = (
            f"The store at {location} has no repository metadata; move it to "
            "the current form first, then to day blocks:\n"
            f"  {MIGRATE_COMMAND} SITE --store gnss|vod"
        )
        raise ValueError(msg)


def _epochs_ns(store: Any, group: str) -> np.ndarray:
    """The group's epochs as stored, in ns since 1970."""
    ds = xr.open_zarr(store, group=group, chunks={}, consolidated=False)
    return ds["epoch"].values.astype("M8[ns]").astype(np.int64)


def _plan_group(store: Any, group: str) -> GroupLayoutMigration:
    zgroup = zarr.open_group(store, mode="r", path=group)
    if is_day_block_group(zgroup.attrs):
        if DAY_BLOCK_INDEX_ATTR in zgroup.attrs:
            blocks = day_blocks(store, group)
            return GroupLayoutMigration(
                group,
                NOTHING,
                {day: block.cadence_s for day, block in sorted(blocks.items())},
            )
        index = _rebuilt_index(zgroup, group, _epochs_ns(store, group))
        return GroupLayoutMigration(
            group,
            INDEX,
            {
                np.datetime64(day, "D"): entry["cadence_ns"] / 1e9
                for day, entry in sorted(index.items())
            },
            _index=index,
        )

    epochs = _epochs_ns(store, group)
    # Stable: of the entries of one epoch, the one written last stays last.
    order = np.argsort(epochs, kind="stable")
    times = epochs[order]
    last = np.ones(times.size, dtype=bool)
    last[:-1] = times[1:] != times[:-1]
    kept, times = order[last], times[last]
    if not times.size:
        msg = f"Group '{group}' holds no epochs, so it has no days to move."
        raise LayoutError(msg)
    cadences = _cadences(times, group)
    return GroupLayoutMigration(
        group,
        REWRITE,
        {day: step / 1e9 for day, step in cadences.items()},
        epochs=int(times.size),
        duplicates=int(epochs.size - times.size),
        _kept=kept,
        _times=times,
    )


def _cadences(times: np.ndarray, group: str) -> dict[np.datetime64, int]:
    """Each day's cadence in ns: the finest step between its epochs, to 1 ms.

    ``times`` are sorted, each once. A day with a single epoch takes the
    finest cadence of the group.

    Raises
    ------
    LayoutError
        If no day has two epochs.
    CadenceError
        If two epochs of a day are less than half a millisecond apart.
    """
    days = times // _DAY_NS
    numbers, starts = np.unique(days, return_index=True)
    stops = np.append(starts[1:], times.size)
    steps: dict[np.datetime64, int | None] = {}
    for number, start, stop in zip(numbers, starts, stops, strict=True):
        day = np.datetime64(int(number), "D")
        if stop - start < 2:
            steps[day] = None
            continue
        finest = int(np.diff(times[start:stop]).min())
        step = round(finest / _MS) * _MS
        if step <= 0:
            msg = (
                f"Two epochs of {day} in group '{group}' are "
                f"{finest} ns apart, less than the 1 ms a cadence is rounded "
                "to; the group cannot be moved to day blocks."
            )
            raise CadenceError(msg)
        steps[day] = step
    known = [step for step in steps.values() if step is not None]
    if not known:
        msg = (
            f"Group '{group}' has no day with two epochs, so no cadence can "
            "be taken from its data."
        )
        raise LayoutError(msg)
    finest = min(known)
    return {day: finest if step is None else step for day, step in steps.items()}


def _rebuilt_index(
    zgroup: zarr.Group, group: str, epochs: np.ndarray
) -> dict[str, dict[str, int]]:
    """The block index of a day-block group written without one.

    Such a group was written by a development version that took only
    cadences dividing a day into whole epoch chunks: its blocks follow one
    another without padding, one per day, each a whole day of slots.

    Raises
    ------
    LayoutError
        If the epoch axis is not made of such blocks.
    """
    epoch = zgroup["epoch"]
    assert isinstance(epoch, zarr.Array)
    epoch_chunk = int(epoch.chunks[0])
    days = epochs // _DAY_NS
    edges = np.flatnonzero(np.diff(days)) + 1
    starts = np.concatenate([[0], edges]).astype(int)
    stops = np.concatenate([edges, [epochs.size]]).astype(int)
    index: dict[str, dict[str, int]] = {}
    for start, stop in zip(starts, stops, strict=True):
        slots = stop - start
        day = str(np.datetime64(int(days[start]), "D"))
        if (
            day in index
            or _DAY_NS % slots
            or day_slots(_DAY_NS // slots) != slots
            or slots % epoch_chunk
        ):
            msg = (
                f"Group '{group}' is made of day blocks without a block index, "
                f"and its block of {day} ({slots} epochs from position "
                f"{start}) is not a whole day of slots in whole chunks, so the "
                "index cannot be rebuilt. Write the group again from its files."
            )
            raise LayoutError(msg)
        index[day] = {
            "start": int(start),
            "stop": int(stop),
            "slots": int(slots),
            "cadence_ns": int(_DAY_NS // slots),
        }
    return index


def _plain(ds: xr.Dataset) -> xr.Dataset:
    """``ds`` without the storage encoding of the group it was read from."""
    ds = ds.copy(deep=False)
    for var in ds.variables.values():
        var.encoding = {k: v for k, v in var.encoding.items() if k in _KEPT_ENCODING}
    return ds


def _rewrite_group(
    session: Any,
    old: Any,
    plan: GroupLayoutMigration,
    epoch_chunk: int,
    dim_chunks: dict[str, int] | None,
) -> None:
    """Write a group written by appending again as day blocks.

    The group's arrays are deleted and created anew; its subgroups
    (``metadata/``) and attributes stay. Its data are read from ``old``,
    the snapshot the session was opened on, one day at a time.
    """
    group = plan.group
    ds = restore_integers(xr.open_zarr(old, group=group, chunks={}, consolidated=False))
    ds = _plain(cleanse_dataset_attrs(ds))
    zgroup = zarr.open_group(session.store, mode="r+", path=group)
    for name in list(zgroup.array_keys()):
        del zgroup[name]

    days = plan._times // _DAY_NS
    numbers, starts = np.unique(days, return_index=True)
    stops = np.append(starts[1:], days.size)
    created = False
    for number, start, stop in zip(numbers, starts, stops, strict=True):
        day = np.datetime64(int(number), "D")
        data = normalize_encodings(ds.isel(epoch=plan._kept[start:stop]).load())
        if not created:
            _create_group(
                session,
                group,
                data,
                epoch_chunk,
                dim_chunks,
                keep_subgroups=True,
            )
            created = True
        add_day_block(session, group, day, plan.cadences[day], None)
        write_file_region(session, group, data)


def _count_epochs(session: Any, plan: GroupLayoutMigration) -> int:
    """Fill the ``epochs`` column of a rewritten group's log book.

    Returns the epochs no stored row covers.
    """
    zgroup = zarr.open_group(session.store, mode="r+", path=plan.group)
    keys = logged_keys(zgroup)
    table = zgroup["metadata/table"]
    assert isinstance(table, zarr.Group)
    starts, ends = (
        np.asarray(_column(table, name)[...]).astype("M8[ns]")
        for name in ("start", "end")
    )
    latest = {key: row for row, key in enumerate(keys) if key is not None}
    owner = np.full(plan._times.size, -1, dtype=np.int64)
    for row in sorted(latest.values()):
        if np.isnat(starts[row]) or np.isnat(ends[row]):
            continue
        low = np.searchsorted(plan._times, starts[row].astype(np.int64), "left")
        high = np.searchsorted(plan._times, ends[row].astype(np.int64), "right")
        owner[low:high] = row
    counts = np.where([key is not None for key in keys], 0, -1).astype(np.int64)
    rows, n = np.unique(owner[owner >= 0], return_counts=True)
    counts[rows] = n
    if "epochs" not in table:
        table.create_array(
            "epochs", shape=(len(keys),), dtype="i8", chunks=(1024,), fill_value=-1
        )
    _column(table, "epochs")[:] = counts
    return int((owner < 0).sum())


def _column(table: zarr.Group, name: str) -> zarr.Array:
    column = table[name]
    assert isinstance(column, zarr.Array)
    return column
