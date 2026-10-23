"""The VOD phase: the VOD of whole days in the worker pool, one commit per unit.

ADR 0021. A task computes the VOD of one analysis pair on one day
(:func:`compute_vod_into_fork`): it reads the day of the canopy and the
reference group from a committed snapshot of the GNSS store
(:func:`~canvod.store.day_blocks.load_group` reads only the day's blocks, so
a day takes the same time however many days are stored) and writes the
result into the day's block of the VOD group, in its own fork of one session
of the VOD store. The main process merges the forks of a unit and commits
once (:meth:`~canvod.store.store.MyIcechunkStore.commit_vod_days`).

A day block is padded to whole epoch chunks (#376) and a task writes one
day of one group, so no two forks write one chunk (see
:mod:`canvodpy.orchestrator.forked_writes`). A VOD group that does not exist
yet is created by the commit from its first day: its tasks return their
results instead of writing them.

The main process plans a unit from the log books before any data are read
(:func:`plan_vod_unit`): the GNSS files behind each day and their
preprocessing, and the days whose VOD is stored from the same files, which
get no task. A day without data in a group of its pair gets no VOD and is
reported (:attr:`VodUnitReport.missing`).
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import Future
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import polars as pl
import structlog
import xarray as xr
import zarr
from icechunk.session import ForkSession, Session

from canvod.config.models import PREPROCESSING_ATTR, vod_preprocessing_record
from canvod.readers.base import validate_vod_dataset
from canvod.store.day_blocks import (
    DayBlock,
    clear_day_block,
    day_blocks,
    drop_empty_slots,
    holds_day_blocks,
    load_group,
    stored_epoch_chunk,
    write_file_region,
)
from canvod.store.store import (
    MyIcechunkStore,
    VodDayWrite,
    VodWriteItem,
    normalize_encodings,
)
from canvod.store_metadata.layout import LayoutError
from canvod.utils.tools import get_version_from_pyproject
from canvodpy.orchestrator.resources import run_measured

_DAY = np.timedelta64(1, "D")
_NS = np.timedelta64(1, "ns")

#: Most days of a unit of the VOD phase run alone (``canvodpy vod``). A unit
#: holds in the main process only the results of a group's first days; a
#: lost conflict or a crash loses at most one unit.
VOD_UNIT_DAYS = 31


@dataclass(frozen=True)
class VodPair:
    """One VOD analysis pair, as the phase computes it."""

    analysis: str
    canopy_receiver: str
    reference_receiver: str
    canopy_group: str
    reference_group: str


@dataclass(frozen=True)
class VodTask:
    """One analysis pair's day, as a worker computes and writes it.

    Attributes
    ----------
    group
        The VOD store group, ``{calculator}/{analysis}``.
    gnss
        A read-only session of the GNSS store at the unit's snapshot.
    block
        The day's block in ``group``; ``None`` when the group does not exist
        yet, so the worker returns the result for the commit to write.
    chunks
        The epoch chunks of ``block``, the only ones the task may write.
    """

    pair: VodPair
    group: str
    day: np.datetime64
    gnss: Session
    calculator: str
    calculator_params: Mapping[str, Any]
    store_delta_snr: bool
    store_radial_diff: bool
    block: DayBlock | None
    chunks: frozenset[int]


@dataclass
class VodDayResult:
    """What a task did with its day.

    ``missing`` says why the day has no VOD (a group of the pair has no data
    on the day); nothing was written then. ``dataset`` holds the result when
    the task had no block to write it into.
    """

    task: VodTask
    fork: ForkSession | None
    epochs: int = 0
    start: np.datetime64 | None = None
    end: np.datetime64 | None = None
    attrs: dict[str, Any] = field(default_factory=dict)
    dataset: xr.Dataset | None = None
    missing: str | None = None
    seconds: float = 0.0


@dataclass
class VodDayPlan:
    """One analysis pair's day to compute, with its provenance."""

    pair: VodPair
    day: np.datetime64
    cadence_s: float
    action: str  # "write" | "append" | "overwrite"
    source_file_hashes: dict[str, str]
    preprocessing: str


@dataclass
class VodUnitReport:
    """What the phase did with the days of a unit, per analysis.

    ``stored`` lists the days whose VOD the store held from the same GNSS
    files, so they were not computed again; ``missing`` the days without
    VOD and why.
    """

    written: dict[str, list[np.datetime64]] = field(default_factory=dict)
    stored: dict[str, list[np.datetime64]] = field(default_factory=dict)
    missing: dict[str, list[tuple[np.datetime64, str]]] = field(default_factory=dict)
    snapshot_id: str | None = None

    def extend(self, other: VodUnitReport) -> None:
        """Add the days of ``other``, the report of a later unit."""
        for analysis, days in other.written.items():
            self.written.setdefault(analysis, []).extend(days)
        for analysis, days in other.stored.items():
            self.stored.setdefault(analysis, []).extend(days)
        for analysis, missing in other.missing.items():
            self.missing.setdefault(analysis, []).extend(missing)
        self.snapshot_id = other.snapshot_id or self.snapshot_id


def _day_slice(day: np.datetime64) -> slice:
    """The epochs of ``day``, as a label-based selection."""
    start = np.datetime64(day, "D").astype("M8[ns]")
    return slice(start, start + _DAY - _NS)


def compute_vod_into_fork(fork: ForkSession | None, task: VodTask) -> VodDayResult:
    """Compute the VOD of the task's day and write it into ``fork``.

    Runs in a worker process. The day of the canopy and the reference group
    is read from ``task.gnss`` without its empty slots, the two are aligned
    on their shared epochs, and the result replaces the day's block of the
    VOD group (the block is emptied first). Without a block, the result is
    returned for the commit to write.
    """
    from canvodpy.vod_computer import compute_vod

    t_start = time.perf_counter()
    pair = task.pair
    result = VodDayResult(task=task, fork=fork)
    window = _day_slice(task.day)
    canopy = load_group(
        task.gnss.store, pair.canopy_group, time_slice=window, drop_empty=True
    )
    sky = load_group(
        task.gnss.store, pair.reference_group, time_slice=window, drop_empty=True
    )
    empty = [
        group
        for group, ds in ((pair.canopy_group, canopy), (pair.reference_group, sky))
        if not ds.sizes.get("epoch", 0)
    ]
    if empty:
        result.missing = f"no data in {' and '.join(empty)}"
        return result
    canopy, sky = xr.align(canopy.load(), sky.load(), join="inner")
    if not canopy.sizes.get("epoch", 0):
        result.missing = (
            f"no epoch shared by {pair.canopy_group} and {pair.reference_group}"
        )
        return result

    vod = compute_vod(
        canopy,
        sky,
        analysis_name=pair.analysis,
        canopy_receiver=pair.canopy_receiver,
        reference_receiver=pair.reference_receiver,
        calculator=task.calculator,
        calculator_params=task.calculator_params,
        store_delta_snr=task.store_delta_snr,
        store_radial_diff=task.store_radial_diff,
    )
    validate_vod_dataset(vod)
    vod = vod.copy(deep=False)
    for name in vod.variables:
        vod[name].encoding = {}
    vod = normalize_encodings(vod)

    result.epochs = int(drop_empty_slots(vod, task.group).sizes["epoch"])
    result.start = np.datetime64(vod.epoch.values.min(), "ns")
    result.end = np.datetime64(vod.epoch.values.max(), "ns")
    result.attrs = dict(vod.attrs)
    if task.block is None:
        result.dataset = vod
    elif fork is not None:
        clear_day_block(fork, task.group, task.block)
        write_file_region(
            fork,
            task.group,
            vod,
            blocks={task.block.day: task.block},
            chunks=task.chunks,
        )
    result.seconds = time.perf_counter() - t_start
    return result


def _gnss_cadences(
    gnss: Session, pair: VodPair, days: Sequence[np.datetime64]
) -> tuple[dict[np.datetime64, float], dict[np.datetime64, str]]:
    """The VOD cadence of each day, and why the other days have none.

    A VOD epoch is an epoch of both groups, so the coarser of their two
    cadences gives every VOD epoch of the day a slot (as
    :meth:`~canvodpy.vod_computer.VodComputer._gnss_cadences`).

    Raises
    ------
    LayoutError
        If a group of the pair was written by appending.
    """
    blocks: dict[str, dict[np.datetime64, DayBlock]] = {}
    for group in (pair.canopy_group, pair.reference_group):
        if group not in zarr.open_group(gnss.store, mode="r"):
            blocks[group] = {}
            continue
        if not holds_day_blocks(gnss.store, group):
            msg = (
                f"GNSS group '{group}' was written by appending, so the VOD "
                f"of {pair.analysis} has no day blocks to follow. Move the "
                "GNSS store to day blocks first (canvodpy store migrate-layout)."
            )
            raise LayoutError(msg)
        blocks[group] = day_blocks(gnss.store, group)
    cadences: dict[np.datetime64, float] = {}
    missing: dict[np.datetime64, str] = {}
    for day in days:
        without = [g for g, b in blocks.items() if day not in b]
        if without:
            missing[day] = f"no data in {' and '.join(without)}"
            continue
        cadences[day] = max(b[day].cadence_s for b in blocks.values())
    return cadences, missing


def _overlapping(rows: pl.DataFrame | None, day: np.datetime64) -> pl.DataFrame:
    """The log-book rows whose epochs reach into ``day``."""
    if rows is None or rows.is_empty():
        return pl.DataFrame()
    window = _day_slice(day)
    return rows.filter(
        (pl.col("start").cast(pl.Datetime("ns")) <= window.stop)
        & (pl.col("end").cast(pl.Datetime("ns")) >= window.start)
    )


def plan_vod_unit(
    gnss_store: MyIcechunkStore,
    vod_store: MyIcechunkStore,
    gnss: Session,
    pairs: Sequence[VodPair],
    days: Sequence[np.datetime64],
    calculator: str,
) -> tuple[list[VodDayPlan], VodUnitReport]:
    """Plan a unit's days of each pair from the log books; no data are read.

    The GNSS files behind a day are those whose log-book rows reach into
    it. A day whose VOD the store holds from the same files gets no plan
    (:attr:`VodUnitReport.stored`); a day the VOD store holds from other
    files is written again (``overwrite``).

    Raises
    ------
    PreprocessingMismatchError
        If canopy and reference data of a day were preprocessed differently.
    LayoutError
        If a GNSS group of a pair was written by appending.
    """
    report = VodUnitReport()
    plans: list[VodDayPlan] = []
    vod_session = vod_store.repo.readonly_session("main")
    for pair in pairs:
        group = f"{calculator}/{pair.analysis}"
        cadences, missing = _gnss_cadences(gnss, pair, days)
        if missing:
            report.missing[pair.analysis] = sorted(missing.items())
        vod_rows = vod_store.log_books.rows(vod_session, group)
        exists = vod_rows is not None
        for day, cadence_s in cadences.items():
            window = _day_slice(day)
            hashes = {
                pair.canopy_receiver: ",".join(
                    gnss_store.source_file_hashes(
                        pair.canopy_group, window.start, window.stop
                    )
                ),
                pair.reference_receiver: ",".join(
                    gnss_store.source_file_hashes(
                        pair.reference_group, window.start, window.stop
                    )
                ),
            }
            stored = _overlapping(vod_rows, day)
            if not stored.is_empty():
                key = json.dumps(hashes, sort_keys=True)
                if (stored["source_file_hashes"] == key).any():
                    report.stored.setdefault(pair.analysis, []).append(day)
                    continue
            record = vod_preprocessing_record(
                {
                    pair.canopy_receiver: gnss_store.preprocessing_records(
                        pair.canopy_group, window.start, window.stop
                    ),
                    pair.reference_receiver: gnss_store.preprocessing_records(
                        pair.reference_group, window.start, window.stop
                    ),
                }
            )
            plans.append(
                VodDayPlan(
                    pair=pair,
                    day=day,
                    cadence_s=cadence_s,
                    action=(
                        "overwrite"
                        if not stored.is_empty()
                        else ("append" if exists else "write")
                    ),
                    source_file_hashes=hashes,
                    preprocessing=record,
                )
            )
    return plans, report


@dataclass
class VodPhase:
    """The VOD phase of one site: units of days, in a worker pool.

    ``submit`` puts a call into the worker pool, as
    ``concurrent.futures.Executor.submit`` does.
    """

    gnss_store: MyIcechunkStore
    vod_store: MyIcechunkStore
    pairs: Sequence[VodPair]
    calculator: str
    calculator_params: Mapping[str, Any]
    store_delta_snr: bool
    store_radial_diff: bool
    submit: Callable[..., Future]
    log: Any = field(default_factory=lambda: structlog.get_logger(__name__))

    def run_unit(self, days: Sequence[np.datetime64]) -> VodUnitReport:
        """Compute the VOD of a unit's days for every pair; commit once.

        The VOD store exists (its metadata are ensured before). Days of a
        pair are planned (:func:`plan_vod_unit`), the existing groups get
        blocks for them in one small commit, and one task per pair and day
        runs in the pool. The forks are merged and committed once.
        """
        from canvod.utils.logging import record_stage_timing

        days = [np.datetime64(d, "D") for d in days]
        vod_store = self.vod_store
        gnss = self.gnss_store.repo.readonly_session("main")
        plans, report = plan_vod_unit(
            self.gnss_store, vod_store, gnss, self.pairs, days, self.calculator
        )
        for analysis, missing in report.missing.items():
            for day, reason in missing:
                self.log.warning(
                    "vod_day_missing",
                    analysis=analysis,
                    date_key=_yyyydoy(day),
                    reason=reason,
                )
        if not plans:
            return report

        groups = {f"{self.calculator}/{p.pair.analysis}" for p in plans}
        existing = {g for g in groups if vod_store.group_exists(g)}
        growth: dict[str, dict[np.datetime64, float]] = {}
        for plan in plans:
            group = f"{self.calculator}/{plan.pair.analysis}"
            if group in existing:
                growth.setdefault(group, {})[plan.day] = plan.cadence_s
        if growth:
            t_growth = time.perf_counter()
            vod_store.grow_day_blocks(
                growth,
                message=(
                    f"[v{get_version_from_pyproject()}] VOD day blocks for "
                    f"{_yyyydoy(days[0])}..{_yyyydoy(days[-1])}"
                ),
            )
            record_stage_timing("vod_day_block_growth", time.perf_counter() - t_growth)

        session = vod_store.repo.writable_session("main")
        blocks = {g: day_blocks(session.store, g) for g in existing}
        chunk_of = {g: stored_epoch_chunk(session.store, g) for g in existing}
        futures: list[tuple[VodDayPlan, Future]] = []
        for plan in plans:
            group = f"{self.calculator}/{plan.pair.analysis}"
            block = blocks[group][plan.day] if group in existing else None
            chunks = (
                frozenset()
                if block is None
                else frozenset(
                    range(block.start // chunk_of[group], block.stop // chunk_of[group])
                )
            )
            task = VodTask(
                pair=plan.pair,
                group=group,
                day=plan.day,
                gnss=gnss,
                calculator=self.calculator,
                calculator_params=self.calculator_params,
                store_delta_snr=self.store_delta_snr,
                store_radial_diff=self.store_radial_diff,
                block=block,
                chunks=chunks,
            )
            fork = None if block is None else session.fork()
            # The input is read from the store, not from files: its size is
            # not known before the task runs, so it is logged as 0.
            futures.append(
                (plan, self.submit(run_measured, 0, compute_vod_into_fork, fork, task))
            )

        writes: list[VodDayWrite] = []
        forks: list[ForkSession] = []
        gnss_path = str(self.gnss_store.store_path)
        for plan, future in futures:
            result = future.result()
            analysis = plan.pair.analysis
            if result.missing is not None:
                report.missing.setdefault(analysis, []).append(
                    (plan.day, result.missing)
                )
                self.log.warning(
                    "vod_day_missing",
                    analysis=analysis,
                    date_key=_yyyydoy(plan.day),
                    reason=result.missing,
                )
                continue
            record_stage_timing(
                "vod_calc",
                result.seconds,
                date_key=_yyyydoy(plan.day),
                calculator=self.calculator,
                analysis=analysis,
            )
            if result.fork is not None:
                forks.append(result.fork)
            attrs = {**result.attrs, PREPROCESSING_ATTR: plan.preprocessing}
            dataset = (
                xr.Dataset(attrs=attrs)
                if result.dataset is None
                else result.dataset.assign_attrs(attrs)
            )
            writes.append(
                VodDayWrite(
                    item=VodWriteItem(
                        group_name=result.task.group,
                        dataset=dataset,
                        source_file_hashes=plan.source_file_hashes,
                        source_gnss_stores={
                            plan.pair.canopy_receiver: gnss_path,
                            plan.pair.reference_receiver: gnss_path,
                        },
                        calculator_name=self.calculator,
                        calculator_params=dict(self.calculator_params),
                        commit_message=f"VOD {analysis} {_yyyydoy(plan.day)}",
                        cadences={plan.day: plan.cadence_s},
                    ),
                    action=plan.action,
                    start=result.start,
                    end=result.end,
                    epochs=result.epochs,
                    in_fork=result.dataset is None,
                )
            )
            report.written.setdefault(analysis, []).append(plan.day)

        t_commit = time.perf_counter()
        report.snapshot_id = vod_store.commit_vod_days(session, forks, writes)
        record_stage_timing(
            "vod_store",
            time.perf_counter() - t_commit,
            days=len({plan.day for plan in plans}),
            calculator=self.calculator,
        )
        self.log.info(
            "vod_unit_committed",
            first=_yyyydoy(days[0]),
            last=_yyyydoy(days[-1]),
            written=sum(len(d) for d in report.written.values()),
            stored=sum(len(d) for d in report.stored.values()),
            missing=sum(len(d) for d in report.missing.values()),
            snapshot_id=report.snapshot_id,
        )
        return report


def _yyyydoy(day: np.datetime64) -> str:
    """``YYYYDOY`` of ``day``."""
    import pandas as pd

    stamp = pd.Timestamp(day)
    return f"{stamp.year}{stamp.dayofyear:03d}"


def units(days: Sequence[np.datetime64], unit_days: int) -> list[list[np.datetime64]]:
    """``days`` in time order, in units of at most ``unit_days`` days."""
    ordered = sorted({np.datetime64(d, "D") for d in days})
    return [ordered[i : i + unit_days] for i in range(0, len(ordered), unit_days)]
