"""Forked writes of day blocks: workers write regions, one thread commits.

A day of a store made of day blocks (ADR 0016) is written by tasks in the
worker pool. Each task reads its files and writes their regions into its
own fork of one session of the day (:func:`write_files_into_fork`); the
writer thread merges the forks of all receivers of the day and commits once
(``RinexDataProcessor._commit_forked_day``).

Icechunk merges forks chunk by chunk: of two forks that wrote one epoch
chunk, the one merged last replaces the chunk whole and the other's data in
it are lost without an error. A task therefore owns whole chunks. Files
whose names put them into a shared chunk (e.g. six 15-minute files at 30 s
in one chunk of 180 epochs) go to one task (:func:`chunk_groups`), with
aggregation or without. A file whose epochs reach beyond its task's chunks
is not written by the worker; the writer thread writes it into the merged
session, where it cannot replace a fork's chunk.
"""

from __future__ import annotations

import time
from collections.abc import Hashable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import structlog
import xarray as xr
from icechunk.session import ForkSession, Session

from canvod.config.models import PreprocessingConfig
from canvod.ops import preprocess_files
from canvod.store.day_blocks import (
    ChunkOwnershipError,
    DayBlock,
    write_file_region,
)
from canvod.store.store import cleanse_dataset_attrs, normalize_encodings
from canvod.store_metadata.layout import LayoutError

#: Log-book actions of a file a fork wrote, or the writer thread wrote.
WRITTEN, OVERWRITTEN, SKIPPED = "written", "overwritten", "skipped"


@dataclass(frozen=True)
class ForkTask:
    """The files one task reads and writes into its fork, with what it needs.

    Attributes
    ----------
    date_key
        The processing day, ``YYYYDOY``.
    file_tasks
        The task descriptors of ``prepare_batch_tasks`` for the files; the
        last element of each marks a reference fan-out task.
    groups
        The store groups the files are written to: one receiver, or every
        pairing of a reference receiver.
    chunks
        The epoch chunks of each group the task owns.
    blocks
        The day blocks of each group the files may reach (their day and
        the next), so the worker does not read the epoch axis.
    stored_hashes
        Each group's file hashes in its log book around this day; a file
        with one of them is skipped with ``gnss_store_strategy: skip`` and
        written again otherwise.
    strategy
        ``processing.storage.gnss_store_strategy``.
    preprocessing
        ``processing.preprocessing``, applied to the task's files together.
    canonical_names
        The canonical canVOD name of each file.
    keep_sbf_obs
        Whether to return the files' ``sbf_obs`` for the writer to store.
    """

    date_key: str
    file_tasks: tuple[tuple, ...]
    groups: tuple[str, ...]
    chunks: Mapping[str, frozenset[int]]
    blocks: Mapping[str, Mapping[np.datetime64, DayBlock]]
    stored_hashes: Mapping[str, frozenset[str]]
    strategy: str
    preprocessing: PreprocessingConfig | None
    canonical_names: Mapping[Path, str]
    keep_sbf_obs: bool


@dataclass
class FileNumbers:
    """What a task did with one file in one group, for its log-book row.

    ``epochs`` counts the epochs written (-1 if the file was skipped).
    ``deferred`` holds the file's data when the writer thread must write
    it (its epochs reach beyond the task's chunks or days); ``epochs`` is
    then filled in by the writer.
    """

    group: str
    fname: Path
    rinex_hash: str
    action: str
    exists: bool
    start: np.datetime64
    end: np.datetime64
    epochs: int
    n_sids: int
    nbytes: int
    attrs: dict[str, Any]
    canonical_name: str
    seconds: float
    sbf_obs: xr.Dataset | None = None
    deferred: xr.Dataset | None = None


@dataclass
class ForkResult:
    """A task's fork and the numbers of its files.

    ``failed`` lists ``(group, file name, error)`` of files that could not
    be read or written; they get no log-book row, so the next run tries
    them again.
    """

    task: ForkTask
    fork: ForkSession
    files: list[FileNumbers] = field(default_factory=list)
    failed: list[tuple[str, str, str]] = field(default_factory=list)


@dataclass
class ForkedDay:
    """One day of one store, written by forks of one session.

    ``tasks`` pairs each task with its fork.
    """

    date_key: str
    date: date
    session: Session
    tasks: list[tuple[ForkTask, ForkSession]]


def chunk_groups[K, C: Hashable](
    chunks_of: Sequence[tuple[K, set[C]]],
) -> list[tuple[list[K], set[C]]]:
    """Group items whose epoch chunks overlap, so each chunk has one owner.

    ``chunks_of`` pairs each item (a file) with the chunks its name gives.
    Items sharing a chunk, directly or through other items, form one
    group; the result gives each group's items, in the given order, and
    its chunks.
    """
    parent = list(range(len(chunks_of)))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    owner: dict[C, int] = {}
    for i, (_, chunks) in enumerate(chunks_of):
        for chunk in chunks:
            if chunk in owner:
                parent[root(i)] = root(owner[chunk])
            else:
                owner[chunk] = i
    members: dict[int, list[int]] = {}
    for i in range(len(chunks_of)):
        members.setdefault(root(i), []).append(i)
    return [
        (
            [chunks_of[i][0] for i in indices],
            set().union(*(chunks_of[i][1] for i in indices)),
        )
        for indices in members.values()
    ]


def _read(file_task: tuple, groups: Sequence[str]) -> tuple[Path, dict, dict]:
    """Read one file as the run's task would: its dataset per group and aux."""
    from canvodpy.orchestrator.processor import (
        preprocess_reference_with_hermite_aux_fanout,
        preprocess_with_hermite_aux,
    )

    args, is_fanout = file_task[:-1], file_task[-1]
    if is_fanout:
        fname, by_group, aux, _ = preprocess_reference_with_hermite_aux_fanout(*args)
        return fname, {g: by_group[g] for g in groups if g in by_group}, aux
    fname, ds, aux, _ = preprocess_with_hermite_aux(*args)
    return fname, {groups[0]: ds}, aux


def write_files_into_fork(fork: ForkSession, task: ForkTask) -> ForkResult:
    """Read the task's files and write their regions into ``fork``.

    Runs in a worker process. Files are read, preprocessed together per
    group (``processing.preprocessing``), and written into the slots of
    their day blocks, unless already stored with ``gnss_store_strategy:
    skip``. A file whose slots reach beyond the task's chunks or blocks is
    returned for the writer thread to write (``FileNumbers.deferred``). A
    file that fails is logged and listed in ``ForkResult.failed``.
    """
    from canvodpy.orchestrator.processor import (
        _warn_if_epoch_count_differs_from_name,
        _warn_if_name_disagrees_with_data,
    )

    log = structlog.get_logger(__name__)
    result = ForkResult(task=task, fork=fork)
    parts: dict[str, list[tuple[Path, xr.Dataset]]] = {g: [] for g in task.groups}
    aux_by_file: dict[Path, dict[str, xr.Dataset]] = {}
    for file_task in task.file_tasks:
        fname = Path(file_task[0])
        try:
            fname, by_group, aux = _read(file_task, task.groups)
        except Exception as exc:
            log.exception("task_failed", date=task.date_key, file=fname.name)
            result.failed.extend((g, fname.name, repr(exc)) for g in task.groups)
            continue
        aux_by_file[fname] = aux or {}
        for group, ds in by_group.items():
            canonical = task.canonical_names.get(fname, "")
            _warn_if_epoch_count_differs_from_name(log, fname, canonical, ds)
            parts[group].append((fname, ds))

    for group, group_parts in parts.items():
        if not group_parts:
            continue
        try:
            augmented = preprocess_files(
                sorted(group_parts, key=lambda part: part[0].name),
                task.preprocessing,
            )
        except Exception as exc:
            log.exception("preprocessing_failed", date=task.date_key, group=group)
            result.failed.extend((group, f.name, repr(exc)) for f, _ in group_parts)
            continue
        for fname, ds in augmented:
            numbers = _write_one(fork, task, group, fname, ds, log)
            if numbers is None:
                continue
            if isinstance(numbers, tuple):
                result.failed.append(numbers)
                continue
            canonical = numbers.canonical_name
            _warn_if_name_disagrees_with_data(log, fname, canonical, ds)
            if task.keep_sbf_obs and numbers.action != SKIPPED:
                numbers.sbf_obs = aux_by_file.get(fname, {}).get("sbf_obs")
            result.files.append(numbers)
    return result


def _write_one(
    fork: ForkSession,
    task: ForkTask,
    group: str,
    fname: Path,
    ds: xr.Dataset,
    log: Any,
) -> FileNumbers | tuple[str, str, str] | None:
    """Write one file into ``fork``; its numbers, a failure, or ``None``."""
    rinex_hash = ds.attrs.get("File Hash")
    if not rinex_hash:
        log.debug("no_file_hash", file=fname.name, group=group)
        return None
    exists = rinex_hash in task.stored_hashes.get(group, frozenset())
    numbers = FileNumbers(
        group=group,
        fname=fname,
        rinex_hash=str(rinex_hash),
        action=SKIPPED,
        exists=exists,
        start=np.datetime64(ds.epoch.min().values, "ns"),
        end=np.datetime64(ds.epoch.max().values, "ns"),
        epochs=-1,
        n_sids=int(ds.sizes.get("sid", 0)),
        nbytes=int(ds.nbytes),
        attrs=dict(ds.attrs),
        canonical_name=ds.attrs.get("canonical_name")
        or task.canonical_names.get(fname, ""),
        seconds=0.0,
    )
    if exists and task.strategy == "skip":
        return numbers
    numbers.action = OVERWRITTEN if exists else WRITTEN
    clean = normalize_encodings(cleanse_dataset_attrs(ds))
    numbers.attrs = dict(clean.attrs)
    t_file = time.perf_counter()
    try:
        region = write_file_region(
            fork,
            group,
            clean,
            blocks=task.blocks.get(group),
            chunks=task.chunks.get(group, frozenset()),
        )
    except ChunkOwnershipError, LayoutError:
        # Beyond the task's chunks or days: the writer thread writes it
        # into the merged session (see the module docstring).
        log.info("file_write_deferred", file=fname.name, group=group)
        numbers.deferred = clean
        return numbers
    except (OSError, RuntimeError, ValueError) as exc:  # fmt: skip
        log.exception("file_write_failed", file=fname.name, group=group)
        return (group, fname.name, repr(exc))
    numbers.epochs = region.epochs
    numbers.seconds = time.perf_counter() - t_file
    return numbers
