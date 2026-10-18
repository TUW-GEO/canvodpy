---
title: Diagnostics
description: Where a run writes its logs, how to find out what went wrong, and the performance dashboard
---

# Diagnostics

A scheduled `canvodpy run` often runs on a server where nobody watches
it. Its log files are then the only record of what happened. This page
explains where the logs go, what each file holds, how to find the cause
of a failure, and how to see where a run spends its time.

---

## Where the logs go

Set the log folder under `processing.logging` in `canvod-settings.yaml`:

```yaml
processing:
  logging:
    log_dir: /path/to/logs
```

A run needs `log_dir`: without it, `canvodpy run` and `site.pipeline()`
stop before they process anything, with a message that names the
setting.

Importing canVODpy writes no log files. Until a run starts, warnings and
errors go to the terminal only. File logging starts when a pipeline is
created, by `canvodpy run` or by `site.pipeline()` in Python, so the log
folder comes from the settings of that run, including `--config-dir` and
`--config`. To write the log files without a pipeline, for example when
you use a reader or a store directly, call `canvodpy.setup_logging()`, or
`canvodpy.setup_logging(log_dir=...)` for another folder.

The terminal shows warnings and errors in every case.

---

## The log files

The logs use [structlog](https://www.structlog.org/): each entry is an
event with a name, such as `task_failed`, and fields, such as the date
and the receiver. The log folder holds these files:

| File | What it holds | When a new file starts | Old files kept |
|---|---|---|---|
| `human/main.log` | Information, warnings, and errors, one readable line each | Every midnight | 30 |
| `human/errors.log` | Errors only, with the full traceback | At 50 MB | 5 |
| `machine/agent.json` | Every event, including debug messages, one JSON object per line | At 100 MB | 150 |
| `machine/performance.json` | Timing events: `stage_timing` and every event with a `duration_seconds` field | At 50 MB | 60 |
| `component/processor.log` | Events of the file processing | Every midnight | 7 |
| `component/auxiliary.log` | Events of the orbit and clock data | Every midnight | 7 |
| `component/icechunk.log` | Events of the store writes | Every midnight | 7 |

Older files get a number or a date at the end of the name, for example
`agent.json.1` or `main.log.2026-10-09`.

`machine/agent.json` always records every event, debug messages
included. A failure on a remote server can't be run again with more
logging, so the detail has to be there already.

Each worker process writes its own set of files, with its process ID in
the name, for example `machine/agent.12345.json`. Files can't be shared
safely between processes. A worker creates a file only when it logs to
it. New workers get new process IDs, so these files don't rotate like
the files of the main process. Instead, a run deletes worker files that
haven't changed for 30 days when its file logging starts. To keep them
longer or shorter, set `worker_log_retention_days`:

```yaml
processing:
  logging:
    log_dir: /path/to/logs
    worker_log_retention_days: 90
```

---

## Find out what went wrong

### What the run does when something fails

Most failures don't stop a run. The run logs an error event and goes on:

| Event | What failed | What the run does |
|---|---|---|
| `task_failed` | Reading one file | Writes the other files of that receiver and day |
| `worker_pool_broken` | A worker process died, for example because the machine ran out of memory | Writes the other files of that receiver and day |
| `receiver_all_tasks_failed` | Every file of one receiver and day | Writes nothing for that receiver and day |
| `batch_all_tasks_failed` | Every file of one batch | Goes on with the next batch |
| `icechunk_write_failed` | Writing one receiver and day to the GNSS store | Goes on with the next receiver |
| `read_back_failed` | Reading a written day back from the GNSS store | Goes on with the next receiver |
| `vod_failed` | Computing the VOD of one receiver pair and day (`canvodpy run` only) | Goes on with the next pair |

These events carry the date (`date` or `date_key`) and the receiver, and
`human/errors.log` holds their tracebacks.

After `receiver_all_tasks_failed`, `icechunk_write_failed` and
`read_back_failed`, the receiver-day counts as failed: `canvodpy run`
names it at the end and exits with code 3, and `process_day` raises an
error.

When a store write or read fails with a file system or Icechunk error,
for example because a network drive lost its connection, the run tries
again up to four times, after 5, 15, 45, and 90 seconds. Each retry logs
a `store_op_retry` warning. Only when the last try fails does the run
log the error.

A conflict, when another commit changed the store first, is not a lost
connection: the run tries again on the new state of the store, up to
five tries in all, and logs a `store_conflict_retry` warning (for a day
of a store made of day blocks, `forked_day_conflict_retrying`) with the
number of the retry and the seconds it waited. The wait doubles with
every retry, from about 1 second, and has a random part, so two runs
that collided don't try again at the same moment. A conflict on the last
try is logged as an error.

Other errors stop the run:

- **`run_crashed`**: `canvodpy run` logs this event when an error ends
  the processing of a site. It names the step the run was in (`stage`,
  for example `pipeline_process` or `vod_store`) and the last day that
  was processed completely (`last_good_date_key`). Then the run stops;
  sites after it in the same command aren't processed.
- **`uncaught_exception`**: any error that would end Python is logged
  with its traceback before Python ends, in `canvodpy run` and in your
  own scripts once file logging has started.

After each site, also after a crash, `canvodpy run` logs a `run_summary`
event with the number of days processed (`days`), the VOD results
written (`vod_results`), and per step the number of times it ran, its
total time, and its errors (`stages`). `stages` covers the steps of the
main process, such as `planning`, `writing` (the GNSS store),
`vod_calc`, and `vod_store`.
The reading steps run in the worker processes; their times are in the
log files and in the [dashboard](#see-where-a-run-spends-its-time).

### Missing files and days without VOD

Before it processes anything, a run checks the files of each of its
receiver-days. A receiver-day is complete when it has as
many files as its file length gives for a whole day: 96 files of 15
minutes (`15M` in the name), 24 of an hour, one daily file. For
each receiver-day with fewer files, the run prints one line and logs a
`receiver_day_incomplete` warning with the receiver, the day, the files
found (`files_found`) and the files expected (`files_expected`):

```
  incomplete: canopy_01 has 81 of 96 files on 2025001
```

The run still processes that day, with the files it has. Today is not
checked, because its files are still arriving.

A day on which one receiver of a pair has files and the other has none
is not processed, so it gets no VOD. The run prints one line per
receiver that lacks files and logs a `days_without_vod` warning:

```
  no VOD on 2 days, reference_01 has no files: 2025002, 2025003
```

When the VOD of a processed day is skipped because the data of a
receiver is missing, for example because that receiver-day failed, the
run prints which data is missing and logs a `vod_skipped` warning; the
log says why the receiver-day failed:

```
  VOD canopy_01_vs_reference_01: skipped, no data of canopy_01 on 2025001 (the log says why)
```

In Python, `site.pipeline(on_incomplete_day=..., on_days_without_vod=...)`
receives the same findings: `(receiver, day, files_found, files_expected)`
for each incomplete receiver-day, and a receiver with its days without
VOD.

### Search the logs

Each line of `machine/agent.json` is one JSON object, so you can search
it with `grep` or [jq](https://jqlang.org/):

```bash
cd /path/to/logs

# The errors that stopped a run
grep -E '"event": "(run_crashed|uncaught_exception)"' machine/agent.json

# Every failed file, with its date and receiver
jq -c 'select(.event == "task_failed") | {timestamp, date, receiver}' machine/agent*.json

# Everything one run logged, in the main process and the workers
grep -h '"run_id": "ExampleSite-20261010-030000-3f9a1c"' machine/agent*.json
```

The worker processes write to their own files, so search
`machine/agent*.json` to include them. Add the older files
(`machine/agent*.json*`) to search further back.

---

## The run ID

`canvodpy run` gives each site it processes a run ID: the site name, the
start time in UTC and six random characters, for example
`ExampleSite-20261010-030000-3f9a1c`. The random part keeps the run IDs
of two machines apart when both start a run in the same second. In
Python, `site.pipeline()` sets one in the same way; it applies until the
pipeline is closed, at the end of the `with` block. Every event of the
run carries it in the `run_id` field, in the main process, and in the
workers, so one search finds everything a run logged.

The run ID also goes into the message of each commit the run makes to
the stores, as `(run=ExampleSite-20261010-030000-3f9a1c)`. To see which run
wrote which data, list the commits:

```bash
canvodpy store log ExampleSite --store gnss
```

To use a run ID of your own, set it before you create the pipeline; the
pipeline then keeps it:

```python
from canvodpy import Site
from canvodpy.logging import reset_run_id, set_run_id

site = Site("ExampleSite")
token = set_run_id("ExampleSite-reprocessing-2025")
try:
    with site.pipeline() as pipeline:
        for date, data in pipeline.process_range("2025001", "2025007"):
            ...
finally:
    reset_run_id(token)
```

The worker processes take the run ID when they start. When the run ID
changes, the run starts new workers.

---

## The run history

Every run records itself in the **run history**: `run_history.sqlite`
in the log folder, one file per machine (ADR 0018). A run of
`canvodpy run`, of `site.pipeline()` (until the pipeline is closed, at
the end of the `with` block) and of the Airflow task `process_day`
records:

- its start: site, run ID, settings, canvodpy version and commit,
  machine (CPU, memory, operating system, Python, size and free space of
  the disks of the log folder and the stores), worker count, and the
  label of `--label` or `site.pipeline(label=...)`;
- the receiver-days it plans, and for each one it finishes: `written`,
  `skipped` (every file already in the store) or `failed`, and the size
  of the data written (in memory, before compression);
- the time of each stage, with the process that ran it (see the table
  below);
- every 30 seconds and once more at its end, also when it fails: the
  CPU use and memory use of the machine (percent) and the free space of
  the disks of the log folder and the stores
  (`history.resource_samples(run_id)`);
- once a data day the run finishes, on the same background thread: the
  on-disk size of each local store the run writes (the GNSS and VOD
  stores), recorded against the data day (YYYYDOY) the run had finished,
  so the run history shows how the store grew over the run; how long the
  walk took is recorded beside it
  (`history.store_sizes(run_id)`);
- its warnings and errors, in words, with their receiver and day (a
  receiver-day with missing files reads, for example,
  `canopy_01 has 81 of 96 files on 2025001`);
- its end: `finished`, or `failed` with the error.

The same file holds the [file index](../packages/naming/overview.md#folders-of-other-days-come-from-the-file-index):
the names found in each folder of every receiver directory, so a run need
not list the folders that hold none of the days it processes.

The stages a run records, from every `stage_timing` event of the run:

| Stage | Process | One per |
|---|---|---|
| `finding_files` | main | receiver folder scanned |
| `auxiliary_data` | main | day: downloading or reading the orbit and clock files |
| `rinex.process_file` | worker | file: everything below, together |
| `reading`, `validating`, `augmenting` | worker | file: reading it, checking its signals, adding positions and geometry |
| `day_block_growth` | main | batch: giving its days a block in the GNSS store, one commit |
| `planning` | main | day: planning which worker writes which part of the day (reads the store's day blocks and log book) |
| `writing` | main | unit of days with workers: merging the workers' parts of all its receivers and days and committing them to the GNSS store, one commit; one record per unit, with `days` and the comma-joined dates; without workers: receiver-day, writing to the GNSS store |
| `assembly` | main | receiver-day: reading the written day back from the GNSS store, in `process_range` and `process_date` only (a run reads nothing back) |
| `icechunk.write` | main | group write of a store made before day blocks |
| `vod_day_block_growth` | main | unit of days: giving its days a block in the VOD store, one commit |
| `vod_calc` | worker | VOD analysis and day: reading the day from the GNSS store and computing its VOD (recorded by the main process) |
| `vod_store` | main | unit of days: merging the VOD of all its days and analyses and committing it to the VOD store, one commit; one record per unit, with `days` |

A run that has no end and whose process is gone shows as `interrupted`.
A run whose run ID the run history already holds (set by the caller and
used before) gets a number (`ExampleSite-20261010-030000-3f9a1c-2`).

Read it from Python, also while a run writes to it:

```python
from canvodpy.run_history import RunHistory

with RunHistory.open("/path/to/logs", read_only=True) as history:
    for run in history.runs(site="ExampleSite", label="benchmark-a"):
        print(run.run_id, run.status, run.started_at, run.ended_at)
        for problem in history.problems(run.run_id):
            print(" ", problem.level, problem.day, problem.message)
```

The run history must be on a local disk: SQLite needs shared memory for
one process to write while others read, which network drives (NFS, SMB)
don't provide. A run refuses to start when the log folder
(`processing.logging.log_dir`) is on a network drive. Errors that stop
`canvodpy run` before processing starts (for example a settings check)
are in the log files only.

---

## See where a run spends its time

Finding the files is the first thing a run does, before it reads a file.
On a network drive it can take minutes, so the CLI says, for each receiver,
`Finding files of receiver <name> in <folder>...` and then
`Found <n> files on <d> days for receiver <name> (<s> s)`, so you know it
is working. From the second run on, the folders that hold none of the
days the run processes come from the [file index](../packages/naming/overview.md#folders-of-other-days-come-from-the-file-index)
and the listing is much shorter; the log event `files_found` says per
receiver how many folders were listed and how many came from the index.

`canvodpy dashboard` opens a [marimo](https://marimo.io/) app that reads
the run history of a log folder:

```bash
canvodpy dashboard                         # log folder from the settings
canvodpy dashboard --logs-dir /path/to/logs
canvodpy dashboard --host 0.0.0.0 --port 8080
```

To start it together with a run, use `canvodpy run --dashboard`; the
dashboard keeps running after the run ends. `--dashboard-host` and
`--dashboard-port` set its address.

No runs of your own yet? `canvodpy.demo_data("run_history")` downloads
an anonymized example: nine runs of the same seven days of two
receivers with 1 to 126 workers, and a warm-up run with failed orbit
downloads. Open it with
`canvodpy dashboard --logs-dir <folder>/run_history`, where `<folder>`
is the folder `demo_data` returns. The demo notebook
[23 · Run Dashboard](https://github.com/nfb2021/canvodpy-demo/blob/main/23_run_dashboard.py)
shows the dashboard on it.

The dashboard reads the run history, not the log files, so nothing
disappears when the log files rotate, and it knows a run's settings,
machine, progress, and problems.

**Site overview:** one row per site: its last run, that run's status and
its start and end, and the receiver-days it planned, wrote, skipped,
failed and hasn't done yet.

**Run page:** pick a run (newest first). It shows the run's settings, the
canvodpy version and commit, the machine, the workers and the label; the
progress per receiver (planned, written, skipped, failed, not yet done,
bytes added);
an estimate of when it finishes; the last finished step; the
throughput; and the run's warnings and errors in words, with their
receiver and day.

The page labels the times in UTC and the three numbers above, and says
how each is computed:

- **Estimate:** for a running run, the mean time per finished
  receiver-day of this run times the receiver-days not yet done. There
  is no estimate before the first receiver-day finishes.
- **Last finished step:** the newest recorded stage of a run (stage,
  receiver, day, how long ago). The run history records a stage when it
  ends, so this is the last finished step, not the step running now.
- **Throughput:** receiver-days finished per hour and bytes added per
  hour over the run (so far, for a running run).

**Charts:** the run page also shows charts of the run, built from the
run history queries only:

- **Time per stage:** the median of a stage's per-day seconds (left,
  "Median per day") and the total seconds of each stage (right,
  "Total"), in the same order (by total). The median is over the seconds
  of a day, added up over the day's receivers; a stage that names no day
  (such as `day_block_growth`) takes the median of its records; a unit
  of days is split evenly over its days. A long bar is a stage that
  takes a lot of the run.
- **Time per day:** the stage seconds of a data day, added up over all
  its receivers, as a line over the days so a trend over the run is easy
  to see. A run that works in units of days splits a unit's record
  evenly over its days. Receivers run in parallel, so this is not wall
  time; a day can show more seconds than it took.
- **Store size on disk:** the on-disk size of each local store (GNSS,
  VOD) as a line, plus a **Total** line, measured on the background
  sampler thread when the run finished a new data day (never inside a
  stage or a commit), so the growth of the store over the run is
  visible. The x-axis is the data day (YYYYDOY), one point per data day
  the size was measured (a unit of days has one point, on its last day);
  the y-axis is in MB or GB, chosen from the values. How long each walk
  took is recorded too (`history.store_sizes(run_id)`).
- **CPU and memory:** the percent of the CPU and memory used, sampled
  during the run. A line near 100 % shows what limits the run.
- **Free disk:** the free space of each folder, sampled during the run.
  Free disk is one value per folder, so a chart has one line per folder;
  the y-axis is in gigabytes.
- **Throughput over time:** the receiver-days finished, cumulative from
  the run start. The slope is the pace; a steep line is a fast run.

The dashboard is always dark, whatever the machine's or the browser's
setting: the notebook's script header sets the marimo theme. The data
colors fit canvodpy's colors, those of this documentation. A chart
with one series is canvodpy's green. Up to four series, such as CPU and
memory, get cream, blue, amber and brick red, which differ in hue and in
lightness. More series, such as a comparison of eight worker counts, run
from dark blue over sky blue and amber to canvodpy's cream, so they get
lighter in the sorted order of their labels. Both stay readable with a
red-green color vision deficiency and in grayscale.

Every chart of a duration (time per stage, time per day, the
comparison) has a **Time axis** switch between a linear axis from zero
and a logarithmic one, which spreads short and long stages apart. The
free-disk chart starts its axis near the lowest value, not at zero, so
a change in free space is visible. The settings and the machine of a
run are folded in; click to open them.

**Compare runs by label:** a run can take a free-text label with
`canvodpy run --label <text>`, for example to group the repetitions of a
benchmark. The dashboard groups the runs that share a label and compares
them:

- Only **finished** runs are compared, and a run without a label is left
  out.
- Each group shows its machine, workers, version and settings, or
  "differs" when the group is not uniform. A group whose machine,
  workers, version or settings differ is not a set of repetitions of the
  same thing, and the dashboard says so.
- For each stage, the median time of the group's finished runs that
  recorded it, with the minimum and the maximum. Per stage a run's time
  is the sum over its receivers and days (across its worker processes).
  In total, the median of the runs' wall time (ended minus started),
  with the minimum and the maximum. Stages run in parallel, so the stage
  times can add up to more than the total. The median is the middle of
  the sorted times; the spread is min to max.
- A grouped bar chart shows the median time per stage: per stage one bar
  per label, side by side, colored as described above, in the sorted
  order of the labels (with zero-padded numbers, such as `w001`, `w016`, `w126`, that
  is the order of the numbers). Hover over a bar for its label and time.

**Download the data:** the run page and the comparison each have a
download button (**Download the data of this run**, **Download the data
of this comparison**). Each gives a zip with:

- `run_history.sqlite`: every record of the runs shown (settings,
  machine, receiver-days, stage timings, resource samples, warnings and
  errors) and nothing of other runs.
- One CSV file per table and chart of the view, with the rows the
  dashboard showed.
- `README.txt`: the canvodpy version, the log folder, the runs, and
  what each file holds.

Unzipped, the folder opens like a log folder, so
`canvodpy dashboard --logs-dir <folder>` shows the same runs on another
machine. The zip is made when you click, so for a running run its run
history can hold records newer than the page. Each table's own
**Export** button saves just that table as CSV or JSON.

A run's status is one of:

- **Running:** the run's process lives.
- **Finished:** it ended and wrote a result.
- **Failed:** it ended with an error.
- **Interrupted:** its process is gone without an end (killed or
  crashed).
- **Unknown:** it started on another machine, whose processes can't be
  checked from here.

It reloads the run history every 10 seconds by default, so you can watch
a run while it runs. On a long run, pick a longer interval.

You can open the same notebook without canvodpy installed, on a machine
that has a run history folder. From v1.0.0 on, canvodpy on PyPI ships the
run history, and `marimo run --sandbox` installs canvodpy in a sandbox
and takes the folder from `--logs-dir` after `--`:

```bash
uvx marimo run --sandbox \
  https://raw.githubusercontent.com/nfb2021/canvodpy/main/canvodpy/src/canvodpy/cli/dashboards/performance.py \
  -- --logs-dir /path/to/logs
```

Read from that URL, the notebook takes the run history from the
installed canvodpy (its logo comes from the installed package too), but
the style sheet sits next to the notebook, so the app runs with marimo's
default styling.

!!! example "Try it in a notebook"

    Open [Batch processing](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/20_workflow_batch_processing.py?mode=edit) in molab, the online notebook service of marimo.

---

## Time your own code

To time a step in your own code or in a [plugin](plugins.md), use
`stage_timer` or its decorator form `timed_stage`. Each writes one
`stage_timing` event when the step ends, with the step name, the
duration in seconds (`duration_seconds`), the status (`ok` or `error`),
and the fields you pass. It also writes the event when the step fails,
before the error goes on.

```python
from canvodpy.logging import stage_timer, timed_stage

with stage_timer("my_step", receiver="canopy_01"):
    ...


@timed_stage("my_function")
def my_function(): ...
```

When you measure the times yourself, for example several steps from one
set of checkpoints, `record_stage_timing("my_step", seconds, ...)` writes
the same event.

The events go to `machine/performance.json`. The dashboard draws events
that carry a `date_key` (`YYYYDDD`) and a `receiver` or `analysis`
field.

Every commit to a store also writes a `commit_parts` event there, not a
stage: the seconds it waited for the commit lock (`lock_wait_seconds`),
opened the repository (`open_seconds`), checked the content settings
(`content_check_seconds`) and the stored lockfile
(`lockfile_check_seconds`), rebased (`rebase_seconds`), wrote the
store metadata and snapshot summary (`summary_seconds`; a process's
first commit to a store rebuilds the summary from the whole store, later
ones update it from their own log-book rows), committed
(`icechunk_commit_seconds`) and released the lock
(`lock_release_seconds`), with the commit message and the number of
the commit in this process (`commit_number`).

---

**Next in the trail:** [parallel processing](parallel-processing.md) · [configuration](configuration.md) · [architecture](../architecture.md)
