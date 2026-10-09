# Parallel Processing & Resource Management

canVODpy processes many GNSS observation files per site — one per receiver per day,
sometimes split into sub-daily intervals. Running these sequentially on a single
core would be prohibitively slow for multi-year datasets. This page explains how
canVODpy distributes that work and how to configure resource limits for your machine.

---

## The parallelism model

canVODpy reads files in a **persistent [loky](https://loky.readthedocs.io/)
process pool** — no external scheduler required — and writes from a single
process. A run works through the days in batches of `days_per_batch` days:

```
 days of one batch (days_per_batch)
 ┌───────────────────────────────────────────────┐
 │ per day, one thread each: orbit/clock         │  ← preparing
 │ interpolation, receiver positions             │
 └───────────────────────┬───────────────────────┘
                         ▼
 files of all receivers, in date order, round-robin across receivers
                         ▼
        loky process pool (one task per file)       ← parallel reading
                         │
                         ▼  as soon as all files of a receiver-day are read
        one writer: preprocessing (if set),          ← serial writing
        dedup checks, Icechunk write
                         │
                         ▼  when the batch is written
        VOD per day                                  ← serial VOD
```

**Preparing**: each day of the batch first gets its orbit and clock
interpolation (or takes it from the cache) and the receiver positions, one
thread per day.

**Reading**: all files of the batch are submitted to the shared pool, one
task per file, in date order and round-robin across receivers, so every receiver
makes progress and results of one day arrive together. At most twice as many
tasks as workers are in flight at a time.

**Writing**: a receiver-day is written as soon as all its files are read, while
the pool keeps reading. One process writes: it applies the preprocessing (if
set), runs the deduplication checks and writes the receiver-day with one commit
for its data (with `overwrite` on a temporary branch, then promoted) and one for
the store metadata. Icechunk on a local or network file system cannot detect two
commits at the same time, so this is a hard constraint of the local storage
model, and it keeps the deduplication checks consistent.

**VOD**: when all receiver-days of the batch are written, VOD is computed day by
day in the same process, and each day is written with one commit for the results
and one for the store metadata. The next batch starts after that, so the pool
waits while a batch is prepared and while its VOD is computed. The days of a
batch are prepared at the same time, so a larger `days_per_batch` shortens the
preparing wait per day; the VOD wait grows with the number of days either way.

### Why loky instead of standard ProcessPoolExecutor?

Python's built-in `ProcessPoolExecutor` re-spawns a fresh worker pool on each call.
For a pipeline that processes hundreds of files across many days, the cost of
importing Python and all scientific dependencies (numpy, xarray, icechunk, …) into
fresh processes on every batch dominates wall time.

**loky** (a canvodpy dependency, also the backend behind [joblib](https://joblib.readthedocs.io/))
provides a **reusable process pool** that stays alive between batches:

- Workers are started once at pipeline launch and reused across all tasks.
- Module imports pay their cost exactly once per worker, not once per day.
- The pool is shared across the run, not created and destroyed per receiver-day.

This makes the overhead of spawning scale with the number of workers (a one-time cost),
not with the number of files or days being processed.

!!! note "The first minute or two of a run can look idle"
    A run's initial "warm-up" — before the first files start visibly
    processing — can take a minute or more on a cold start. Besides the
    scientific-dependency imports above, this window also covers one-time
    setup work (e.g. database/index creation) that only happens once per
    worker lifetime, not per file or per day. This is expected, not a hang —
    give it a couple of minutes before assuming something is stuck.

!!! note "Reading from the store is always fast"
    `xarray.open_zarr()` loads only the array chunks you actually access — the
    full dataset is never read into memory at once.

---

## Configuration

Resource limits are set under `processing.params` in your `canvod-settings.yaml`:

=== "Automatic (local machine)"

    canVODpy detects available cores and memory automatically:

    ```yaml
    processing:
      params:
        resource_mode: auto
        days_per_batch: 1
    ```

=== "Manual (shared server / HPC)"

    Hard caps prevent the pipeline from monopolising shared resources:

    ```yaml
    processing:
      params:
        resource_mode: manual
        n_max_threads: 4          # number of worker processes
        max_memory_gb: 16         # soft RAM limit across all workers
        cpu_affinity: [0, 1, 2, 3]  # pin to specific CPU cores (Linux only)
        nice_priority: 10         # lower process priority (0=normal, 19=lowest)
        days_per_batch: 1         # days whose files are read together
    ```

### Configuration reference

| Field | Default | Description |
|-------|---------|-------------|
| `resource_mode` | `auto` | `auto` (detect cores/memory) or `manual` (hard caps) |
| `n_max_threads` | — | Worker process count. Required when `resource_mode=manual` |
| `max_memory_gb` | — | Soft RAM limit in GB. Manual mode only |
| `days_per_batch` | `1` | Days whose files are submitted to the worker pool together (1–30) |
| `cpu_affinity` | — | CPU core IDs to pin workers to (Linux only) |
| `nice_priority` | `0` | Process priority: 0 = normal, 19 = lowest |

!!! tip "Shared servers"
    On a machine shared with colleagues, set `resource_mode: manual` with
    `n_max_threads` ≤ half the available cores and `nice_priority: 10`.
    This ensures interactive work on the same server is not disrupted.

---

## Memory monitoring

`MemoryMonitor` logs system memory usage at key points during a pipeline run.
It does not enforce limits — that is handled by the OS and the `max_memory_gb`
cap on worker processes. Logs are written to the configured logging output and
can be inspected to diagnose out-of-memory failures on constrained machines.

---

## Write granularity and data integrity

Writes are per receiver-day (see above). Before every write, the three-layer
deduplication guard runs:

1. **Hash match** — identical file content is never written twice
2. **Temporal overlap** — a file overlapping already-stored epochs is not written
   (default `skip`) or replaces them (`overwrite`)
3. **Intra-batch overlap** — two files of one batch covering the same time are caught before writing

These checks run before every write, regardless of parallelism settings. A failed
write leaves the store unchanged — Icechunk's snapshot model means partial writes
are never committed.
