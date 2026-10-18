---
title: Parallel processing
description: How a run spreads the files over worker processes, and the settings that limit its CPU and memory use
---

# Parallel processing

A run reads many files: one or more per receiver and day. canVODpy reads
and writes them in parallel worker processes and commits them to the
store in units of days, once per unit. This page explains how a run divides the work and which
settings limit its use of the machine.

---

## How a run divides the work

A run works through the days in units of several days. The run sizes
the units itself (see [Memory use](#memory-use)): as many days as the
memory budget holds, at most 31; a run of one new day is a unit of one
day. Each unit goes through three steps, and the units overlap: while
the workers read one unit, the next unit is prepared, and while its days
go to VOD, the workers read the next unit.

```text
 days of one unit
        │
        ▼   one thread per day
 1. Prepare: orbit and clock data, receiver positions
        │
        ▼   one task per group of files, in date order
 2. Read and write: worker processes read the files and
        │   write them into forks of the unit
        ▼   when all tasks of the unit are done
 3. Commit: the forks of the unit go into the GNSS store, one commit
        │
        ▼
 the days go to VOD (canvodpy run) or to your loop (Python)
```

1. **Prepare.** Each day of the unit gets its orbit and clock data,
   downloaded and interpolated or taken from the cache, and the receiver
   positions. Up to four days of a unit are prepared at the same time,
   one thread per day, so that the download server gets at most four
   requests at once. A day whose orbit and clock files are not out yet is
   left out of the unit and stays open for the next run; the other days
   go on.
2. **Read and write.** A task for the worker processes holds the files
   of one receiver that share an epoch chunk of the store. With
   [preprocessing](configuration.md) set, the chunks are those of the
   aggregated epochs: a time bin is one of their slots, so files whose
   epochs fall into one bin are in one task. The worker reads the files,
   applies the preprocessing (if set), checks for data already in the
   store, and writes the files into their places in the day's
   [day blocks](../packages/store/overview.md), in its own fork of the
   store. No two tasks write the same chunk. The tasks go out in date
   order and alternate between the receivers, so all receivers of a day
   finish at about the same time. At most twice as many tasks as workers
   wait at a time.
3. **Commit.** When all tasks of the unit are done, a thread of the
   main process merges their forks and commits the unit, once per store.
   It also writes the few files whose epochs reach beyond their task's
   chunks. A file that fails gets no entry in the store's log book, so
   the next run tries it again; the other files and days are committed.
   The commit itself is one for the whole unit: if it fails (a store
   error, or other runs keep committing first through all tries), every
   day of the unit is reported as failed and the next run writes them.
   If another run committed to the store first, the unit is read and
   written again on top of it. The first day of a new store is a unit of
   its own, and the first day of a receiver new to the store is read by
   the workers and written by the main process, since that day creates
   the store's arrays; the [Storage](../packages/store/overview.md) page
   describes the checks for duplicate data.

When the unit is committed, `canvodpy run` (and `pipeline.run()` in
Python) computes the VOD of its days: one task per receiver pair and
day in the same worker processes, each reading its day from the GNSS
store, and one commit of the VOD store for the unit. Nothing is read
back for VOD while the observations are written. A day that failed gets
no VOD and stays open for the next run; if the VOD of a unit fails, the
run says which days are left without VOD and goes on (`canvodpy
vod-reconcile` computes them later). In Python, `process_range` instead
reads each day back and hands it to your loop.

Meanwhile the run goes on with the next unit, which was prepared while
this one was read, so the workers don't wait for the preparing. The
preparing of the next unit starts once this unit's day blocks are added
to the store (a small commit before the tasks go out): next to the
preparing, that commit took many times as long. The run
goes one unit ahead at most: it waits when a whole unit waits for its
VOD or for your loop. So the data of two units can be in memory at the
same time.

If your loop stops with an error, the run stops too: the unit being
committed is committed, the files still being read are dropped, and the
error is raised. Days already written stay in the store; the next run
writes the rest. A day whose preparing fails, other than a
missing orbit or clock file, is reported as failed for each receiver.

---

## The worker processes

The workers are a reusable process pool of
[loky](https://loky.readthedocs.io/), a dependency of canVODpy. They start
with the first unit and stay for the next units, so Python and the
scientific libraries are loaded once per worker, not once per day.

Before the first file is read, the run prepares the first unit. On a
first run this includes downloading the orbit and clock files, so the
first minutes of a run can look idle.

The workers are shared by all pipelines in one Python session, and
`Pipeline.close()` leaves them running. They stop after 15 minutes
without work, or when Python exits.

---

## Settings

The settings are under `processing.params` in `canvod-settings.yaml`.
`resource_mode` decides which of them a run uses.

=== "Automatic"

    ```yaml
    processing:
      params:
        resource_mode: auto
    ```

    The run starts one worker per physical CPU core, but leaves at least
    two of the CPU threads free for the operating system, and starts at
    least one worker; fewer if they do not fit in the
    [memory budget](#memory-use). A second thread per core
    (hyper-threading, SMT) would add a worker process and its memory, not
    speed. With `auto_uncapped: true` the run uses all CPU threads; use
    that only on a machine nobody else uses.

=== "Manual, for shared servers"

    ```yaml
    processing:
      params:
        resource_mode: manual
        n_max_threads: 4            # number of worker processes
        cpu_affinity: [0, 1, 2, 3]  # CPU cores the workers run on
        nice_priority: 10           # lower priority than other programs
    ```

| Setting | Default | Meaning |
|---|---|---|
| `resource_mode` | `auto` | `auto` chooses the number of workers; `manual` uses the settings below. |
| `n_max_threads` | none | Most worker processes, 1 to 100; fewer run if they do not fit in the [memory budget](#memory-use). Required with `manual`; `auto` ignores it and warns. |
| `auto_uncapped` | `false` | With `auto`: one worker per CPU thread, instead of one per physical core with two threads left free. |
| `threads_per_worker` | none (1) | Threads that numerical libraries such as OpenBLAS and MKL use in each worker, 1 to 8. If you set `OMP_NUM_THREADS` or a similar variable yourself, your value applies. |
| `cpu_affinity` | none | With `manual`: the CPU cores the workers run on. Works on Linux and Windows; macOS ignores it. |
| `nice_priority` | `-5` | With `manual`: the [nice value](https://en.wikipedia.org/wiki/Nice_(Unix)) added to the workers' priority, from -20 (highest) to 19 (lowest). Only an administrator can set a negative value; for other users the workers keep the normal priority. With `auto`, the run always tries -5. |

On a server you share with others, use `manual` with at most half of the
CPU cores and a positive `nice_priority`, such as 10, so the run gives way
to other programs.

### From the command line and from Python

`canvodpy run --workers` overrides the settings for one run. In Python,
`site.pipeline()` takes `n_workers`, `max_memory_gb` and
`threads_per_worker`. Setting the number of workers this way replaces
the choice of `resource_mode: auto`. The workers' CPU cores and priority
always come from the settings file.

---

## Memory use

A run fits its memory budget: `max_memory_gb` under `processing.params`,
or, without it, the memory available when the run starts. The budget
holds two things:

- **The main process:** what it holds at the start, plus the data of the
  days in flight. Since the run goes one unit ahead, that is two units of
  days.
- **The workers:** each holds Python and its libraries, about 0.3 GB,
  plus its largest task. A task reads the files of one receiver that
  share an epoch chunk, one after the other, and holds their data until
  it writes them. A reference receiver paired with several canopy
  receivers counts once for each pairing.

Before it reads a file, the run estimates both from the size of the
files. The workers come first:

```text
workers = min(worker cap, (budget - main process with one day) / largest task)
```

The worker cap is `n_max_threads` with `manual` (or `--workers`), and
the CPU cores minus two with `auto`. A unit then gets as many days as
the rest of the budget holds, at most 31 and at most the days the run
has. Larger units spread the main process's work per unit (the growth of
the day blocks, the commit) over more days; the limit of 31 keeps what
a crash or a lost conflict costs small. If one worker does not fit even
with one day, the run stops before it reads a file and says how much
memory it needs.

```yaml
processing:
  params:
    max_memory_gb: 8   # this run uses at most about 8 GB
```

| Setting | Default | Meaning |
|---|---|---|
| `max_memory_gb` | none | Memory budget of a run in GB. Without it, the memory available when the run starts. With `auto` and `manual` alike. In Python, `site.pipeline(max_memory_gb=...)`. |

The estimates come from factors measured on the test data, with a
margin: reading a file needs about 45 times its size for RINEX v3, 100
times for RINEX v2, 25 times for SBF and 15 times for NMEA, and a task
holds about the size of its files once read; the main process holds
about the size of a day's files for each day in flight. The run writes
its sizes to the log (`memory_budget`): the workers, the days per unit
(`unit_days`) and what set them (`unit_limit`: `memory`,
`max_unit_days`, `days_to_run`, or the deprecated `days_per_batch`),
the tasks per day and per worker, as a warning when the budget lowered
the workers or the days per unit. After
each task, the worker writes its memory before the task and its peak
during the task (`worker_memory_peak`), so you can check the estimates
on your data and set the budget. The VOD phase's tasks log the same
event, with `task` set to `compute_vod_into_fork` and `input_mb` 0,
since they read from the GNSS store, not from files.

The run also writes the memory use of the machine to the log before each
unit (`memory_stats`). Every run also writes memory, CPU, and disk use
every 30 seconds (`resource_sample`) to the log; the run history keeps
the same samples. [Diagnostics](diagnostics.md) describes both.

---

**Next in the trail:** [diagnostics](diagnostics.md) · [configuration](configuration.md) · [architecture](../architecture.md)
