# Parallel Processing & Resource Management

canVODpy processes many GNSS observation files per site — one per receiver per day,
sometimes split into sub-daily intervals. Running these sequentially on a single
core would be prohibitively slow for multi-year datasets. This page explains how
canVODpy distributes that work and how to configure resource limits for your machine.

---

## The parallelism model

canVODpy uses Python's standard `concurrent.futures.ThreadPoolExecutor` at the outer
level and a **persistent [loky](https://loky.readthedocs.io/) process pool** at the
inner level — no external scheduler required. The pipeline applies two levels of
parallelism:

```
┌─────────────────────────────────────────┐
│  ThreadPoolExecutor (Wave A / Wave B)   │  ← receivers processed concurrently
│  ┌──────────────┐  ┌──────────────┐     │
│  │  Receiver A  │  │  Receiver B  │     │
│  │ ─────────── │  │ ─────────── │     │
│  │  loky pool  │  │  loky pool  │     │
│  │(file parse) │  │(file parse) │     │
│  └──────────────┘  └──────────────┘     │
└─────────────────────────────────────────┘
           │
           ▼  (sequential)
   Icechunk store  ←  one commit per receiver-day
```

**Wave A/B**: the outer `ThreadPoolExecutor` runs two groups of receivers
concurrently. Within each receiver, a persistent loky pool parses individual GNSS
files in parallel using **flat LPT scheduling** — all tasks are submitted upfront
and workers pick them up in Longest Processing Time order, which keeps CPU utilisation
high across unevenly-sized files.

**Sequential writes**: Icechunk on a local filesystem cannot accept concurrent
commits. Every write is performed sequentially after parsing completes, with one
commit per receiver-day. This is a hard constraint of the local storage model
and ensures data integrity through Icechunk's snapshot mechanism.

### Why loky instead of standard ProcessPoolExecutor?

Python's built-in `ProcessPoolExecutor` re-spawns a fresh worker pool on each call.
For a pipeline that processes hundreds of files across many days, the cost of
importing Python and all scientific dependencies (numpy, xarray, icechunk, …) into
fresh processes on every batch dominates wall time.

**loky** (`pip install loky`, also the backend behind [joblib](https://joblib.readthedocs.io/))
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
        days_per_batch: 1         # days processed per commit
    ```

### Configuration reference

| Field | Default | Description |
|-------|---------|-------------|
| `resource_mode` | `auto` | `auto` (detect cores/memory) or `manual` (hard caps) |
| `n_max_threads` | — | Worker process count. Required when `resource_mode=manual` |
| `max_memory_gb` | — | Soft RAM limit in GB. Manual mode only |
| `days_per_batch` | `1` | Days of data per processing batch and Icechunk commit |
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

Each receiver-day produces one Icechunk commit. This maps directly to the three-layer
deduplication guard built into `canvod-store`:

1. **Hash match** — identical file content is never written twice
2. **Temporal overlap** — a new batch that overlaps existing epochs is rejected
3. **Intra-batch overlap** — duplicate epochs within a single batch are caught before writing

These checks run before every write, regardless of parallelism settings. A failed
write leaves the store unchanged — Icechunk's snapshot model means partial writes
are never committed.

---

!!! example "Try it"
    [20 · Batch Processing](../notebooks/_build/20_workflow_batch_processing.html){target=_blank}
    · [view source on molab](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/20_workflow_batch_processing.py)
