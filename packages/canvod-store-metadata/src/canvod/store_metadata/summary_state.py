"""The snapshot summary of a store, kept up to date commit by commit.

ADR 0021 (#418, #422): the summary written with each commit (ADR 0014)
is updated from the log-book rows that commit adds, not rebuilt from the
whole log book. A :class:`SummaryState` holds, for each day-block group
of one branch of one store, what the summary needs of its log book: each
stored file's epoch count and first and last epoch, the header positions,
the block index and each day's span. At a commit it reads only the rows
past those it knows, so a commit's summary costs the same on day 365 as
on day 1. Rows another run added (a commit rebased onto that run's
commits) are read the same way: the log book only grows at its end. The
rows come from :class:`~canvod.store_metadata.log_book.LogBooks`, one per
store and branch: the log books at the snapshot the commit builds on
(kept), then the commit's own rows (read, not kept).

The state is rebuilt from the whole log book, as :func:`summarize_root`
does, at a store's first commit in a process, and for a group whose log
book no longer starts with the rows the state knows: its columns changed,
it shrank, or its last known row differs (a table written again). It is
dropped when a commit fails, so the next commit starts from the store.

A store with a group written by appending (before day blocks), or with a
log book without row numbers (``index``) or with a stored row without a
first or last epoch, is summarized in full.
"""

from __future__ import annotations

import threading
from collections import Counter, defaultdict
from collections.abc import Collection, Hashable, Mapping
from pathlib import Path
from typing import Any

import icechunk
import numpy as np
import polars as pl
import zarr

from .layout import DAY_BLOCK_INDEX_ATTR, is_day_block_group
from .location import StoreLocation, store_location
from .log_book import LogBooks
from .summary import (
    _array,
    _groups_by_receiver,
    _header_positions,
    _key_array,
    _observation_groups,
    _summary_updates,
    summarize_root,
)

_NS_PER_DAY = 86_400 * 10**9
_NAT = np.iinfo(np.int64).min

# A stored file: epochs with data, first and last epoch (ns since 1970).
_Entry = tuple[int, int, int]
# A day's cadence (s) and first and last epoch with data (ns).
_Span = tuple[float, int, int]


class _FullRebuildError(Exception):
    """The store holds something the state does not follow: summarize in full."""


class _Rows:
    """New log-book rows, read like a whole log book (``_LogBook``)."""

    def __init__(self, frame: pl.DataFrame) -> None:
        self._frame = frame
        self.columns = set(frame.columns)
        self._values: dict[str, np.ndarray] = {}

    def __contains__(self, column: str) -> bool:
        return column in self.columns

    def __getitem__(self, column: str) -> np.ndarray:
        if column not in self._values:
            self._values[column] = self.read(column)
        return self._values[column]

    def read(self, column: str) -> np.ndarray:
        values = self._frame[column]
        if values.dtype == pl.Utf8:
            return np.asarray(values.to_list(), dtype=object)
        return values.to_numpy()


class _Group:
    """What the summary needs of one day-block group's log book."""

    def __init__(self, path: str) -> None:
        self.path = path
        self.columns: frozenset[str] = frozenset()
        self.rows = 0
        self.last_row = pl.DataFrame()
        self.files: dict[str, _Entry] = {}
        self.positions: dict[str, tuple[float, float, float]] = {}
        self.index: dict[int, tuple[int, int]] = {}
        self.day_keys: dict[int, set[str]] = defaultdict(set)
        self.days: dict[int, _Span] = {}

    @property
    def file_count(self) -> int | None:
        """Distinct stored files, as ``_stored_file_count`` counts them."""
        if not {"rinex_hash", "action"} <= self.columns:
            return None
        return len(self.files)

    def refresh(
        self, group: zarr.Group, frame: pl.DataFrame | None
    ) -> tuple[bool, set[str], set[int], dict[str, tuple[float, float, float]]]:
        """Take the rows of ``frame`` (the group's log book) past those known.

        Returns whether the group was read again from its first row, and
        the keys, days and header positions the new rows changed.
        """
        if frame is None:
            _key_array(None, group.path)  # raises: no log book
        assert frame is not None
        if "index" not in frame.columns:
            raise _FullRebuildError
        columns = frozenset(frame.columns)
        known = (
            columns == self.columns
            and frame.height >= self.rows
            and (
                self.rows == 0
                # By name: reads may give the columns in another order.
                or frame.slice(self.rows - 1, 1)
                .select(self.last_row.columns)
                .equals(self.last_row)
            )
        )
        again = not known and self.rows > 0
        if not known:
            self.__init__(self.path)  # type: ignore[misc]
            self.columns = columns
        self._read_index(group)
        if frame.height == self.rows:
            return again, set(), set(), {}
        book = _Rows(frame.slice(self.rows))
        keys, days = self._apply(book)
        positions = (
            _header_positions(book)
            if {"rinex_hash", "action", "attrs"} <= columns
            else {}
        )
        self.positions.update(positions)
        self.rows = frame.height
        self.last_row = frame.slice(frame.height - 1, 1)
        return again, keys, days, positions

    def _read_index(self, group: zarr.Group) -> None:
        """Add the days new to the block index (a day's entry never changes)."""
        index = group.attrs.get(DAY_BLOCK_INDEX_ATTR)
        if not isinstance(index, Mapping):
            msg = (
                f"Day-block group {group.path} has no block index; its cadences "
                "cannot be summarized"
            )
            raise ValueError(msg)
        if len(index) == len(self.index):
            return
        for day, entry in index.items():
            number = int(np.datetime64(str(day), "D").astype(np.int64))
            if number not in self.index:
                assert isinstance(entry, Mapping)
                cadence_ns, slots = entry["cadence_ns"], entry["slots"]
                assert isinstance(cadence_ns, int) and isinstance(slots, int)
                self.index[number] = (cadence_ns, slots)

    def _apply(self, book: _Rows) -> tuple[set[str], set[int]]:
        """Take the stored rows of ``book``; return the keys and days changed."""
        keys = _key_array(book, self.path)
        if not {"end", "epochs"} <= book.columns:
            msg = (
                f"Day-block group {self.path} has no log book with the columns "
                "end, epochs; its epoch count cannot be summarized"
            )
            raise ValueError(msg)
        stored = np.flatnonzero(keys != None)  # noqa: E711 (element-wise)
        counts = np.asarray(book["epochs"])[stored].astype(np.int64)
        starts = np.asarray(book["start"])[stored].astype("M8[ns]").view(np.int64)
        ends = np.asarray(book["end"])[stored].astype("M8[ns]").view(np.int64)
        negative = np.flatnonzero(counts < 0)
        if negative.size:
            msg = (
                f"Log book of day-block group {self.path} has a stored row "
                f"without an epoch count ({keys[stored][negative[0]]})"
            )
            raise ValueError(msg)
        if (starts == _NAT).any() or (ends == _NAT).any():
            raise _FullRebuildError
        changed_keys: set[str] = set()
        changed_days: set[int] = set()
        for key, count, start, end in zip(
            keys[stored].tolist(), counts.tolist(), starts.tolist(), ends.tolist(),
            strict=True,
        ):  # fmt: skip
            old = self.files.get(key)
            new = (count, start, end)
            if old == new:
                continue
            for entry, add in ((old, False), (new, True)):
                if entry is None or entry[0] == 0:
                    continue
                for day in _covered_days(entry):
                    if add:
                        self.day_keys[day].add(key)
                    else:
                        self.day_keys[day].discard(key)
                    changed_days.add(day)
            self.files[key] = new
            changed_keys.add(key)
        for day in changed_days:
            self._day_span(day)
        return changed_keys, changed_days

    def _day_span(self, day: int) -> None:
        """Recompute one day's span from the files covering it (``_block_days``)."""
        keys = self.day_keys.get(day)
        if not keys:
            self.day_keys.pop(day, None)
            self.days.pop(day, None)
            return
        if day not in self.index:
            raise KeyError(np.datetime64(day, "D"))
        cadence_ns, slots = self.index[day]
        day_ns = day * _NS_PER_DAY
        last_slot = day_ns + (slots - 1) * cadence_ns
        first = min(max(self.files[k][1], day_ns) for k in keys)
        last = max(min(self.files[k][2], last_slot) for k in keys)
        self.days[day] = (cadence_ns / 1e9, first, last)


def _covered_days(entry: _Entry) -> range:
    """The days (since 1970) from a file's first epoch to its last."""
    first = entry[1] // _NS_PER_DAY
    return range(first, max(entry[2] // _NS_PER_DAY + 1, first))


class _Extremes:
    """A multiset of times with its least and greatest, kept as they change."""

    def __init__(self) -> None:
        self._count: Counter[int] = Counter()
        self._low: int | None = None
        self._high: int | None = None

    def add(self, t: int) -> None:
        self._count[t] += 1
        if self._low is not None and t < self._low:
            self._low = t
        if self._high is not None and t > self._high:
            self._high = t

    def remove(self, t: int) -> None:
        self._count[t] -= 1
        if not self._count[t]:
            del self._count[t]
            # Only when the least or greatest goes is the whole set read.
            if t == self._low:
                self._low = None
            if t == self._high:
                self._high = None

    def low(self) -> int:
        if self._low is None:
            self._low = min(self._count)
        return self._low

    def high(self) -> int:
        if self._high is None:
            self._high = max(self._count)
        return self._high

    def __bool__(self) -> bool:
        return bool(self._count)


class _Median:
    """The per-axis median of header positions, by file hash (``np.median``)."""

    def __init__(self) -> None:
        self.by_hash: dict[str, tuple[float, float, float]] = {}
        self._axes: tuple[Counter[float], ...] = (Counter(), Counter(), Counter())

    def set(self, file_hash: str, xyz: tuple[float, float, float]) -> None:
        old = self.by_hash.get(file_hash)
        if old == xyz:
            return
        for axis, value in enumerate(xyz):
            if old is not None:
                self._axes[axis][old[axis]] -= 1
                if not self._axes[axis][old[axis]]:
                    del self._axes[axis][old[axis]]
            self._axes[axis][value] += 1
        self.by_hash[file_hash] = xyz

    def value(self) -> list[float] | None:
        n = len(self.by_hash)
        if not n:
            return None
        return [_nth_mean(axis, (n - 1) // 2, n // 2) for axis in self._axes]


def _nth_mean(counts: Counter[float], i: int, j: int) -> float:
    """Mean of the i-th and j-th smallest values of a multiset."""
    found: dict[int, float] = {}
    seen = 0
    for value in sorted(counts):
        seen += counts[value]
        for k in (i, j):
            if k not in found and k < seen:
                found[k] = value
        if j in found:
            break
    return float(np.mean([found[i], found[j]]))


class _Scope:
    """Groups summarized together: the whole store, or one receiver's groups.

    A file stored in several of them counts once, from the last group in
    order that holds it (``_merged``).
    """

    def __init__(self, names: list[str]) -> None:
        self.names = names
        self.chosen: dict[str, _Entry] = {}
        self.total = 0
        self.times = _Extremes()
        self.days: dict[int, _Span] = {}
        self.positions = _Median()

    def update_key(self, key: str, groups: Mapping[str, _Group]) -> None:
        new = next(
            (
                groups[n].files[key]
                for n in reversed(self.names)
                if key in groups[n].files
            ),
            None,
        )
        old = self.chosen.get(key)
        if old == new:
            return
        if old is not None:
            self.total -= old[0]
            self.times.remove(old[1])
            self.times.remove(old[2])
        if new is not None:
            self.chosen[key] = new
            self.total += new[0]
            self.times.add(new[1])
            self.times.add(new[2])
        else:
            del self.chosen[key]

    def update_day(self, day: int, groups: Mapping[str, _Group]) -> None:
        spans = [groups[n].days[day] for n in self.names if day in groups[n].days]
        if not spans:
            self.days.pop(day, None)
            return
        cadence, first, last = spans[0]
        for c, f, la in spans[1:]:
            cadence, first, last = min(cadence, c), min(first, f), max(last, la)
        self.days[day] = (cadence, first, last)

    def coverage(
        self,
    ) -> tuple[int, np.datetime64, np.datetime64, dict[np.datetime64, Any]] | None:
        if not self.times:
            return None
        days = {
            np.datetime64(day, "D"): (
                cadence,
                np.datetime64(first, "ns"),
                np.datetime64(last, "ns"),
            )
            for day, (cadence, first, last) in self.days.items()
        }
        return (
            self.total,
            np.datetime64(self.times.low(), "ns"),
            np.datetime64(self.times.high(), "ns"),
            days,
        )


class SummaryState:
    """The summary's view of one branch of one store, kept across commits."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._log_books = LogBooks()
        self._groups: dict[str, _Group] = {}
        self._layout: tuple[Any, ...] | None = None
        self._scopes: dict[str | None, _Scope] = {}

    def reset(self) -> None:
        self._log_books = LogBooks()
        self._groups, self._layout, self._scopes = {}, None, {}

    def summarize(
        self,
        session: icechunk.Session,
        repo: icechunk.Repository,
        receivers: Mapping[str, str] | Collection[str] | None = None,
    ) -> dict[str, Any]:
        """The updates :func:`summarize_root` gives for ``session``'s data.

        ``session`` is the session about to be committed, rebased onto the
        branch tip; ``repo`` its repository. Reads only the log-book rows
        added since the last call; see the module docstring for when it
        reads a group in full.
        """
        root = zarr.open_group(session.store, mode="r")
        with self._lock:
            try:
                return self._summarize(root, receivers, session, repo)
            except _FullRebuildError:
                self.reset()
                return summarize_root(root, receivers)
            except BaseException:
                self.reset()
                raise

    def _summarize(
        self,
        root: zarr.Group,
        receivers: Mapping[str, str] | Collection[str] | None,
        session: icechunk.Session,
        repo: icechunk.Repository,
    ) -> dict[str, Any]:
        data_groups = _observation_groups(root)
        if not data_groups:
            self.reset()
            return {}
        if not all(is_day_block_group(g.attrs) for g in data_groups.values()):
            raise _FullRebuildError
        by_receiver = _groups_by_receiver(receivers, list(data_groups))
        layout = (
            tuple(data_groups),
            tuple(sorted((r, tuple(sorted(g))) for r, g in by_receiver.items())),
        )
        rebuild = layout != self._layout
        for gone in set(self._groups) - set(data_groups):
            del self._groups[gone]
        # The log books at the snapshot this commit builds on are kept; the
        # commit's own rows are read on top and not kept (LogBooks).
        base = repo.readonly_session(snapshot_id=session.snapshot_id)
        changes = []
        for name, group in data_groups.items():
            self._log_books.rows(base, name)
            frame = self._log_books.rows(session, name)
            state = self._groups.setdefault(name, _Group(group.path))
            again, keys, days, positions = state.refresh(group, frame)
            rebuild |= again
            changes.append((name, keys, days, positions))

        if rebuild:
            self._layout = layout
            self._scopes = {None: _Scope(list(data_groups))} | {
                r: _Scope(sorted(g)) for r, g in sorted(by_receiver.items()) if g
            }
            changes = [
                (name, set(g.files), set(g.days), g.positions)
                for name, g in self._groups.items()
            ]
        for scope in self._scopes.values():
            for name, keys, days, positions in changes:
                if name not in scope.names:
                    continue
                for key in keys:
                    scope.update_key(key, self._groups)
                for day in days:
                    scope.update_day(day, self._groups)
                for file_hash, xyz in positions.items():
                    scope.positions.set(file_hash, xyz)

        coverage = self._scopes[None].coverage()
        if coverage is None:
            return {}
        facts = {name: _group_facts(group) for name, group in data_groups.items()}
        own = {}
        for receiver, scope in self._scopes.items():
            if receiver is None:
                continue
            r_coverage = scope.coverage()
            if r_coverage is not None:
                own[receiver] = (scope.names, r_coverage, scope.positions.value())
        file_counts = [
            n for n in (g.file_count for g in self._groups.values()) if n is not None
        ]
        return _summary_updates(facts, coverage, own, file_counts)


def _group_facts(group: zarr.Group) -> dict[str, Any]:
    """Sids, systems and variables of a group: small, read at every commit."""
    variables = sorted(name for name, arr in group.arrays() if len(arr.shape) >= 2)
    sids = np.asarray(_array(group, "sid")[...]) if "sid" in group else np.array([])
    systems = (
        {str(s) for s in np.asarray(_array(group, "system")[...])}
        if "system" in group
        else set()
    )
    return {"sids": {str(s) for s in sids}, "variables": variables, "systems": systems}


_states: dict[tuple[Hashable, str], SummaryState] = {}
_states_guard = threading.Lock()


def _key(store_path: StoreLocation | Path | str) -> Hashable:
    """One key per store, however its path is written."""
    location = store_location(store_path)
    local = location.local_path
    return local.resolve() if local is not None else location


def summary_state(store_path: StoreLocation | Path | str, branch: str) -> SummaryState:
    """The summary state of ``branch`` of the store in this process."""
    with _states_guard:
        return _states.setdefault((_key(store_path), branch), SummaryState())


def forget_summary_state(store_path: StoreLocation | Path | str, branch: str) -> None:
    """Drop the state, so the next commit reads the store's log books again."""
    with _states_guard:
        _states.pop((_key(store_path), branch), None)


__all__ = ["SummaryState", "forget_summary_state", "summary_state"]
