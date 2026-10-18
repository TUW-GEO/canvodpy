"""The memory budget of a run: how many workers and days per unit fit.

``processing.params.max_memory_gb`` is the budget; without it, the memory
available when the run starts. The budget holds the main process and the
workers:

- The main process holds what it holds when the run starts, plus the data
  of the days in flight: two units of days, the one going to VOD and the
  one being read (:func:`~canvodpy.orchestrator.pipeline._run_ahead`).
- Each worker holds the Python libraries, plus its largest task: a task
  reads the files that share an epoch chunk, one after the other, and
  holds their data until it writes them. With ``processing.preprocessing``
  set the chunks are counted at the aggregation interval, so the files of
  a time bin are in one task.

Workers = min(the worker cap, (budget - main process with one day) /
largest task). A unit then gets as many days as the rest of the budget
holds, at most :data:`MAX_UNIT_DAYS` (ADR 0021). A run in which not even
one worker fits with one day stops before reading a file
(:class:`MemoryBudgetError`). The estimates come from the factors below,
measured on the test data; the workers log their real peaks
(``worker_memory_peak``, :func:`~canvodpy.orchestrator.resources.run_measured`).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

GB = 1024**3

#: Memory of a worker before its first task: Python and the scientific
#: libraries (0.24 GB measured on macOS, up to 0.33 GB after tasks).
WORKER_BASE_BYTES = int(0.35 * GB)

#: Peak memory of a worker task per byte of its input files, by reader.
#: Reading alone peaks at 66 (RINEX v2.11), 28 (RINEX v3.04), 15 (SBF) and
#: 8 (NMEA) times the file size on the test data; the factors add half of
#: that for the coordinates and the write.
TASK_BYTES_PER_INPUT_BYTE: Mapping[str, float] = {
    "rinex2": 100.0,
    "rinex3": 45.0,
    "rinex3_stripped": 45.0,
    "sbf": 25.0,
    "nmea": 15.0,
}

#: Memory a task holds per byte of its input files once they are read, until
#: it writes them: the data in memory (0.45 measured on the test data),
#: twice while preprocessing joins the files.
TASK_HELD_BYTES_PER_INPUT_BYTE = 1.0

#: For a reader not listed above: the largest factor.
UNKNOWN_READER_FACTOR = max(TASK_BYTES_PER_INPUT_BYTE.values())

#: Memory the main process holds per byte of a day's input files while the
#: day is in flight (0.45 measured on the test data, with the default
#: ``keep_gnss_observables``).
MAIN_BYTES_PER_DAY_INPUT_BYTE = 1.0

#: Units whose data are in memory at the same time (#277).
UNITS_IN_MEMORY = 2

#: Most days of a unit, so that a lost conflict or a crash loses little
#: (ADR 0021).
MAX_UNIT_DAYS = 31


class MemoryBudgetError(ValueError):
    """Not even one worker fits in the memory budget with one day per unit."""


@dataclass(frozen=True)
class InputFile:
    """A file a run reads: its size, reader and canVOD name (``""`` if none)."""

    path: Path
    size: int
    reader: str
    canonical_name: str


@dataclass(frozen=True)
class MemoryPlan:
    """The sizes a run uses and the numbers they come from."""

    budget_bytes: int
    main_bytes: int
    day_bytes: int
    task_peak_bytes: int
    largest_task: tuple[Path, ...]
    workers: int
    unit_days: int
    unit_limit: str
    tasks_per_day: float

    def log_fields(self) -> dict[str, object]:
        """The plan for the log, in GB.

        ``unit_limit`` says what set the days per unit: ``"memory"``,
        ``"max_unit_days"`` (:data:`MAX_UNIT_DAYS`), ``"days_to_run"``
        (the run has no more days) or ``"days_per_batch"`` (the
        deprecated setting).
        """
        return {
            "budget_gb": round(self.budget_bytes / GB, 2),
            "main_process_gb": round(self.main_bytes / GB, 2),
            "day_gb": round(self.day_bytes / GB, 2),
            "task_peak_gb": round(self.task_peak_bytes / GB, 2),
            "largest_task": [p.name for p in self.largest_task],
            "workers": self.workers,
            "unit_days": self.unit_days,
            "unit_limit": self.unit_limit,
            "tasks_per_day": round(self.tasks_per_day, 1),
            "tasks_per_worker": round(
                self.unit_days * self.tasks_per_day / self.workers, 1
            ),
        }


def task_peak_bytes(files: Sequence[InputFile]) -> int:
    """Estimated peak memory of a worker that reads ``files`` in one task.

    The task reads the files one after the other and holds their data until
    it writes them: the peak of reading its largest file, plus the data of
    all of them.
    """
    if not files:
        return WORKER_BASE_BYTES
    reading = max(
        f.size * TASK_BYTES_PER_INPUT_BYTE.get(f.reader, UNKNOWN_READER_FACTOR)
        for f in files
    )
    held = sum(f.size for f in files) * TASK_HELD_BYTES_PER_INPUT_BYTE
    return WORKER_BASE_BYTES + int(reading + held)


def chunk_tasks(
    files: Sequence[InputFile],
    *,
    epoch_chunk: int,
    cadence_s: float | None,
) -> list[list[InputFile]]:
    """The files of one receiver and day, grouped as the run's tasks group them.

    Files whose names put them into a shared epoch chunk are one task; the
    chunks start at 00:00 at the day's ``cadence_s`` (the aggregation
    interval, or else the finest sampling the names give). A time bin is
    one slot of the aggregated epochs, so the files of a bin share its
    chunk. A file without a canonical name is a task of its own.
    """
    from canvod.preflight.convention import CanVODFilename
    from canvodpy.orchestrator.forked_writes import chunk_groups

    named = [
        (f, CanVODFilename.from_filename(f.canonical_name))
        for f in files
        if f.canonical_name
    ]
    if cadence_s is None:
        intervals = [n.sampling_interval.total_seconds() for _, n in named]
        cadence_s = min(intervals) if intervals else None
    chunks_of: list[tuple[InputFile, set[object]]] = []
    for f in files:
        if not f.canonical_name or not cadence_s:
            chunks_of.append((f, {("own", f.path)}))
            continue
        name = CanVODFilename.from_filename(f.canonical_name)
        midnight = datetime.combine(
            name.start.date(), datetime.min.time(), name.start.tzinfo
        )
        chunk_s = epoch_chunk * cadence_s
        first = (name.start - midnight).total_seconds() // chunk_s
        last_epoch = name.end - name.sampling_interval
        last = max(first, (last_epoch - midnight).total_seconds() // chunk_s)
        chunks_of.append((f, {int(c) for c in range(int(first), int(last) + 1)}))
    return [members for members, _ in chunk_groups(chunks_of)]


def largest_task(
    receiver_days: Iterable[Sequence[InputFile]],
    *,
    epoch_chunk: int,
    cadence_s: float | None,
) -> list[InputFile]:
    """The task of the largest estimated peak over all receiver-days."""
    best: list[InputFile] = []
    best_peak = -1
    for files in receiver_days:
        for task in chunk_tasks(files, epoch_chunk=epoch_chunk, cadence_s=cadence_s):
            peak = task_peak_bytes(task)
            if peak > best_peak:
                best, best_peak = task, peak
    return best


def plan_memory(
    *,
    budget_bytes: int,
    main_now_bytes: int,
    day_input_bytes: int,
    task: Sequence[InputFile],
    tasks_per_day: float,
    max_workers: int,
    days_to_run: int,
    budget_source: str,
    days_per_batch: int | None = None,
) -> MemoryPlan:
    """Size the workers and the days per unit to fit ``budget_bytes``.

    The workers come first: as many as fit next to the main process with
    one day in flight. A unit then gets the most days the rest of the
    budget holds, at most :data:`MAX_UNIT_DAYS` and the days the run has
    (ADR 0021).

    Parameters
    ----------
    budget_bytes
        The memory the run may use.
    main_now_bytes
        Memory of the main process when the run starts.
    day_input_bytes
        Size of the input files of the largest day (all receivers).
    task
        The largest task (:func:`largest_task`).
    tasks_per_day
        The tasks of a day, on average over the run's days; for the log.
    max_workers
        The worker cap: ``n_max_threads``, or the cores minus two.
    days_to_run
        The days the run processes.
    budget_source
        Where the budget comes from, for the error message.
    days_per_batch
        The deprecated ``processing.params.days_per_batch``: if given, a
        unit has at most this many days.

    Raises
    ------
    MemoryBudgetError
        If one worker does not fit with one day per unit.
    """
    peak = task_peak_bytes(task)
    day_bytes = int(day_input_bytes * MAIN_BYTES_PER_DAY_INPUT_BYTE)

    def main_bytes(days: int) -> int:
        return main_now_bytes + UNITS_IN_MEMORY * days * day_bytes

    if main_bytes(1) + peak > budget_bytes:
        files = ", ".join(f.path.name for f in task)
        msg = (
            f"The run needs at least {(main_bytes(1) + peak) / GB:.1f} GB of "
            f"memory, but its budget is {budget_bytes / GB:.1f} GB "
            f"({budget_source}). The main process needs "
            f"{main_bytes(1) / GB:.1f} GB with one day per unit "
            f"({UNITS_IN_MEMORY} days in flight), and one worker reading "
            f"{files} needs {peak / GB:.1f} GB. Raise "
            "processing.params.max_memory_gb or free memory."
        )
        raise MemoryBudgetError(msg)
    workers = int(max(1, min(max_workers, (budget_bytes - main_bytes(1)) // peak)))

    limits = {"max_unit_days": MAX_UNIT_DAYS, "days_to_run": max(1, days_to_run)}
    if days_per_batch is not None:
        limits["days_per_batch"] = max(1, days_per_batch)
    unit_limit = min(limits, key=lambda name: limits[name])
    days = limits[unit_limit]
    while days > 1 and main_bytes(days) + workers * peak > budget_bytes:
        days -= 1
        unit_limit = "memory"
    return MemoryPlan(
        budget_bytes=budget_bytes,
        main_bytes=main_bytes(days),
        day_bytes=day_bytes,
        task_peak_bytes=peak,
        largest_task=tuple(f.path for f in task),
        workers=workers,
        unit_days=days,
        unit_limit=unit_limit,
        tasks_per_day=tasks_per_day,
    )
