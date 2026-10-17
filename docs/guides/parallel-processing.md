---
title: Parallel processing
description: How a run spreads the files over worker processes, and the settings that limit its CPU and memory use
---

# Parallel processing

A run reads many files: one or more per receiver and day. canVODpy reads
and writes them in parallel worker processes and commits each day to the
store once. This page explains how a run divides the work and which
settings limit its use of the machine.

---

## How a run divides the work

A run works through the days in batches of `days_per_batch` days. Each
batch goes through three steps, and the batches overlap: while the
workers read one batch, the next batch is prepared, and while its days
go to VOD, the workers read the next batch.

```text
 days of one batch
        │
        ▼   one thread per day
 1. Prepare: orbit and clock data, receiver positions
        │
        ▼   one task per file, in date order
 2. Read and write: worker processes read the files and
        │   write them into forks of the day
        ▼   as soon as all tasks of a day are done
 3. Commit: the forks of the day go into the GNSS store, one commit
        │
        ▼   when the whole batch is written
 the days go to VOD (canvodpy run) or to your loop (Python)
```

1. **Prepare.** Each day of the batch gets its orbit and clock data,
   downloaded and interpolated or taken from the cache, and the receiver
   positions. The days of a batch are prepared at the same time, one
   thread per day.
2. **Read and write.** A task for the worker processes holds the files
   of one receiver that share an epoch chunk of the store; with
   [preprocessing](configuration.md) set, all files of a receiver and
   day, since a time bin can span two files. The worker reads the files,
   applies the preprocessing (if set), checks for data already in the
   store, and writes the files into their places in the day's
   [day blocks](../packages/store/overview.md), in its own fork of the
   store. No two tasks write the same chunk. The tasks go out in date
   order and alternate between the receivers, so all receivers of a day
   finish at about the same time. At most twice as many tasks as workers
   wait at a time.
3. **Commit.** As soon as all tasks of a day are done, a thread of the
   main process merges their forks and commits the day, once per store.
   It also writes the few files whose epochs reach beyond their task's
   chunks. The workers keep reading meanwhile. If another run committed
   to the store first, the day is read and written again on top of it.
   The first day of a new store, or of a receiver new to the store, is
   read by the workers and written by the main process, since that day
   creates the store's arrays; the
   [Storage](../packages/store/overview.md) page describes the checks for
   duplicate data.

When the whole batch is written, `canvodpy run` computes the VOD of its
days; in Python, `process_range` hands the days to your loop. Meanwhile
the run goes on with the next batch, which was prepared while this one
was read, so the workers don't wait for the VOD or for the preparing.
The run goes one batch ahead at most: it waits when a whole batch waits
for VOD or for your loop. So the data of two batches can be in memory at
the same time, the one going to VOD and the one being read.

If VOD or your loop stops with an error, the run stops too: the day
being written is committed, the files still being read are dropped, and
the error is raised. Days already written stay in the store; the next
run writes the rest. A day whose preparing fails, other than a missing
orbit or clock file, is reported as failed for each receiver.

A larger `days_per_batch` prepares more days at the same time. It also
downloads the orbit and clock files of all these days at the same time,
which can cause connection problems with the download server, and holds
more days in memory.

---

## The worker processes

The workers are a reusable process pool of
[loky](https://loky.readthedocs.io/), a dependency of canVODpy. They start
with the first batch and stay for the next batches, so Python and the
scientific libraries are loaded once per worker, not once per day.

Before the first file is read, the run prepares the first batch. On a
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
        days_per_batch: 1
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
        days_per_batch: 1
    ```

| Setting | Default | Meaning |
|---|---|---|
| `resource_mode` | `auto` | `auto` chooses the number of workers; `manual` uses the settings below. |
| `n_max_threads` | none | Most worker processes, 1 to 100; fewer run if they do not fit in the [memory budget](#memory-use). Required with `manual`; `auto` ignores it and warns. |
| `auto_uncapped` | `false` | With `auto`: one worker per CPU thread, instead of one per physical core with two threads left free. |
| `days_per_batch` | `1` | Days per batch, 1 to 30. Lowered if the days do not fit in the [memory budget](#memory-use). |
| `threads_per_worker` | none (1) | Threads that numerical libraries such as OpenBLAS and MKL use in each worker, 1 to 8. If you set `OMP_NUM_THREADS` or a similar variable yourself, your value applies. |
| `cpu_affinity` | none | With `manual`: the CPU cores the workers run on. Works on Linux and Windows; macOS ignores it. |
| `nice_priority` | `-5` | With `manual`: the [nice value](https://en.wikipedia.org/wiki/Nice_(Unix)) added to the workers' priority, from -20 (highest) to 19 (lowest). Only an administrator can set a negative value; for other users the workers keep the normal priority. With `auto`, the run always tries -5. |

On a server you share with others, use `manual` with at most half of the
CPU cores and a positive `nice_priority`, such as 10, so the run gives way
to other programs.

### From the command line and from Python

`canvodpy run --workers` and `--days-per-batch` override the settings for
one run. In Python, `site.pipeline()` takes `n_workers`, `days_per_batch`,
`max_memory_gb` and `threads_per_worker`. Setting the number of workers this way replaces
the choice of `resource_mode: auto`. The workers' CPU cores and priority
always come from the settings file.

---

## Memory use

A run fits its memory budget: `max_memory_gb` under `processing.params`,
or, without it, the memory available when the run starts. The budget
holds two things:

- **The main process:** what it holds at the start, plus the data of the
  days in flight. Since the run goes one batch ahead, that is two batches
  of `days_per_batch` days.
- **The workers:** each holds Python and its libraries, about 0.3 GB,
  plus the files of its largest task while it reads them. A task reads
  the files of one receiver that share an epoch chunk; with
  [preprocessing](configuration.md) set, all files of a receiver and day.
  A reference receiver paired with several canopy receivers counts once
  for each pairing.

Before it reads a file, the run estimates both from the size of the
files and sets

```text
workers = min(worker cap, (budget - main process) / largest task)
```

The worker cap is `n_max_threads` with `manual` (or `--workers`), and
the CPU cores minus two with `auto`. If the days of a batch leave no room
for one worker, the run lowers `days_per_batch` until one fits. If one
worker does not fit even with one day per batch, the run stops before it
reads a file and says how much memory it needs.

```yaml
processing:
  params:
    max_memory_gb: 8   # this run uses at most about 8 GB
```

| Setting | Default | Meaning |
|---|---|---|
| `max_memory_gb` | none | Memory budget of a run in GB. Without it, the memory available when the run starts. With `auto` and `manual` alike. In Python, `site.pipeline(max_memory_gb=...)`. |

The estimates come from factors measured on the test data, with a
margin: a worker task needs about 45 times the size of its RINEX v3
files, 100 times for RINEX v2, 25 times for SBF and 15 times for NMEA;
the main process holds about the size of a day's files for each day in
flight. The run writes its sizes to the log (`memory_budget`), as a
warning when the budget lowered the workers or `days_per_batch`. After
each task, the worker writes its memory before the task and its peak
during the task (`worker_memory_peak`), so you can check the estimates
on your data and set the budget.

The run also writes the memory use of the machine to the log before each
batch (`memory_stats`). Every run also writes memory, CPU, and disk use
every 30 seconds (`resource_sample`) to the log; the run history keeps
the same samples. [Diagnostics](diagnostics.md) describes both.

---

**Next in the trail:** [diagnostics](diagnostics.md) · [configuration](configuration.md) · [architecture](../architecture.md)
