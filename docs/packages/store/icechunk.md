---
title: Versioning with Icechunk
description: The Icechunk format of the stores, chunks, the Icechunk settings, and reading earlier states of a store.
---

# Versioning with Icechunk

The GNSS store and the VOD store are [Icechunk](https://icechunk.io/)
repositories. Icechunk stores Zarr v3 arrays and records every write as a
commit, with a snapshot ID. A store keeps its earlier snapshots until they
are expired, so you can read the state of a store at an earlier commit.

This page describes the store format, the chunks, and the Icechunk settings,
and how to read history and earlier states.

## What's on disk

canVODpy creates stores in Icechunk format version 2 and requires
`icechunk>=2.0.0`. A store is a directory:

```text
rinex/
├── repo           # branches, tags, and the list of snapshots
├── snapshots/     # one file per snapshot
├── transactions/  # the changes of each commit
├── manifests/     # where each chunk is stored
├── chunks/        # chunk data, once data larger than the inline threshold is written
└── overwritten/   # earlier versions of the repo file
```

Don't change these files by hand; use the store's methods or
`canvodpy store`.

canVODpy opens stores on a local or network file system. Icechunk can also
store repositories in object storage, such as S3, but canVODpy doesn't
open them there.

## Chunks

A Zarr array is stored in chunks: the unit that is read, compressed, and
written. The default chunk shapes are:

| Store | Chunk shape | Size in epochs |
|---|---|---|
| GNSS store | `{"epoch": 180, "sid": -1}` | one 15-minute file at a 5 s sampling interval ($900\,\text{s} / 5\,\text{s}$) |
| VOD store | `{"epoch": 17280, "sid": -1}` | one day at a 5 s sampling interval ($86400\,\text{s} / 5\,\text{s}$) |

`sid: -1` puts all signals in one chunk.

!!! warning "Match the epoch chunk size to what a run writes"
    A run adds one file at a time to the GNSS store and one day at a time
    to the VOD store. An addition that ends inside a chunk rewrites that
    whole chunk the next time. Set the epoch chunk sizes to:

    $$
    \text{GNSS store: } \frac{\text{file length in s}}{\text{sampling interval in s}}
    \qquad
    \text{VOD store: } \frac{86400\,\text{s}}{\text{sampling interval in s}}
    $$

    For example, 15-minute files at a 2.5 s interval need `epoch: 360` in
    the GNSS store and `epoch: 34560` in the VOD store.

    Set `processing.icechunk.chunk_strategies` before the first write of a
    group: a group keeps the chunk shape it was created with. To change the
    chunks of an existing group, use `store.rechunk_group()`.

!!! note "GNSS stores created before 1.0.0b1"
    Before 1.0.0b1, the GNSS store default was `epoch: 17280`. Groups
    created then keep those chunks: reads work as before, but every file a
    run adds rewrites the last chunk. To change a group to the current
    default:

    ```python
    store.rechunk_group("canopy_01", {"epoch": 180, "sid": -1})
    ```

`chunk_strategies` has exactly two keys, `gnss_store` and `vod_store`. A
store that you leave out keeps the default, and any other key fails
validation. A store that you set needs `epoch`; `sid` defaults to `-1`.

### Reads are lazy

`read_group()` opens a group with `xarray.open_zarr()`, so every data
variable is a Dask array. Nothing is read until a value is needed (for
example `.compute()`, `.values`, or a plot), and then only the chunks the
result needs.

With the default `sid: -1`, a chunk holds all signals, so one signal over a
year reads 365 chunks of the VOD store and 35,040 of the GNSS store. If you
read single signals over long periods, rechunk along `sid` with
`rechunk_group()`.

`read_group()` returns Dask chunks equal to the chunks on disk, whatever
`chunk_strategies` says now. Its `chunks` argument sets other Dask chunks
for the returned dataset; it doesn't change the chunks on disk:

```python
ds = store.read_group(
    "canopy_01",
    time_slice=slice("2024-01-01", "2024-01-31"),
    chunks={"epoch": 3600, "sid": -1},
)
```

Variables that you compute from a read and add with
`add_group_variables()` are rechunked to the group's chunks before they are
written.

## Settings

The Icechunk settings are under `processing.icechunk` in
`canvod-settings.yaml`:

```yaml
processing:
  icechunk:
    compression_level: 3
    chunk_strategies:
      gnss_store:
        epoch: 180
        sid: -1
      vod_store:
        epoch: 17280
        sid: -1
    manifest_splitting_enabled: true
    manifest_splitting_epoch_range: 17280
```

Every setting is optional. A setting of `null` leaves the value to
Icechunk or Zarr; the table names their defaults for Icechunk 2.3 and Zarr
3.4.

| Setting | Default | Description |
|---|---|---|
| `compression_algorithm` | `zstd` | The only algorithm Icechunk 2 offers. |
| `compression_level` | `3` | Zstandard level, 0 to 22. |
| `inline_chunk_threshold_bytes` | `512` | Chunks up to this size are stored in the manifest instead of in `chunks/`. |
| `get_partial_values_concurrency` | `1` | Concurrent requests when reading part of a chunk. |
| `max_concurrent_requests` | `null` | Limit on concurrent storage requests. |
| `zarr_async_concurrency` | `null` | Limit on the concurrent chunk reads and writes of Zarr per array; `null` keeps Zarr's default of 10. On a network-mounted store (CIFS or NFS) that drops connections during writes, set a lower value; writes get slower. |
| `chunk_strategies` | see [Chunks](#chunks) | Chunk shape per store. |
| `manifest_splitting_enabled` | `true` | Splits manifests along `epoch` every `manifest_splitting_epoch_range` epoch chunks. |
| `manifest_splitting_epoch_range` | `17280` | Epoch chunks per manifest. The value counts chunks, not epochs: with the default chunks, a GNSS store manifest covers $17280 \times 180$ epochs (180 days at 5 s). |
| `manifest_preload_enabled` | `false` | Reads the manifests of matching arrays when a store is opened. |
| `manifest_preload_max_refs` | `10000` | Limit on the chunk references read in advance. |
| `manifest_preload_max_arrays_to_scan` | `500` | Limit on the arrays checked for reading in advance. |
| `manifest_preload_pattern` | `^(epoch\|sid)$` | Regular expression for the names of the arrays to read in advance. |
| `cache_num_chunk_refs` | `null` | Number of chunk references Icechunk keeps in memory; Icechunk's default is 15,000,000. |
| `cache_num_bytes_chunks` | `null` | Bytes of chunk data Icechunk keeps in memory; Icechunk's default is 0. |
| `num_updates_per_repo_info_file` | `null` | Number of updates that share one `repo` file before Icechunk starts a new one. |
| `repo_update_max_tries` | `null` | Attempts to update the `repo` file; Icechunk's default is 100. |
| `repo_update_initial_backoff_ms` | `null` | First wait between attempts; Icechunk's default is 50 ms. |
| `repo_update_max_backoff_ms` | `null` | Longest wait between attempts; Icechunk's default is 30,000 ms. |

## History

```python
from canvodpy import Site

store = Site("ExampleSite").gnss_store

# Commits on main, newest first
for entry in store.get_history(limit=20):
    print(entry["snapshot_id"][:8], entry["written_at"], entry["commit_msg"])
store.print_history(limit=20)

# Commit graph: SVG in a notebook, colored text in a terminal
store.plot_commit_graph()

# Operations on the store: commits, branch operations, expiry, garbage collection
store.print_ops_log(limit=30)

# One snapshot, or the difference between two
store.get_snapshot_info(snapshot_id)
store.compare_snapshots(snapshot_id_1, snapshot_id_2)
```

## Read an earlier state

To read a store as it was at an earlier commit, create a branch at that
snapshot and read from the branch:

```python
store.create_branch("before_reprocessing", snapshot_id)
ds = store.read_group("canopy_01", branch="before_reprocessing")
```

A snapshot stays readable until it's expired. `canvodpy store maintain`
expires old snapshots and collects garbage; without `--execute`, it only
reports what it would delete.

## File hash

The `File Hash` attribute of a stored file, and the hash in the log book,
come from the reader's `file_hash`: the first 16 characters of the SHA-256
hex digest of the file.
