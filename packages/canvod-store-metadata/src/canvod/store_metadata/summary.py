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


def cadence_ranges(epochs: np.ndarray) -> list[dict[str, Any]]:
    """The time ranges of ``epochs`` at one cadence, in time order.

    Consecutive days at the same cadence (see :func:`day_cadences`) form one
    range, from its first to its last epoch. Each range is
    ``{"start": ISO, "end": ISO, "cadence_s": float}``.
    """
    epochs = np.unique(np.asarray(epochs).astype("M8[ns]"))
    days = epochs.astype("M8[D]")
    ranges: list[dict[str, Any]] = []
    for day, cadence in sorted(day_cadences(epochs).items()):
        on_day = epochs[days == day]
        if ranges and ranges[-1]["cadence_s"] == cadence:
            ranges[-1]["end"] = _iso(on_day[-1])
        else:
            ranges.append(
                {
                    "start": _iso(on_day[0]),
                    "end": _iso(on_day[-1]),
                    "cadence_s": cadence,
                }
            )
    return ranges


def _data_groups(root: zarr.Group) -> dict[str, zarr.Group]:
    """Groups holding data (an ``epoch`` array), keyed by their path."""
    return {
        name: member
        for name, member in root.members(max_depth=None)
        if isinstance(member, zarr.Group) and "epoch" in member
    }


def _group_summary(group: zarr.Group) -> dict[str, Any]:
    epochs = np.unique(_decode_epochs(_array(group, "epoch")))
    variables = sorted(name for name, arr in group.arrays() if len(arr.shape) >= 2)
    sids = np.asarray(_array(group, "sid")[...]) if "sid" in group else np.array([])
    systems = (
        {str(s) for s in np.asarray(_array(group, "system")[...])}
        if "system" in group
        else set()
    )
    return {
        "epochs": epochs,
        "sids": {str(s) for s in sids},
        "variables": variables,
        "systems": systems,
    }


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
    data_groups = _data_groups(root)
    groups = {name: _group_summary(g) for name, g in data_groups.items()}
    if not groups:
        return {}

    epochs = np.unique(np.concatenate([g["epochs"] for g in groups.values()]))
    start, end = _iso(epochs[0]), _iso(epochs[-1])
    # The finest cadence of any day in any group.
    cadences = [c for g in groups.values() for c in day_cadences(g["epochs"]).values()]
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
            (epochs[-1] - epochs[0]) / np.timedelta64(1, "s")
        ),
        "temporal.time_coverage_resolution": (
            _iso_duration(resolution) if resolution is not None else None
        ),
        "spatial.extent_temporal_interval": [[start, end]],
        "summaries.total_epochs": int(epochs.size),
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
        if not own:
            continue
        r_epochs = np.unique(np.concatenate([g["epochs"] for g in own]))
        prefix = f"instruments.receivers.{receiver}"
        updates[f"{prefix}.epochs"] = int(r_epochs.size)
        updates[f"{prefix}.sids"] = len(set().union(*(g["sids"] for g in own)))
        updates[f"{prefix}.variables"] = sorted(
            set().union(*(g["variables"] for g in own))
        )
        updates[f"{prefix}.temporal_range"] = [_iso(r_epochs[0]), _iso(r_epochs[-1])]
        updates[f"{prefix}.cadences"] = cadence_ranges(r_epochs)
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
