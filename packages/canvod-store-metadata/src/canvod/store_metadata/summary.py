"""Summarize the data held in a store for its metadata record.

The temporal coverage and the ``summaries`` section describe the store's
contents, so they are recomputed from the store after every write instead of
being fixed when the store is created.
"""

from __future__ import annotations

import json
import warnings
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

import numpy as np
import zarr
from canvod.config.models.sites import reference_store_group

from .layout import DAY_BLOCK_INDEX_ATTR, is_day_block_group

if TYPE_CHECKING:
    from .location import StoreLocation

_CONSTELLATIONS = {
    "G": "GPS",
    "R": "GLONASS",
    "E": "Galileo",
    "C": "BeiDou",
    "J": "QZSS",
    "I": "NavIC",
    "S": "SBAS",
}

_CF_UNITS = {
    "nanoseconds": "ns",
    "microseconds": "us",
    "milliseconds": "ms",
    "seconds": "s",
    "minutes": "m",
    "hours": "h",
    "days": "D",
}

# Log-book actions whose file is part of the stored data: those of a run,
# and those the store's own write methods record.
_STORED_ACTIONS = {
    "initial",
    "written",
    "appended",
    "overwritten",
    "write",
    "append",
    "overwrite",
}
# Actions of a VOD log book's rows whose result is part of the stored data.
_VOD_STORED_ACTIONS = {"write", "append", "overwrite"}

_DAY = np.timedelta64(1, "D")

# A day's cadence (s) and its first and last epoch with data.
_DaySpan = tuple[float, np.datetime64, np.datetime64]


def _decode_epochs(arr: zarr.Array) -> np.ndarray:
    """Epoch values as ``datetime64[ns]``, decoding CF time units if needed."""
    values = np.asarray(arr[...])
    if np.issubdtype(values.dtype, np.datetime64):
        return values.astype("M8[ns]")
    unit, _, reference = str(arr.attrs["units"]).partition(" since ")
    ref = np.datetime64(reference.strip().replace(" ", "T").split("+")[0], "ns")
    return ref + values.astype("i8").astype(f"m8[{_CF_UNITS[unit.strip()]}]")


def _array(group: zarr.Group, path: str) -> zarr.Array:
    """The array at ``path`` in ``group``."""
    member = group[path]
    if not isinstance(member, zarr.Array):
        msg = f"{path} in {group.path or '/'} is a group, not an array"
        raise TypeError(msg)
    return member


class _Book(Protocol):
    """Log-book columns: a whole log book (:class:`_LogBook`) or new rows."""

    columns: set[str]

    def __contains__(self, column: str) -> bool: ...

    def __getitem__(self, column: str) -> np.ndarray: ...

    def read(self, column: str) -> np.ndarray: ...


class _LogBook:
    """A group's log book (``metadata/table``), each column read at most once.

    The summary of a commit reads the same columns for several parts (epoch
    counts, file count, header positions); reading each once keeps the
    commit's cost to one pass over the log book. A column only one part
    reads, such as the header attributes, is read with :meth:`read` and
    not kept.
    """

    def __init__(self, table: zarr.Group) -> None:
        self._table = table
        self.columns = set(table.array_keys())
        self._values: dict[str, np.ndarray] = {}

    def __contains__(self, column: str) -> bool:
        return column in self.columns

    def __getitem__(self, column: str) -> np.ndarray:
        if column not in self._values:
            self._values[column] = self.read(column)
        return self._values[column]

    def read(self, column: str) -> np.ndarray:
        """The values of ``column``, read without keeping them."""
        return np.asarray(_array(self._table, column)[...])


def _log_book(group: zarr.Group) -> _LogBook | None:
    """The log book of ``group``; ``None`` if it has none."""
    table = group["metadata/table"] if "metadata/table" in group else None
    return _LogBook(table) if isinstance(table, zarr.Group) else None


def _iso(t: np.datetime64) -> str:
    return f"{np.datetime_as_string(t, unit='s')}Z"


def _iso_duration(seconds: float) -> str:
    """ISO 8601 duration in seconds, never in exponent notation."""
    return f"PT{np.format_float_positional(seconds, trim='-')}S"


def day_cadences(epochs: np.ndarray) -> dict[np.datetime64, float]:
    """The cadence of each day in ``epochs``, in seconds, by day.

    A day's cadence is the median step between its consecutive epochs, so
    missing epochs do not change it; steps into the next day are not counted.
    ``epochs`` may be in any order (day blocks are stored in the order they
    were written). A day with a single epoch has no cadence and is left out.
    Cadences are rounded to the millisecond.
    """
    epochs = np.unique(np.asarray(epochs).astype("M8[ns]"))
    days = epochs.astype("M8[D]")
    same_day = days[1:] == days[:-1]
    steps = (np.diff(epochs) / np.timedelta64(1, "s"))[same_day]
    step_days = days[:-1][same_day]
    return {
        day: round(float(np.median(steps[step_days == day])), 3)
        for day in np.unique(step_days)
    }


def _epoch_days(epochs: np.ndarray) -> dict[np.datetime64, _DaySpan]:
    """Each day's cadence and first and last epoch, from the epochs."""
    epochs = np.unique(np.asarray(epochs).astype("M8[ns]"))
    days = epochs.astype("M8[D]")
    spans = {}
    for day, cadence in day_cadences(epochs).items():
        on_day = epochs[days == day]
        spans[day] = (cadence, on_day[0], on_day[-1])
    return spans


def _ranges(days: Mapping[np.datetime64, _DaySpan]) -> list[dict[str, Any]]:
    """Consecutive days at the same cadence, merged into time ranges."""
    ranges: list[dict[str, Any]] = []
    for _, (cadence, first, last) in sorted(days.items()):
        if ranges and ranges[-1]["cadence_s"] == cadence:
            ranges[-1]["end"] = _iso(last)
        else:
            ranges.append(
                {"start": _iso(first), "end": _iso(last), "cadence_s": cadence}
            )
    return ranges


def cadence_ranges(epochs: np.ndarray) -> list[dict[str, Any]]:
    """The time ranges of ``epochs`` at one cadence, in time order.

    Consecutive days at the same cadence (see :func:`day_cadences`) form one
    range, from its first to its last epoch. Each range is
    ``{"start": ISO, "end": ISO, "cadence_s": float}``.
    """
    return _ranges(_epoch_days(epochs))


def _data_groups(root: zarr.Group) -> dict[str, zarr.Group]:
    """Groups holding data (an ``epoch`` array), keyed by their path."""
    return {
        name: member
        for name, member in root.members(max_depth=None)
        if isinstance(member, zarr.Group) and "epoch" in member
    }


def _observation_groups(root: zarr.Group) -> dict[str, zarr.Group]:
    """Data groups that hold observations, keyed by their path.

    Datasets under a group's ``metadata/`` (``sbf_obs``, the log book)
    describe the group's files; they are not observations of their own.
    """
    return {
        name: member
        for name, member in _data_groups(root).items()
        if "metadata" not in name.split("/")
    }


def logged_keys(group: zarr.Group) -> list[str | None]:
    """The key of each row of a day-block group's log book; ``None`` if not stored.

    A row whose action stores data has a key; the latest stored row of a
    key says what the group holds of it (:func:`_logged_files`). A GNSS
    log book (``rinex_hash`` column) is keyed by the file's canonical
    name, the period whose slots the file writes, so a file written again
    with other data (a new hash) replaces its earlier row; a row without a
    canonical name is keyed by file hash. A VOD log book
    (``source_file_hashes`` column) has one row per day written, and a day
    written again replaces it, so it is keyed by group and day.

    Raises
    ------
    ValueError
        If the group has no GNSS or VOD log book.
    """
    return _logged_keys(_log_book(group), group.path)


def _logged_keys(book: _Book | None, path: str) -> list[str | None]:
    """:func:`logged_keys` of the group at ``path``, from its log book."""
    return _key_array(book, path).tolist()


def _key_array(book: _Book | None, path: str) -> np.ndarray:
    """:func:`logged_keys` as an object array, from the log book."""
    if book is None:
        msg = (
            f"Day-block group {path} has no log book; its epoch count "
            "cannot be summarized"
        )
        raise ValueError(msg)
    keys = book.columns
    if "rinex_hash" in keys:
        key_column, stored_actions = "rinex_hash", _STORED_ACTIONS
    elif "source_file_hashes" in keys:
        key_column, stored_actions = "source_file_hashes", _VOD_STORED_ACTIONS
    else:
        msg = (
            f"Day-block group {path} has no GNSS or VOD log book; its "
            "epoch count cannot be summarized"
        )
        raise ValueError(msg)
    if not {key_column, "start"} <= keys or not keys & {"action", "exists"}:
        msg = (
            f"Day-block group {path} has no log book with the columns "
            f"{key_column}, action, start; its epoch count cannot be summarized"
        )
        raise ValueError(msg)
    hashes, starts = book[key_column], book["start"]
    if "action" in keys:
        actions = book["action"]
    else:
        # canVODpy 0.x wrote no action, only whether the file was in the
        # store already (skipped) or not (written), as canvod.store reads it.
        exists = book["exists"]
        actions = np.array(
            ["skipped" if str(e) == "True" else "written" for e in exists],
            dtype=object,
        )
    stored = _is_stored(actions, stored_actions)
    if key_column == "rinex_hash":
        if "canonical_name" in keys:
            names = book["canonical_name"]
            key_values = np.where(names != "", names, hashes)
        else:
            key_values = hashes
    else:
        days = np.datetime_as_string(
            np.asarray(starts).astype("M8[ns]").astype("M8[D]")
        )
        key_values = np.array([f"{path}@{day}" for day in days], dtype=object)
    out = np.full(len(actions), None, dtype=object)
    out[stored] = [str(k) for k in key_values[stored]]
    return out


def _is_stored(actions: np.ndarray, stored_actions: Collection[str]) -> np.ndarray:
    """Whether each row's action stores data."""
    return np.isin(np.asarray(actions, dtype=object), list(stored_actions))


@dataclass(frozen=True)
class _Files:
    """Stored writes, one per key: epochs with data, first and last epoch."""

    keys: np.ndarray
    counts: np.ndarray
    starts: np.ndarray
    ends: np.ndarray

    def __len__(self) -> int:
        return int(self.keys.size)

    def take(self, rows: np.ndarray) -> _Files:
        return _Files(
            self.keys[rows], self.counts[rows], self.starts[rows], self.ends[rows]
        )


_NO_FILES = _Files(
    np.array([], dtype=object),
    np.array([], dtype=np.int64),
    np.array([], dtype="M8[ns]"),
    np.array([], dtype="M8[ns]"),
)


def _latest_rows(keys: np.ndarray) -> np.ndarray:
    """The row of each key's last occurrence in ``keys``, in row order."""
    if not keys.size:
        return np.array([], dtype=np.intp)
    _, first_reversed = np.unique(keys[::-1], return_index=True)
    return np.sort(keys.size - 1 - first_reversed)


def _merged(files: Iterable[_Files]) -> _Files:
    """Writes of several groups, a key's last write counting (as in a dict)."""
    parts = [f for f in files if len(f)]
    if not parts:
        return _NO_FILES
    joined = _Files(
        *(np.concatenate([getattr(f, a) for f in parts]) for a in _FILE_FIELDS)
    )
    return joined.take(_latest_rows(joined.keys))


_FILE_FIELDS = ("keys", "counts", "starts", "ends")


def _logged_files(group: zarr.Group, book: _Book | None) -> _Files:
    """Stored writes of a day-block group: epochs with data, first and last.

    From the group's log book; the latest stored row of a key counts
    (:func:`logged_keys`). A file stored in several groups counts once.
    """
    keys = _key_array(book, group.path)
    assert book is not None
    if not {"end", "epochs"} <= book.columns:
        msg = (
            f"Day-block group {group.path} has no log book with the columns "
            "end, epochs; its epoch count cannot be summarized"
        )
        raise ValueError(msg)
    stored = keys != None  # noqa: E711 (element-wise)
    files = _Files(
        keys[stored],
        np.asarray(book["epochs"])[stored].astype(np.int64),
        np.asarray(book["start"])[stored].astype("M8[ns]"),
        np.asarray(book["end"])[stored].astype("M8[ns]"),
    )
    negative = np.flatnonzero(files.counts < 0)
    if negative.size:
        msg = (
            f"Log book of day-block group {group.path} has a stored row "
            f"without an epoch count ({files.keys[negative[0]]})"
        )
        raise ValueError(msg)
    return files.take(_latest_rows(files.keys))


def _block_index(group: zarr.Group) -> dict[np.datetime64, tuple[int, int]]:
    """Each day's cadence (ns) and number of slots, from the block index.

    The block index (``DAY_BLOCK_INDEX_ATTR``) gives them; the length of a
    day's block does not, since blocks are padded to whole chunks.
    """
    index = group.attrs.get(DAY_BLOCK_INDEX_ATTR)
    if not isinstance(index, Mapping):
        msg = (
            f"Day-block group {group.path} has no block index; its cadences "
            "cannot be summarized"
        )
        raise ValueError(msg)
    days: dict[np.datetime64, tuple[int, int]] = {}
    for day, entry in index.items():
        assert isinstance(entry, Mapping)
        cadence_ns, slots = entry["cadence_ns"], entry["slots"]
        assert isinstance(cadence_ns, int) and isinstance(slots, int)
        days[np.datetime64(str(day), "D")] = (cadence_ns, slots)
    return days


def _block_days(
    index: Mapping[np.datetime64, tuple[int, int]], files: _Files
) -> dict[np.datetime64, _DaySpan]:
    """Each day's cadence and first and last epoch, in a day-block group.

    A day's cadence comes from the block index (:func:`_block_index`); its
    first and last epoch come from the files covering it, up to the day's
    last slot. Days without files (a block whose files failed) are left out,
    and so are files without epochs (a row whose epochs a later row of
    another file holds).

    Raises
    ------
    KeyError
        If a file covers a day without a block.
    """
    files = files.take(np.flatnonzero(files.counts != 0))
    if not len(files):
        return {}
    first_day = files.starts.astype("M8[D]")
    n_days = np.maximum(
        (files.ends.astype("M8[D]") - first_day).astype(np.int64) + 1, 0
    )
    # One entry per file and day it covers.
    row = np.repeat(np.arange(len(files)), n_days)
    nth = np.arange(row.size) - np.repeat(np.cumsum(n_days) - n_days, n_days)
    day = first_day[row] + nth.astype("m8[D]")

    block_days = np.array(sorted(index), dtype="M8[D]")
    at = np.searchsorted(block_days, day)
    found = at < block_days.size
    found[found] = block_days[at[found]] == day[found]
    if not found.all():
        raise KeyError(day[~found][0])
    cadence_ns = np.array([index[d][0] for d in block_days], dtype=np.int64)[at]
    slots = np.array([index[d][1] for d in block_days], dtype=np.int64)[at]
    day_ns = day.astype("M8[ns]")
    last_slot = day_ns + ((slots - 1) * cadence_ns).astype("m8[ns]")
    first = np.maximum(files.starts[row], day_ns).view(np.int64)
    last = np.minimum(files.ends[row], last_slot).view(np.int64)

    days, of_day = np.unique(day, return_inverse=True)
    day_first = np.full(days.size, np.iinfo(np.int64).max)
    day_last = np.full(days.size, np.iinfo(np.int64).min)
    np.minimum.at(day_first, of_day, first)
    np.maximum.at(day_last, of_day, last)
    day_cadence = np.zeros(days.size, dtype=np.int64)
    day_cadence[of_day] = cadence_ns
    return {
        d: (
            int(c) / 1e9,
            np.datetime64(int(f), "ns"),
            np.datetime64(int(la), "ns"),
        )
        for d, c, f, la in zip(days, day_cadence, day_first, day_last, strict=True)
    }


def _group_summary(group: zarr.Group, book: _Book | None) -> dict[str, Any]:
    """What a data group holds.

    ``epochs`` are the epochs of a group written by appending; a day-block
    group (ADR 0016) has a slot for every epoch of its days, with or
    without data, so its ``files`` (from the log book) say which epochs
    hold data and ``epochs`` is empty. ``days`` gives each day's cadence
    and its first and last epoch with data.
    """
    if is_day_block_group(group.attrs):
        files = _logged_files(group, book)
        epochs = np.array([], dtype="M8[ns]")
        days = _block_days(_block_index(group), files)
    else:
        files = _NO_FILES
        epochs = np.unique(_decode_epochs(_array(group, "epoch")))
        days = _epoch_days(epochs)
    variables = sorted(name for name, arr in group.arrays() if len(arr.shape) >= 2)
    sids = np.asarray(_array(group, "sid")[...]) if "sid" in group else np.array([])
    systems = (
        {str(s) for s in np.asarray(_array(group, "system")[...])}
        if "system" in group
        else set()
    )
    return {
        "epochs": epochs,
        "files": files,
        "days": days,
        "sids": {str(s) for s in sids},
        "variables": variables,
        "systems": systems,
    }


def _coverage(
    groups: Collection[dict[str, Any]],
) -> tuple[int, np.datetime64, np.datetime64, dict[np.datetime64, _DaySpan]] | None:
    """Epochs with data, first and last epoch, and days of some groups.

    None if the groups hold no data (a day block whose files all failed).

    Epochs of groups written by appending count once however many groups
    hold them. Day-block groups add the epochs of their files; a file
    stored in several groups (a reference paired with several canopies)
    counts once.
    """
    epochs = np.unique(np.concatenate([g["epochs"] for g in groups]))
    files = _merged(g["files"] for g in groups)
    times = np.concatenate([epochs[:1], epochs[-1:], files.starts, files.ends])
    if not times.size:
        return None
    days: dict[np.datetime64, _DaySpan] = {}
    for g in groups:
        for day, (cadence, first, last) in g["days"].items():
            if day in days:
                c, f, la = days[day]
                cadence, first, last = min(cadence, c), min(first, f), max(last, la)
            days[day] = (cadence, first, last)
    count = int(epochs.size) + int(files.counts.sum())
    return count, times.min(), times.max(), days


def _stored_file_count(book: _Book | None) -> int | None:
    """Distinct stored files in a GNSS group's log book, if it has one.

    Keyed as in :func:`_logged_files`: by canonical name, else by hash.
    """
    if book is None or not {"rinex_hash", "action"} <= book.columns:
        return None
    hashes = book["rinex_hash"]
    keys = (
        np.where(book["canonical_name"] != "", book["canonical_name"], hashes)
        if "canonical_name" in book
        else hashes
    )
    stored = _is_stored(book["action"], _STORED_ACTIONS)
    return len({str(k) for k in keys[stored]})


def _header_position(attrs: dict[str, Any]) -> tuple[float, float, float] | None:
    """A file's header position (ECEF, m) from its log-book ``attrs``.

    RINEX headers give ``APPROX POSITION X/Y/Z``; SBF files give
    ``Approximate Position`` as ``"X=..., Y=..., Z=..."`` (the same two forms
    ``canvod.auxiliary.position.ECEFPosition.from_ds_metadata`` reads). A
    missing or all-zero position counts as not given.
    """
    if "APPROX POSITION X" in attrs:
        xyz = tuple(float(attrs[f"APPROX POSITION {c}"]) for c in "XYZ")
    elif "Approximate Position" in attrs:
        parts = str(attrs["Approximate Position"]).split(",")
        xyz = tuple(float(p.split("=")[1].strip().split()[0]) for p in parts[:3])
    else:
        return None
    return None if not any(xyz) else (xyz[0], xyz[1], xyz[2])


def _header_positions(
    book: _Book | None,
) -> dict[str, tuple[float, float, float]]:
    """Header positions of the stored files in a group's log book, by hash."""
    if book is None or not {"rinex_hash", "action", "attrs"} <= book.columns:
        return {}
    stored = _is_stored(book["action"], _STORED_ACTIONS)
    rows = zip(book["rinex_hash"][stored], book.read("attrs")[stored], strict=True)
    positions = {}
    for file_hash, attrs in rows:
        position = _header_position(json.loads(str(attrs) or "{}"))
        if position is not None:
            positions[str(file_hash)] = position
    return positions


def _store_size_mb(store_path: Path) -> float:
    size = sum(f.stat().st_size for f in store_path.rglob("*") if f.is_file())
    return round(size / 1e6, 3)


def receiver_groups(receivers: Mapping[str, str]) -> dict[str, set[str]]:
    """The store groups that hold each receiver's data.

    ``receivers`` maps each receiver name to its type (``canopy`` or
    ``reference``). A canopy receiver is stored in the group of its name. A
    reference receiver is stored once per canopy receiver it is paired with,
    in the group :func:`~canvod.config.models.sites.reference_store_group`
    names; its own name is kept as well.
    """
    canopies = [name for name, kind in receivers.items() if kind == "canopy"]
    return {
        name: {name}
        | (
            {reference_store_group(name, canopy) for canopy in canopies}
            if kind == "reference"
            else set()
        )
        for name, kind in receivers.items()
    }


def _groups_by_receiver(
    receivers: Mapping[str, str] | Collection[str] | None, names: Collection[str]
) -> dict[str, set[str]]:
    """Which of the group ``names`` belong to each receiver."""
    if receivers is None:
        return {}
    if not isinstance(receivers, Mapping):
        warnings.warn(
            "Receiver names without their types are left over from development "
            "and will be removed with the next major version. Pass a mapping "
            "of receiver name to type (canopy or reference).",
            FutureWarning,
            stacklevel=3,
        )
        return {
            receiver: {
                name
                for name in names
                if name == receiver or name.startswith(f"{receiver}_")
            }
            for receiver in receivers
        }
    return {
        receiver: groups & set(names)
        for receiver, groups in receiver_groups(receivers).items()
    }


def summarize_root(
    root: zarr.Group, receivers: Mapping[str, str] | Collection[str] | None = None
) -> dict[str, Any]:
    """Dotted-key updates describing the data under ``root``.

    The same as :func:`summarize_store` without ``summaries.store_size_mb``,
    for a group that need not be committed yet (the commit function
    summarizes the session it commits).
    """
    data_groups = _observation_groups(root)
    books = {name: _log_book(g) for name, g in data_groups.items()}
    groups = {name: _group_summary(g, books[name]) for name, g in data_groups.items()}
    if not groups:
        return {}

    coverage = _coverage(list(groups.values()))
    if coverage is None:
        return {}
    file_counts = [
        n
        for n in (_stored_file_count(book) for book in books.values())
        if n is not None
    ]
    receivers_held = {}
    by_receiver = _groups_by_receiver(receivers, list(groups))
    for receiver in sorted(by_receiver):
        # A reference receiver is stored once per canopy it is paired with
        # (e.g. ``reference_01_canopy_01``); combine all of its groups.
        names = sorted(by_receiver[receiver])
        r_coverage = _coverage([groups[name] for name in names]) if names else None
        if r_coverage is None:
            continue
        # A file stored in several groups (a reference paired with several
        # canopies) counts once.
        positions = {
            file_hash: xyz
            for name, book in books.items()
            if name in by_receiver[receiver]
            for file_hash, xyz in _header_positions(book).items()
        }
        position = (
            [float(v) for v in np.median(np.array(list(positions.values())), axis=0)]
            if positions
            else None
        )
        receivers_held[receiver] = (names, r_coverage, position)
    return _summary_updates(groups, coverage, receivers_held, file_counts)


_Coverage = tuple[int, np.datetime64, np.datetime64, dict[np.datetime64, _DaySpan]]


def _summary_updates(
    groups: Mapping[str, Mapping[str, Any]],
    coverage: _Coverage,
    receivers: Mapping[str, tuple[list[str], _Coverage, list[float] | None]],
    file_counts: list[int],
) -> dict[str, Any]:
    """Dotted-key updates from what the groups hold.

    ``groups`` gives each group's ``sids``, ``systems`` and ``variables``;
    ``coverage`` that of all groups (:func:`_coverage`); ``receivers`` each
    receiver's group names, coverage and median header position; and
    ``file_counts`` the stored files of each GNSS group. Shared by the full
    rebuild (:func:`summarize_root`) and the summary kept commit by commit
    (:mod:`.summary_state`).
    """
    total, first, last, days = coverage
    start, end = _iso(first), _iso(last)
    # The finest cadence of any day in any group.
    cadences = [cadence for cadence, _, _ in days.values()]
    resolution = min(cadences) if cadences else None
    systems = set().union(*(g["systems"] for g in groups.values()))
    updates: dict[str, Any] = {
        "temporal.collected_start": start,
        "temporal.collected_end": end,
        "temporal.time_coverage_start": start,
        "temporal.time_coverage_end": end,
        "temporal.time_coverage_duration": _iso_duration(
            (last - first) / np.timedelta64(1, "s")
        ),
        "temporal.time_coverage_resolution": (
            _iso_duration(resolution) if resolution is not None else None
        ),
        "spatial.extent_temporal_interval": [[start, end]],
        "summaries.total_epochs": total,
        "summaries.total_sids": len(set().union(*(g["sids"] for g in groups.values()))),
        "summaries.constellations": sorted(_CONSTELLATIONS.get(s, s) for s in systems),
        "summaries.variables": sorted(
            set().union(*(g["variables"] for g in groups.values()))
        ),
        "summaries.temporal_resolution_s": resolution,
        "summaries.file_count": sum(file_counts) if file_counts else None,
    }
    for receiver, (names, r_coverage, position) in sorted(receivers.items()):
        own = [groups[name] for name in names]
        r_total, r_first, r_last, r_days = r_coverage
        prefix = f"instruments.receivers.{receiver}"
        updates[f"{prefix}.epochs"] = r_total
        updates[f"{prefix}.sids"] = len(set().union(*(g["sids"] for g in own)))
        updates[f"{prefix}.variables"] = sorted(
            set().union(*(g["variables"] for g in own))
        )
        updates[f"{prefix}.temporal_range"] = [_iso(r_first), _iso(r_last)]
        updates[f"{prefix}.cadences"] = _ranges(r_days)
        if position is not None:
            updates[f"{prefix}.position_ecef_m"] = position
    return updates


def summarize_store(
    store_path: StoreLocation | Path | str,
    branch: str = "main",
    receivers: Mapping[str, str] | Collection[str] | None = None,
) -> dict[str, Any]:
    """Metadata updates describing the data currently in a store.

    Parameters
    ----------
    store_path : Path
        Path to the Icechunk store.
    branch : str
        Branch to summarize.
    receivers : Mapping[str, str] | None
        The receivers in ``instruments.receivers``, by name, with their type
        (``canopy`` or ``reference``). Each receiver with data in the store
        also gets its per-receiver fields updated, from the groups
        :func:`receiver_groups` gives it. A collection of names without types
        is deprecated; it matches the group named after a receiver and any
        ``{receiver}_*`` group.

    Returns
    -------
    dict[str, Any]
        Dotted-key updates of the snapshot summary's fields, plus
        ``summaries.store_size_mb`` for a local store. Empty if the store
        holds no data yet.
    """
    from .location import open_repository, store_location

    location = store_location(store_path)
    session = open_repository(location).readonly_session(branch=branch)
    updates = summarize_root(zarr.open_group(session.store, mode="r"), receivers)
    # The size on disk; a store on S3 has no directory to measure.
    if updates and location.local_path is not None:
        updates["summaries.store_size_mb"] = _store_size_mb(location.local_path)
    return updates
