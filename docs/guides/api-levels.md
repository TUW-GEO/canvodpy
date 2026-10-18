---
title: Command line and Python
description: Every option of canvodpy run, and the Site and Pipeline objects that do the same from Python
---

# Command line and Python

canVODpy runs from Python or from the command line. Both run the same
code: `canvodpy run` creates a `Site` and processes the days with
`Site.pipeline()`, so the stores hold the same data either way. Use
Python to script runs, for example in a notebook, or in a loop over
sites; use the command line for scheduled runs.

This page lists the options of both. For a first run, start with
[Retrieve VOD](../users/index.md).

---

## Process a period

=== "Python"

    ```python
    from canvodpy import Site

    site = Site("ExampleSite")
    with site.pipeline() as pipeline:
        for unit in pipeline.run("2025001", "2025007"):
            print(sorted(unit.days), unit.vod.written)
    ```

=== "Command line"

    ```bash
    canvodpy run --site ExampleSite --start 2025001 --end 2025007
    ```

Dates are `YYYYDDD`: the year and the day of year, for example
`2025032` for February 1, 2025.

| Command line | Python | Meaning |
|---|---|---|
| `--site ExampleSite` | `Site("ExampleSite")` | Site name under `sites:` in `canvod-settings.yaml`. Repeat `--site` to process several sites, one after the other. |
| `--start`, `--end` | `run(start, end)` | First and last day, both included; see [Which days a run processes](#which-days-a-run-processes). |
| `--no-vod` | `run(start, end, vod_analyses=())` | Write the observations to the GNSS store and compute no VOD. |
| `--vod-calculator` | `run(start, end, calculator=...)` | The VOD calculator, `tau_omega` by default. |
| `--dry-run` | `pipeline.preview(start, end)` | List the days, receivers and files a run would process, without processing them. |
| `--write-catalog` | `write_catalog(stores_root_dir)` after the run | After a successful run, write the [STAC catalog](../packages/store-metadata/overview.md#write-the-stac-catalog) of every store under the data root. Without it, a run writes no catalog. |
| `--label` | `site.pipeline(label=...)` | Free-text label stored with the run in the [run history](diagnostics.md#the-run-history), for example to group the repetitions of a benchmark. |
| `--workers` | `site.pipeline(n_workers=...)` | Number of worker processes. |
| `--config-dir`, `-c` | `CANVOD_CONFIG_DIR` | Folder that holds `canvod-settings.yaml` and `recipes/`; see [Where canVODpy finds the settings](configuration.md#where-canvodpy-finds-the-settings). |
| `--config` | `CANVOD_CONFIG_FILE` | [Overlay file](configuration.md#overlay-file) applied on top of `canvod-settings.yaml`. |
| `--ephemeris-source` | `processing.params.ephemeris_source` in the settings | `final` (orbit and clock products of an analysis center) or `broadcast` (the satellite angles an SBF file holds); see [Ephemeris sources](../packages/readers/ephemeris-sources.md). |
| `--vod-calculator` | `VodComputer(site, calculator=...)` | VOD calculator; `tau_omega` unless a [plugin](plugins.md) adds others. |
| `--dashboard` | None; run `canvodpy dashboard` | Start the performance dashboard for the run's logs. `--dashboard-host` and `--dashboard-port` set its address. |

Options you leave out take their values from the settings file. In
Python, set `CANVOD_CONFIG_DIR` and `CANVOD_CONFIG_FILE` before you
create the `Site`:

```python
import os

os.environ["CANVOD_CONFIG_DIR"] = "/path/to/config"
```

`canvodpy run --help` lists every option.

`canvodpy run` exits with code 0 when every receiver-day is written or
skipped, and with 1 when it stops, for example on an error in the
settings. When it finishes but a receiver-day failed, it names the
failed receiver-days and exits with 3;
[What the run does when something fails](diagnostics.md#what-the-run-does-when-something-fails)
lists the reasons. A receiver-day that is written though some of its
files failed counts as written. In Python,
`pipeline.failed_receiver_days` lists the failed receiver-days.

!!! example "Try it in a notebook"

    Open [Site pipeline](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/18_site_pipeline.py?mode=edit), [Running the pipeline from the command line](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/01_cli_pipeline.py?mode=edit) in molab, the online notebook service of marimo.

---

## Which days a run processes

In Python, you name the days: `process_date` processes one,
`process_range` the days from `start` to `end`.

On the command line, `--start` and `--end` are optional:

- Without `--end`, the run ends today.
- Without `--start`, the run looks at the last 30 days up to the end and
  processes only the days on which a receiver has a file that the site's
  GNSS store doesn't hold yet. It compares file names with the store's
  log book, so it reads no file to find them. If the store is empty, the
  run processes every day it finds data for.

So `canvodpy run --site ExampleSite` picks up the new files of the last
30 days: the days since the last run, a file that arrived late for an
earlier day, and the days of a receiver whose files arrive a few days
after the others. It prints them first, for example
`resuming: 2 receiver-days with new files (2026285 canopy_01, 2026286 canopy_01)`.
A day with no files in the archive is not looked at again. For new files
older than 30 days, give `--start` and `--end`: with explicit dates the
run processes every day in the range. With the default
`gnss_store_strategy: skip`, files that are already in the store are
skipped, so running a day twice doesn't duplicate data.

In Python, `process_range(start, end, new_files_only=True)` does the
same for any range, and `site.pipeline(on_new_files=...)` receives the
`(day, receiver)` pairs it found.

---

## The `Site` object

`Site("ExampleSite")` reads the settings of one site.

| Attribute | What it gives you |
|---|---|
| `site.receivers` | All receivers of the site, from the settings |
| `site.active_receivers` | The receivers a run processes: those not set to `active: false` |
| `site.vod_analyses` | The receiver pairs under `vod_analyses` |
| `site.gnss_store` | The GNSS store: observations and satellite angles |
| `site.vod_store` | The VOD store |
| `site.gnss_store_path`, `site.vod_store_path` | Where the stores are, from the settings; read-only |
| `site.vod` | Computes VOD; see [Compute VOD](#compute-vod) |
| `site.pipeline()` | Creates a `Pipeline` for this site |

Both stores are [Icechunk](https://icechunk.io/) repositories; see
[Storage](../packages/store/overview.md).

A run creates a site's stores when it first writes data. Before that,
`site.gnss_store` and `site.vod_store` raise a `FileNotFoundError`; the
paths tell you where a run puts them.

---

## The `Pipeline` object

A `Pipeline` reads the files, adds the satellite angles, and writes the
GNSS store. Use it in a `with` block, which closes it at the end.

| Method | What it does |
|---|---|
| `run(start, end, new_files_only=False, vod_analyses=None, calculator="tau_omega")` | What `canvodpy run` does: stores the days from `start` to `end` in [units of days](parallel-processing.md), then computes the VOD of each unit's days from the GNSS store. Yields one `RunUnit` per unit: `days` (each day stored, with the groups that stored it), `vod` (the days with VOD written, already stored, or missing and why, per analysis) and `vod_error` (why the VOD of the unit failed, if it did). `vod_analyses=()` computes no VOD. |
| `process_date(date)` | Processes one day and reads it back from the GNSS store. Returns one dataset per receiver. |
| `process_range(start, end, new_files_only=False)` | Processes the days from `start` to `end` and reads each one back. Yields `(date, datasets)` for one day at a time. With `new_files_only=True`, only the days on which a receiver has a file the GNSS store doesn't hold. Use it to work with the data in Python; `run` reads nothing back and is faster. |
| `preview(start=None, end=None, new_files_only=False)` | Returns the days, receivers and files a run would process. Without dates, it covers every day it finds data for. |
| `failed_receiver_days` | The receiver-days of this pipeline that failed, as `(receiver, date)` pairs. Empty when every one is written or skipped. |
| `close()` | Ends the pipeline. The `with` block calls it for you. The worker processes stay for reuse; see [Parallel processing](parallel-processing.md#the-worker-processes). |

The datasets are [xarray](https://docs.xarray.dev/) Datasets, keyed by
store group: `canopy_01` for a canopy receiver, and
`reference_01_canopy_01` for the data of a reference receiver paired with
that canopy receiver.

The arguments of `site.pipeline()` override the matching settings under
`processing.params` for this pipeline. Setting `n_workers` turns off the
automatic choice of `resource_mode: auto`:

| Argument | Meaning |
|---|---|
| `n_workers` | Number of worker processes |
| `threads_per_worker` | Threads that numerical libraries use in each worker |
| `keep_vars` | Observation variables to keep, such as `["SNR"]` |

The workers' CPU cores and priority come from the settings file;
[Parallel processing](parallel-processing.md#settings) explains them.

---

## Compute VOD

`pipeline.run()` computes the VOD of the days it stores. `site.vod`
computes VOD for the receiver pairs under `vod_analyses` on its own.

From the datasets of one day, without writing:

```python
with site.pipeline() as pipeline:
    for date, data in pipeline.process_range("2025001", "2025007"):
        vod = site.vod.compute_day_all(data, write=False)  # every pair
        # or one pair:
        # vod = site.vod.compute_day(data, "canopy_01_vs_reference_01", write=False)
```

Writing VOD this way (`write=True`, `write_day`) is deprecated; see
[Upgrading](upgrading.md).

From observations already in the GNSS store, for example after you
change the VOD settings, computed and written in the worker pool:

=== "Python"

    ```python
    from datetime import date, timedelta

    report = site.vod.compute_days(
        [date(2025, 1, 1) + timedelta(days=i) for i in range(31)],
        ["canopy_01_vs_reference_01"],
    )
    report.missing  # the days without VOD, and why
    ```

    Each day of each pair is one task in the worker pool, which reads only
    that day from the GNSS store, so a day takes as long in a large store
    as in a small one. Without the list of analyses, every pair is
    computed. A day whose VOD the store already holds from the same GNSS
    files is not computed again (`report.stored`), so running it twice
    adds nothing. A day without data in the canopy or the reference group
    gets no VOD and is listed in `report.missing`.

    To get the VOD of a time range back as one dataset, use
    `site.vod.compute_bulk`:

    ```python
    from datetime import datetime

    vod = site.vod.compute_bulk(
        "canopy_01_vs_reference_01",
        start=datetime(2025, 1, 1),
        end=datetime(2025, 1, 31, 23, 59, 59),
    )
    ```

    It runs `site.vod.compute_days` for the days of the range, then reads
    the VOD from `start` to `end` back from the VOD store. `start` and
    `end` are times, both included: `datetime(2025, 1, 31)` alone would
    end at midnight at the start of January 31. With `write=False`, it
    reads the range into memory and computes the VOD there, without the
    worker pool, and writes nothing. `site.vod.compute_bulk_all` computes
    every pair.

=== "Command line"

    ```bash
    canvodpy vod --site ExampleSite --analysis canopy_01_vs_reference_01 \
        --start 2025001 --end 2025031
    ```

    The command runs `site.vod.compute_days` for whole days, from
    `--start` to `--end`; without them, for every day of the GNSS store.
    It lists the days without VOD.

A day can end up in the GNSS store but not in the VOD store, for example
when writing the VOD failed. `canvodpy run` warns about such days. To
list them and compute their VOD:

```bash
canvodpy vod-reconcile --site ExampleSite --analysis canopy_01_vs_reference_01
canvodpy vod-reconcile --site ExampleSite --analysis canopy_01_vs_reference_01 --execute
```

The [VOD package page](../packages/vod/overview.md) describes the VOD
model and its output.

!!! example "Try it in a notebook"

    Open [VOD retrieval](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/10_vod_retrieval.py?mode=edit) in molab, the online notebook service of marimo.

---

## What only the command line does

`canvodpy run` adds a few steps around `Site.pipeline()`:

- It chooses the days when you leave out `--start` or `--end`; see
  [Which days a run processes](#which-days-a-run-processes).
- Before processing, it stops if a VOD store group holds VOD computed
  from data with other [preprocessing settings](configuration.md).
  In Python, `site.vod` makes the same check when it writes.
- It warns about days that are in the GNSS store but not in the VOD
  store.
- If the VOD of a unit of days fails, it says which days are left
  without VOD and continues. `pipeline.run()` does the same and reports
  the error in `RunUnit.vod_error`.
- It shows the progress per site and receiver.

---

## Scheduled runs

To process new data every day, schedule `canvodpy run` without
`--start` and `--end`, for example with cron at 03:00:

```bash
0 3 * * * /path/to/canvodpy run --site ExampleSite --config-dir /path/to/config
```

Cron runs with a minimal environment, so give the full path to
`canvodpy` (`which canvodpy` prints it) and to the settings folder.
A scheduler can check the exit code: 3 means some receiver-days failed.

For [Apache Airflow](https://airflow.apache.org/), `check_day` and
`process_day` in `canvodpy.workflows.tasks` run the code of
`canvodpy run` for one site and day. `process_day` raises an error when
a receiver-day failed, so Airflow retries the task. Ready-made Airflow DAGs are an
optional extension; see [Optional extensions](extensions.md).

!!! example "Try it in a notebook"

    Open [API overview](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/17_api_overview.py?mode=edit) in molab, the online notebook service of marimo.

---

**Next in the trail:** [configuration](configuration.md) · [parallel processing](parallel-processing.md) · [architecture](../architecture.md)
