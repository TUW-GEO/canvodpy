---
title: Parallel processing
description: How a run spreads the files over worker processes, and the settings that limit its CPU use
---

# Parallel processing

A run reads many files: one or more per receiver and day. canVODpy reads
them in parallel worker processes and writes the results from one
process. This page explains how a run divides the work and which
settings limit its use of the machine.

---

## How a run divides the work

A run works through the days in batches of `days_per_batch` days. Each
batch goes through three steps:

```text
 days of one batch
        │
        ▼   one thread per day
 1. Prepare: orbit and clock data, receiver positions
        │
        ▼   one task per file, in date order
 2. Read: worker processes read the files
        │
        ▼   as soon as all files of a receiver and day are read
 3. Write: one process writes the GNSS store
        │
        ▼   when the whole batch is written
 the days go to VOD (canvodpy run) or to your loop (Python)
```

1. **Prepare.** Each day of the batch gets its orbit and clock data,
   downloaded and interpolated or taken from the cache, and the receiver
   positions. The days of a batch are prepared at the same time, one
   thread per day.
2. **Read.** Each file is one task for the worker processes. The tasks
   go out in date order and alternate between the receivers, so all
   receivers of a day finish at about the same time. At most twice as
   many tasks as workers wait at a time.
3. **Write.** As soon as all files of one receiver and day are read, the
   main process applies the [preprocessing](configuration.md) (if set),
   checks for data that is already in the store, and writes the day. The
   workers keep reading meanwhile. Only one process writes, so the checks
   for duplicate data always see the current store; the
   [Storage](../packages/store/overview.md) page describes these checks.

When the whole batch is written, `canvodpy run` computes the VOD of its
days; in Python, `process_range` hands the days to your loop. The next
batch starts after that, so the workers wait while a batch is prepared
and while its VOD is computed.

A larger `days_per_batch` prepares more days at the same time, so the
workers wait less per day. It also downloads the orbit and clock files
of all these days at the same time, which can cause connection problems
with the download server.

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

    The run starts one worker per CPU core, minus two for the operating
    system, and at least one. With `auto_uncapped: true` it uses all
    cores; use that only on a machine nobody else uses.

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
| `n_max_threads` | none | Number of worker processes, 1 to 100. Required with `manual`; `auto` ignores it and warns. |
| `auto_uncapped` | `false` | With `auto`: use all CPU cores instead of all but two. |
| `days_per_batch` | `1` | Days per batch, 1 to 30. |
| `threads_per_worker` | none (1) | Threads that numerical libraries such as OpenBLAS and MKL use in each worker, 1 to 8. If you set `OMP_NUM_THREADS` or a similar variable yourself, your value applies. |
| `cpu_affinity` | none | With `manual`: the CPU cores the workers run on. Works on Linux and Windows; macOS ignores it. |
| `nice_priority` | `-5` | With `manual`: the [nice value](https://en.wikipedia.org/wiki/Nice_(Unix)) added to the workers' priority, from -20 (highest) to 19 (lowest). Only an administrator can set a negative value; for other users the workers keep the normal priority. With `auto`, the run always tries -5. |

On a server you share with others, use `manual` with at most half of the
CPU cores and a positive `nice_priority`, such as 10, so the run gives way
to other programs.

### From the command line and from Python

`canvodpy run --workers` and `--days-per-batch` override the settings for
one run. In Python, `site.pipeline()` takes `n_workers`, `days_per_batch`
and `threads_per_worker`. Setting the number of workers this way replaces
the choice of `resource_mode: auto`. The workers' CPU cores and priority
always come from the settings file.

---

## Memory use

canVODpy doesn't limit memory. Each worker holds the files it reads, and
the main process holds the days it writes. To lower the memory a run
needs, use fewer workers or a smaller `days_per_batch`.

The run writes the memory use of the machine to the log before each
batch (`memory_stats`). `canvodpy run` also writes memory, CPU, and disk
use every 30 seconds (`resource_sample`). [Diagnostics](diagnostics.md)
describes the logs.

---

**Next in the trail:** [diagnostics](diagnostics.md) · [configuration](configuration.md) · [architecture](../architecture.md)
