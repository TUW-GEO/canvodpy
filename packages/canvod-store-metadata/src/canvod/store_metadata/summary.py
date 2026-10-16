"""Summarize the data held in a store for its metadata record.

The temporal coverage and the ``summaries`` section describe the store's
contents, so they are recomputed from the store after every write instead of
being fixed when the store is created.
"""

from __future__ import annotations

import json
import warnings
from collections.abc import Collection, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import zarr
from canvod.config.models.sites import reference_store_group

from .layout import is_day_block_group

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

# Log-book actions whose file is part of the stored data.
_STORED_ACTIONS = {"initial", "written", "appended", "overwritten"}
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


def _logged_files(
    group: zarr.Group,
) -> dict[str, tuple[int, np.datetime64, np.datetime64]]:
    """Stored writes of a day-block group: epochs with data, first and last.

    From the group's log book; the latest stored row of a key counts. A
    GNSS log book (``rinex_hash`` column) is keyed by file hash, so a file
    stored in several groups counts once. A VOD log book
    (``source_file_hashes`` column) has one row per day written, and a day
    written again replaces it, so it is keyed by group and day.
    """
    table = group["metadata/table"] if "metadata/table" in group else None
    keys = set(table.array_keys()) if isinstance(table, zarr.Group) else set()
    if "rinex_hash" in keys:
        key_column, stored_actions = "rinex_hash", _STORED_ACTIONS
    elif "source_file_hashes" in keys:
        key_column, stored_actions = "source_file_hashes", _VOD_STORED_ACTIONS
    else:
        msg = (
            f"Day-block group {group.path} has no GNSS or VOD log book; its "
            "epoch count cannot be summarized"
        )
        raise ValueError(msg)
    columns = (key_column, "action", "start", "end", "epochs")
    if not set(columns) <= keys:
        msg = (
            f"Day-block group {group.path} has no log book with the columns "
            f"{', '.join(columns)}; its epoch count cannot be summarized"
        )
        raise ValueError(msg)
    hashes, actions, starts, ends, counts = (
        np.asarray(_array(table, name)[...]) for name in columns
    )
    files = {}
    for file_hash, action, start, end, count in zip(
        hashes, actions, starts, ends, counts, strict=True
    ):
        if action not in stored_actions:
            continue
        if count < 0:
            msg = (
                f"Log book of day-block group {group.path} has a stored row "
                f"without an epoch count ({key_column} {file_hash})"
            )
            raise ValueError(msg)
        start = np.datetime64(start, "ns")
        key = (
            str(file_hash)
            if key_column == "rinex_hash"
            else f"{group.path}@{start.astype('M8[D]')}"
        )
        files[key] = (int(count), start, np.datetime64(end, "ns"))
    return files


def _block_days(
    epochs: np.ndarray, files: Mapping[str, tuple[int, np.datetime64, np.datetime64]]
) -> dict[np.datetime64, _DaySpan]:
    """Each day's cadence and first and last epoch, in a day-block group.

    A day's cadence is the day divided by its slots; its first and last
    epoch come from the files covering it. Days without files (a block
    whose files failed) are left out.
    """
    days, slots = np.unique(epochs.astype("M8[D]"), return_counts=True)
    cadences = {
        day: round(86400 / int(n), 3) for day, n in zip(days, slots, strict=True)
    }
    spans: dict[np.datetime64, _DaySpan] = {}
    for _, start, end in files.values():
        day = start.astype("M8[D]")
        while day <= end.astype("M8[D]"):
            cadence = cadences[day]
            last_slot = (day + _DAY).astype("M8[ns]") - np.timedelta64(
                int(cadence * 1e9), "ns"
            )
            first = max(start, day.astype("M8[ns]"))
            last = min(end, last_slot)
            if day in spans:
                _, f, la = spans[day]
                first, last = min(first, f), max(last, la)
            spans[day] = (cadence, first, last)
            day = day + _DAY
    return spans


def _group_summary(group: zarr.Group) -> dict[str, Any]:
    """What a data group holds.

    ``epochs`` are the epochs of a group written by appending; a day-block
    group (ADR 0016) has a slot for every epoch of its days, with or
    without data, so its ``files`` (from the log book) say which epochs
    hold data and ``epochs`` is empty. ``days`` gives each day's cadence
    and its first and last epoch with data.
    """
    all_epochs = _decode_epochs(_array(group, "epoch"))
    if is_day_block_group(group.attrs):
        files = _logged_files(group)
        epochs = np.array([], dtype="M8[ns]")
        days = _block_days(all_epochs, files)
    else:
        files = {}
        epochs = np.unique(all_epochs)
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
    files = {h: f for g in groups for h, f in g["files"].items()}
    times = [*epochs[:1], *epochs[-1:]] + [t for _, *ts in files.values() for t in ts]
    if not times:
        return None
    days: dict[np.datetime64, _DaySpan] = {}
    for g in groups:
        for day, (cadence, first, last) in g["days"].items():
            if day in days:
                c, f, la = days[day]
                cadence, first, last = min(cadence, c), min(first, f), max(last, la)
            days[day] = (cadence, first, last)
    count = int(epochs.size) + sum(n for n, _, _ in files.values())
    return count, min(times), max(times), days


def _stored_file_count(group: zarr.Group) -> int | None:
    """Distinct stored files in a GNSS group's log book, if it has one."""
    if "metadata/table" not in group:
        return None
    table = group["metadata/table"]
    if (
        not isinstance(table, zarr.Group)
        or "rinex_hash" not in table
        or "action" not in table
    ):
        return None
    hashes = np.asarray(_array(table, "rinex_hash")[...])
    actions = np.asarray(_array(table, "action")[...])
    return len(
        {str(h) for h, a in zip(hashes, actions, strict=True) if a in _STORED_ACTIONS}
    )


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


def _header_positions(group: zarr.Group) -> dict[str, tuple[float, float, float]]:
    """Header positions of the stored files in a group's log book, by hash."""
    if "metadata/table" not in group:
        return {}
    table = group["metadata/table"]
    if not isinstance(table, zarr.Group) or not {"rinex_hash", "action", "attrs"} <= {
        name for name, _ in table.arrays()
    }:
        return {}
    rows = zip(
        np.asarray(_array(table, "rinex_hash")[...]),
        np.asarray(_array(table, "action")[...]),
        np.asarray(_array(table, "attrs")[...]),
        strict=True,
    )
    positions = {}
    for file_hash, action, attrs in rows:
        if action not in _STORED_ACTIONS:
            continue
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
    groups = {name: _group_summary(g) for name, g in data_groups.items()}
    if not groups:
        return {}

    coverage = _coverage(list(groups.values()))
    if coverage is None:
        return {}
    total, first, last, days = coverage
    start, end = _iso(first), _iso(last)
    # The finest cadence of any day in any group.
    cadences = [cadence for cadence, _, _ in days.values()]
    resolution = min(cadences) if cadences else None
    systems = set().union(*(g["systems"] for g in groups.values()))
    file_counts = [
        n
        for n in (_stored_file_count(g) for g in data_groups.values())
        if n is not None
    ]

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
    by_receiver = _groups_by_receiver(receivers, list(groups))
    for receiver in sorted(by_receiver):
        # A reference receiver is stored once per canopy it is paired with
        # (e.g. ``reference_01_canopy_01``); combine all of its groups.
        own = [groups[name] for name in sorted(by_receiver[receiver])]
        r_coverage = _coverage(own) if own else None
        if r_coverage is None:
            continue
        r_total, r_first, r_last, r_days = r_coverage
        prefix = f"instruments.receivers.{receiver}"
        updates[f"{prefix}.epochs"] = r_total
        updates[f"{prefix}.sids"] = len(set().union(*(g["sids"] for g in own)))
        updates[f"{prefix}.variables"] = sorted(
            set().union(*(g["variables"] for g in own))
        )
        updates[f"{prefix}.temporal_range"] = [_iso(r_first), _iso(r_last)]
        updates[f"{prefix}.cadences"] = _ranges(r_days)
        # A file stored in several groups (a reference paired with several
        # canopies) counts once.
        positions = {
            file_hash: xyz
            for name, g in data_groups.items()
            if name in by_receiver[receiver]
            for file_hash, xyz in _header_positions(g).items()
        }
        if positions:
            updates[f"{prefix}.position_ecef_m"] = [
                float(v) for v in np.median(np.array(list(positions.values())), axis=0)
            ]
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
