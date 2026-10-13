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

When a store write or read fails with a file system or Icechunk error,
for example because a network drive lost its connection, the run tries
again up to four times, after 5, 15, 45, and 90 seconds. Each retry logs
a `store_op_retry` warning. Only when the last try fails does the run
log the error.

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
main process: `writing` (the GNSS store), `vod_calc`, and `vod_store`.
The reading steps run in the worker processes; their times are in the
log files and in the [dashboard](#see-where-a-run-spends-its-time).

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
grep -h '"run_id": "ExampleSite-20261010-030000"' machine/agent*.json
```

The worker processes write to their own files, so search
`machine/agent*.json` to include them. Add the older files
(`machine/agent*.json*`) to search further back.

---

## The run ID

`canvodpy run` gives each site it processes a run ID: the site name and
the start time in UTC, for example `ExampleSite-20261010-030000`. In
Python, `site.pipeline()` sets one in the same way; it applies until the
pipeline is closed, at the end of the `with` block. Every event of the
run carries it in the `run_id` field, in the main process, and in the
workers, so one search finds everything a run logged.

The run ID also goes into the message of each commit the run makes to
the stores, as `(run=ExampleSite-20261010-030000)`. To see which run
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

## See where a run spends its time

`canvodpy dashboard` opens a [marimo](https://marimo.io/) app that shows
the timing events of `machine/performance*.json`:

```bash
canvodpy dashboard                         # log folder from the settings
canvodpy dashboard --logs-dir /path/to/logs
canvodpy dashboard --host 0.0.0.0 --port 8080
```

To start it together with a run, use `canvodpy run --dashboard`; the
dashboard keeps running after the run ends. `--dashboard-host` and
`--dashboard-port` set its address.

The dashboard shows, per site, receiver and VOD receiver pair:

- the duration of each step per day: `reading`, `validating`,
  `augmenting` (adding the satellite angles), and `writing` for each
  receiver, and `vod_calc` (computing the VOD) and `vod_store` (writing
  it) for each pair;
- the total time per day;
- a table with the exact figures.

It reloads the logs every 10 seconds by default, so you can watch a run
while it runs. On a long run, pick a longer interval.

The dashboard takes the site from the run ID. Events logged outside a
run carry none; the dashboard shows them with "(no run ID)" as the site.

The memory, CPU, and disk use of a run are in the `memory_stats` and
`resource_sample` events; see
[Parallel processing](parallel-processing.md#memory-use).

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

---

**Next in the trail:** [parallel processing](parallel-processing.md) · [configuration](configuration.md) · [architecture](../architecture.md)
