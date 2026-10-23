"""The memory budget sizes the workers and the days per unit (#278, #425).

``processing.params.max_memory_gb`` (or the memory available) holds the
main process, with two units of days in flight, and the workers, each
with its largest task. The workers come first; a unit gets the days the
rest of the budget holds, at most 31 (ADR 0021). A run in which one worker
does not fit stops before reading a file, saying how much memory it needs;
the workers log their peaks.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from canvodpy.orchestrator.memory_budget import (
    GB,
    MAIN_BYTES_PER_INPUT_BYTE,
    MAX_UNIT_DAYS,
    TASK_BYTES_PER_INPUT_BYTE,
    TASK_HELD_BYTES_PER_INPUT_BYTE,
    UNITS_IN_MEMORY,
    WORKER_BASE_BYTES,
    InputFile,
    MemoryBudgetError,
    chunk_tasks,
    largest_task,
    main_day_bytes,
    plan_memory,
    task_peak_bytes,
)

from canvod.utils import testing

MB = 1024**2


def _file(
    hhmm: str, size: int, *, period: str = "15M", sampling: str = "05S"
) -> InputFile:
    name = f"{testing.SITE_ID}A01{testing.AGENCY}_R_2025001{hhmm}_{period}_{sampling}_AA.rnx"
    return InputFile(path=Path(name), size=size, reader="rinex3", canonical_name=name)


def _plan(budget_gb: float, task: list[InputFile], **kwargs) -> object:
    defaults = {
        "main_now_bytes": int(0.5 * GB),
        "day_bytes": 0,
        "max_workers": 16,
        "days_to_run": 1,
        "tasks_per_day": 1.0,
        "budget_source": "processing.params.max_memory_gb",
    }
    return plan_memory(budget_bytes=int(budget_gb * GB), task=task, **defaults | kwargs)


def test_the_workers_follow_the_budget():
    task = [_file("0000", 20 * MB)]
    peak = task_peak_bytes(task)
    assert peak == WORKER_BASE_BYTES + 20 * MB * (
        TASK_BYTES_PER_INPUT_BYTE["rinex3"] + TASK_HELD_BYTES_PER_INPUT_BYTE
    )
    for workers in (1, 3, 7):
        budget = (int(0.5 * GB) + workers * peak) / GB
        assert _plan(budget, task).workers == workers


def test_the_workers_stay_within_the_cap():
    assert _plan(64, [_file("0000", MB)], max_workers=4).workers == 4


def test_a_unit_gets_the_days_the_memory_left_by_the_workers_holds():
    task = [_file("0000", MB)]
    peak = task_peak_bytes(task)
    day = int(0.25 * GB)
    # Room for the main process with three days per unit and one worker.
    budget = int(0.5 * GB) + UNITS_IN_MEMORY * 3 * day + peak
    plan = _plan(budget / GB, task, day_bytes=day, days_to_run=10, max_workers=1)
    assert (plan.unit_days, plan.unit_limit, plan.workers) == (3, "memory", 1)


def test_the_workers_come_before_the_days_of_a_unit():
    task = [_file("0000", MB)]
    peak = task_peak_bytes(task)
    day = int(0.25 * GB)
    # Room for four workers with one day, or one worker with more days.
    budget = int(0.5 * GB) + UNITS_IN_MEMORY * day + 4 * peak
    plan = _plan(budget / GB, task, day_bytes=day, days_to_run=10)
    assert (plan.workers, plan.unit_days) == (4, 1)


@pytest.mark.parametrize(
    ("days_to_run", "days_per_batch", "unit_days", "unit_limit"),
    [
        (400, None, MAX_UNIT_DAYS, "max_unit_days"),
        (5, None, 5, "days_to_run"),
        (400, 7, 7, "days_per_batch"),
    ],
)
def test_without_a_memory_limit_a_unit_has_at_most_31_days(
    days_to_run, days_per_batch, unit_days, unit_limit
):
    plan = _plan(
        64,
        [_file("0000", MB)],
        day_bytes=MB,
        days_to_run=days_to_run,
        days_per_batch=days_per_batch,
    )
    assert (plan.unit_days, plan.unit_limit) == (unit_days, unit_limit)


def test_a_rinex_v3_day_is_counted_at_its_file_size():
    """Unchanged by #452, so RINEX v3 runs get the same workers and units."""
    day = [_file(f"{h:02d}00", 2 * MB) for h in range(24)]
    assert main_day_bytes(day) == 48 * MB


def test_an_sbf_day_is_counted_at_a_quarter_of_its_file_size():
    sbf = InputFile(path=Path("b.sbf"), size=40 * MB, reader="sbf", canonical_name="")
    assert main_day_bytes([sbf]) == 10 * MB


def test_a_reader_without_a_main_factor_gets_the_largest():
    unknown = InputFile(path=Path("x.dat"), size=MB, reader="new", canonical_name="")
    assert main_day_bytes([unknown]) == int(
        MB * max(MAIN_BYTES_PER_INPUT_BYTE.values())
    )


def test_an_sbf_day_of_the_test_data_fits_in_its_free_memory():
    """The Rosalia SBF test day (#452): 2.2 GB of input with 4.6 GB free.

    The run was refused with the main process estimated at 4.8 GB; it
    peaked at 0.75 GB.
    """
    files = [
        InputFile(
            path=Path(f"{i}.sbf"),
            size=int(2.2 * GB / 192),
            reader="sbf",
            canonical_name="",
        )
        for i in range(192)
    ]
    plan = _plan(
        4.6, [files[0]], main_now_bytes=int(0.4 * GB), day_bytes=main_day_bytes(files)
    )
    assert plan.workers >= 1


def test_the_log_says_what_set_the_unit():
    plan = _plan(64, [_file("0000", MB)], days_to_run=5, tasks_per_day=192.0)
    fields = plan.log_fields()
    assert fields["unit_days"] == 5
    assert fields["unit_limit"] == "days_to_run"
    assert fields["tasks_per_day"] == 192.0
    assert fields["tasks_per_worker"] == 5 * 192 / plan.workers


def test_a_budget_smaller_than_one_file_stops_naming_the_memory_needed():
    task = [_file("0000", 100 * MB)]
    needed = int(0.5 * GB) + task_peak_bytes(task)
    with pytest.raises(MemoryBudgetError) as raised:
        _plan(1.0, task)
    message = str(raised.value)
    assert f"at least {needed / GB:.1f} GB" in message
    assert "budget is 1.0 GB (processing.params.max_memory_gb)" in message
    assert task[0].path.name in message


def test_files_sharing_an_epoch_chunk_are_one_task():
    # Six 15-minute files at 30 s fill one chunk of 180 epochs (90 minutes).
    files = [
        _file(f"{h:02d}{m:02d}", MB, sampling="30S")
        for h in (0, 1)
        for m in (0, 15, 30, 45)
    ]
    tasks = chunk_tasks(files, epoch_chunk=180, cadence_s=None)
    assert [len(t) for t in tasks] == [6, 2]


def test_a_file_filling_its_chunks_is_a_task_of_its_own():
    files = [_file(f"00{m:02d}", MB) for m in (0, 15, 30, 45)]
    tasks = chunk_tasks(files, epoch_chunk=180, cadence_s=None)
    assert [len(t) for t in tasks] == [1, 1, 1, 1]


def test_with_preprocessing_the_files_of_a_time_bin_are_one_task():
    # 1-minute bins: a chunk of 180 bins holds three hours, twelve
    # 15-minute files, not the whole day (#417).
    files = [
        _file(f"{h:02d}{m:02d}", 2 * MB) for h in range(24) for m in range(0, 60, 15)
    ]
    tasks = chunk_tasks(files, epoch_chunk=180, cadence_s=60.0)
    assert [len(t) for t in tasks] == [12] * 8


def test_a_task_reads_its_files_one_after_the_other():
    # The peak of reading the largest file, plus the data of all of them;
    # the 96 files of a day at 2 MB each give under 0.8 GB, not 9 GB (#417).
    files = [_file(f"00{m:02d}", 2 * MB) for m in (0, 15, 30, 45)]
    reading = 2 * MB * TASK_BYTES_PER_INPUT_BYTE["rinex3"]
    held = 4 * 2 * MB * TASK_HELD_BYTES_PER_INPUT_BYTE
    assert task_peak_bytes(files) == pytest.approx(
        WORKER_BASE_BYTES + reading + held, abs=1
    )


def test_a_daily_file_is_one_task():
    daily = _file("0000", 217 * MB, period="01D")
    tasks = chunk_tasks([daily], epoch_chunk=180, cadence_s=60.0)
    assert tasks == [[daily]]
    assert task_peak_bytes(tasks[0]) > 217 * MB * TASK_BYTES_PER_INPUT_BYTE["rinex3"]


def test_a_file_without_a_canonical_name_is_a_task_of_its_own():
    files = [
        InputFile(path=Path(f"odd{i}.rnx"), size=MB, reader="rinex3", canonical_name="")
        for i in range(3)
    ]
    tasks = chunk_tasks(files, epoch_chunk=180, cadence_s=None)
    assert [len(t) for t in tasks] == [1, 1, 1]


def test_the_largest_task_is_taken():
    small = [_file("0000", MB)]
    large = [
        _file("0000", 3 * MB, sampling="30S"),
        _file("0015", 3 * MB, sampling="30S"),
    ]
    assert largest_task([small, large]) == large
    assert largest_task([]) == []


# ── A run on the test data ───────────────────────────────────────────────


def _log_events(log_dir: Path, event: str) -> list[dict]:
    events = []
    for path in log_dir.rglob("*"):
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("{") and f'"{event}"' in line:
                record = json.loads(line)
                if record.get("event") == event:
                    events.append(record)
    return events


@pytest.mark.integration
def test_a_run_whose_file_does_not_fit_stops_before_reading(rosalia_site):
    from canvodpy.orchestrator.pipeline import PipelineOrchestrator

    config, site = rosalia_site
    with (
        PipelineOrchestrator(
            site=site, max_memory_gb=0.1, config=config
        ) as orchestrator,
        pytest.raises(MemoryBudgetError, match=r"needs at least \d+\.\d GB"),
    ):
        next(orchestrator.process_by_date(keep_vars=None))
    log_dir = Path(config.processing.logging.log_dir)
    assert not _log_events(log_dir, "worker_memory_peak")


@pytest.mark.integration
def test_a_run_logs_its_sizes_and_the_worker_peaks(rosalia_site):
    from canvodpy.orchestrator.pipeline import PipelineOrchestrator

    config, site = rosalia_site
    with PipelineOrchestrator(
        site=site, n_max_workers=2, max_memory_gb=64, config=config
    ) as orchestrator:
        days = [day for day, _, _ in orchestrator.process_by_date(keep_vars=None)]
    assert days

    log_dir = Path(config.processing.logging.log_dir)
    (budget,) = _log_events(log_dir, "memory_budget")
    assert budget["workers"] == 2
    assert budget["budget_gb"] == 64
    peaks = _log_events(log_dir, "worker_memory_peak")
    assert peaks
    assert all(p["peak_gb"] >= p["before_gb"] > 0 for p in peaks)
    assert all(p["input_mb"] > 0 for p in peaks)


@pytest.mark.integration
def test_each_run_sizes_from_the_deprecated_cap_and_records_the_sized_workers(
    rosalia_site, monkeypatch
):
    import canvodpy.orchestrator.pipeline as pipeline_module
    from canvodpy.orchestrator.memory_budget import MemoryPlan
    from canvodpy.orchestrator.pipeline import PipelineOrchestrator
    from canvodpy.run_history import RunHistory, recorded_run

    asked = []

    def one_worker_one_day(**kwargs):
        asked.append(kwargs["days_per_batch"])
        return MemoryPlan(
            budget_bytes=kwargs["budget_bytes"],
            main_bytes=0,
            day_bytes=0,
            task_peak_bytes=0,
            largest_task=(),
            workers=1,
            unit_days=1,
            unit_limit="memory",
            tasks_per_day=1.0,
        )

    monkeypatch.setattr(pipeline_module, "plan_memory", one_worker_one_day)
    config, site = rosalia_site
    log_dir = Path(config.processing.logging.log_dir)
    with (
        recorded_run(site.site_name, log_dir=log_dir, settings={}, workers=4) as run,
        pytest.warns(FutureWarning, match="days_per_batch"),
        PipelineOrchestrator(
            site=site, n_max_workers=4, days_per_batch=3, config=config, run=run
        ) as orchestrator,
    ):
        for _ in range(2):
            assert list(orchestrator.process_by_date(keep_vars=None))

    # The second run of the orchestrator is capped at 3 days again, not at
    # the 1 the first one was lowered to.
    assert asked == [3, 3]
    with RunHistory.open(log_dir, read_only=True) as history:
        assert history.run(run.run_id).workers == 1
