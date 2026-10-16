"""The memory budget of a run: how many workers and days per batch fit.

``processing.params.max_memory_gb`` is the budget; without it, the memory
available when the run starts. The budget holds the main process and the
workers:

- The main process holds what it holds when the run starts, plus the data
  of the days in flight: two batches of ``days_per_batch`` days, the one
  going to VOD and the one being read (:func:`~canvodpy.orchestrator.pipeline._run_ahead`).
- Each worker holds the Python libraries, plus the files of its largest
  task while it reads them (a task reads the files that share an epoch
  chunk, or with ``processing.preprocessing`` set all files of a receiver
  and day).

Workers = min(the worker cap, (budget - main process) / largest task).
``days_per_batch`` is lowered until at least one worker fits; a run in which
not even one worker fits with one day per batch stops before reading a file
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

#: For a reader not listed above: the largest factor.
UNKNOWN_READER_FACTOR = max(TASK_BYTES_PER_INPUT_BYTE.values())

#: Memory the main process holds per byte of a day's input files while the
#: day is in flight (0.45 measured on the test data, with the default
#: ``keep_gnss_observables``).
MAIN_BYTES_PER_DAY_INPUT_BYTE = 1.0

#: Batches whose data are in memory at the same time (#277).
BATCHES_IN_MEMORY = 2


class MemoryBudgetError(ValueError):
    """Not even one worker fits in the memory budget with one day per batch."""


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
    days_per_batch: int

    def log_fields(self) -> dict[str, object]:
        """The plan for the log, in GB."""
        return {
            "budget_gb": round(self.budget_bytes / GB, 2),
            "main_process_gb": round(self.main_bytes / GB, 2),
            "day_gb": round(self.day_bytes / GB, 2),
            "task_peak_gb": round(self.task_peak_bytes / GB, 2),
            "largest_task": [p.name for p in self.largest_task],
            "workers": self.workers,
            "days_per_batch": self.days_per_batch,
        }


def task_peak_bytes(files: Sequence[InputFile]) -> int:
    """Estimated peak memory of a worker that reads ``files`` in one task."""
    return WORKER_BASE_BYTES + int(
        sum(
            f.size * TASK_BYTES_PER_INPUT_BYTE.get(f.reader, UNKNOWN_READER_FACTOR)
            for f in files
        )
    )


def chunk_tasks(
    files: Sequence[InputFile],
    *,
    epoch_chunk: int,
    cadence_s: float | None,
    whole_day: bool,
) -> list[list[InputFile]]:
    """The files of one receiver and day, grouped as the run's tasks group them.

    With ``whole_day`` (``processing.preprocessing`` set) all files are one
    task. Otherwise files whose names put them into a shared epoch chunk
    are one task; the chunks start at 00:00 at the day's ``cadence_s`` (the
    aggregation interval, or else the finest sampling the names give). A
    file without a canonical name is a task of its own.
    """
    from canvod.preflight.convention import CanVODFilename
    from canvodpy.orchestrator.forked_writes import chunk_groups

    if whole_day:
        return [list(files)] if files else []
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
    whole_day: bool,
) -> list[InputFile]:
    """The task of the largest estimated peak over all receiver-days."""
    best: list[InputFile] = []
    best_peak = -1
    for files in receiver_days:
        for task in chunk_tasks(
            files, epoch_chunk=epoch_chunk, cadence_s=cadence_s, whole_day=whole_day
        ):
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
    max_workers: int,
    days_per_batch: int,
    budget_source: str,
) -> MemoryPlan:
    """Size the workers and ``days_per_batch`` to fit ``budget_bytes``.

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
    max_workers
        The worker cap: ``n_max_threads``, or the cores minus two.
    days_per_batch
        The days per batch asked for.
    budget_source
        Where the budget comes from, for the error message.

    Raises
    ------
    MemoryBudgetError
        If one worker does not fit with one day per batch.
    """
    peak = task_peak_bytes(task)
    day_bytes = int(day_input_bytes * MAIN_BYTES_PER_DAY_INPUT_BYTE)

    def main_bytes(days: int) -> int:
        return main_now_bytes + BATCHES_IN_MEMORY * days * day_bytes

    days = days_per_batch
    while days > 1 and main_bytes(days) + peak > budget_bytes:
        days -= 1
    main = main_bytes(days)
    if main + peak > budget_bytes:
        files = ", ".join(f.path.name for f in task)
        msg = (
            f"The run needs at least {(main + peak) / GB:.1f} GB of memory, "
            f"but its budget is {budget_bytes / GB:.1f} GB ({budget_source}). "
            f"The main process needs {main / GB:.1f} GB with one day per batch "
            f"({BATCHES_IN_MEMORY} days in flight), and one worker reading "
            f"{files} needs {peak / GB:.1f} GB. Raise "
            "processing.params.max_memory_gb or free memory."
        )
        raise MemoryBudgetError(msg)
    workers = max(1, min(max_workers, (budget_bytes - main) // peak))
    return MemoryPlan(
        budget_bytes=budget_bytes,
        main_bytes=main,
        day_bytes=day_bytes,
        task_peak_bytes=peak,
        largest_task=tuple(f.path for f in task),
        workers=int(workers),
        days_per_batch=days,
    )
