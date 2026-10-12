# Icechunk Storage

Icechunk is a cloud-native transactional storage format for multidimensional arrays — Git-like versioning meets Zarr v3.

<div class="grid cards" markdown>

-   :fontawesome-solid-code-branch: &nbsp; **Versioned Writes**

    ---

    Every `commit()` produces an immutable snapshot with a hash-addressable ID.
    Roll back to any prior state with a single line.

-   :fontawesome-solid-bolt: &nbsp; **ACID Transactions**

    ---

    Multiple writes are atomic — either all succeed or none are persisted.
    No partial writes, no corrupt chunks, no reader/writer races.

-   :fontawesome-solid-cloud: &nbsp; **Cloud-Native**

    ---

    Local filesystem for development; S3, MinIO, or Cloudflare R2 for
    production. Zero code change to switch backends.

-   :fontawesome-solid-gauge-high: &nbsp; **Zarr v3 Chunks**

    ---

    Zstd-compressed chunks, O(1) epoch-range reads, compatible with
    `xarray.open_zarr()` out of the box.

</div>

---

## Why Icechunk over plain Zarr?

| Feature | Icechunk | Zarr v3 | NetCDF4 | HDF5 |
|---------|:--------:|:-------:|:-------:|:----:|
| Version control | :octicons-check-16:{ .success } | :octicons-x-16:{ .error } | :octicons-x-16:{ .error } | :octicons-x-16:{ .error } |
| Cloud-native | :octicons-check-16:{ .success } | :octicons-check-16:{ .success } | :octicons-x-16:{ .error } | :octicons-x-16:{ .error } |
| Atomic transactions | :octicons-check-16:{ .success } | :octicons-x-16:{ .error } | :octicons-x-16:{ .error } | :octicons-x-16:{ .error } |
| Chunked arrays | :octicons-check-16:{ .success } | :octicons-check-16:{ .success } | :octicons-check-16:{ .success } | :octicons-check-16:{ .success } |
| Deduplication | :octicons-check-16:{ .success } | :octicons-x-16:{ .error } | :octicons-x-16:{ .error } | :octicons-x-16:{ .error } |

---

## Storage Structure

=== "Spec v2 (icechunk ≥ 2.0)"

    ```
    stores/
      examplesite/
        rinex/
          snapshots/      # Immutable snapshot objects
          transactions/   # Transaction logs
          overwritten/    # Overwritten-chunk tracking
          chunks/         # SHA-256 addressed chunk data (once data is written)
          manifests/      # Chunk manifests (once data is written)
        vod/
          snapshots/
          transactions/
          overwritten/
          chunks/
          manifests/
    ```

=== "Spec v1 (icechunk 1.x)"

    ```
    stores/
      examplesite/
        rinex/
          refs/           # Branch and tag refs
          snapshots/      # Immutable snapshot files
          transactions/   # Transaction logs
          chunks/         # SHA-256 addressed chunk data
          manifests/      # Chunk manifests
          branch.main     # Branch pointer (file at store root)
        vod/
          refs/
          snapshots/
          transactions/
          chunks/
          manifests/
          branch.main
    ```

!!! info "Format compatibility"
    Icechunk 2.x opens v1 stores transparently — no migration required.
    Run `icechunk.upgrade_icechunk_repository(repo, dry_run=False)` to
    explicitly upgrade a store to v2 format. `scan_stores()` detects both
    layouts automatically.

---

## Chunk Strategy

=== "Default"

    The default chunk shape is tuned for daily GNSS time series:

    ```python
    chunk_strategy = {"epoch": 17280, "sid": -1}
    ```

    | Dimension | Value | Rationale |
    |-----------|-------|-----------|
    | `epoch` | 17280 | ≈ 24 h at 5 s cadence — aligned to daily processing granularity |
    | `sid` | −1 (unlimited) | All signal IDs in one chunk — VOD computes across all signals simultaneously |

=== "Memory Estimate"

    For a typical 72-SID dataset at 1 Hz:

    ```python
    # float32, 24 h × 72 SIDs
    bytes_per_chunk = 86400 * 72 * 4   # ≈ 24 MB uncompressed
    # Zstd level 5 typically achieves 4–8× for GNSS float data
    bytes_compressed ≈ 3–6 MB per chunk
    ```

=== "Custom Chunks"

    Override per read call — does not affect on-disk layout:

    ```python
    ds = reader.read(
        time_range=("2024-01-01", "2024-01-31"),
        chunks={"epoch": 3600, "sid": -1},  # 1-hour lazy chunks in memory
    )
    ```

!!! warning "Match epoch chunk size to your site's sampling rate"
    The default `epoch: 17280` is tuned for **5 s sampling** — one full day
    is `86400 s ÷ 5 s = 17280` epochs. If a site samples at a different
    rate, compute its chunk size the same way instead of using the default
    as-is:

    ```
    epoch_chunk_size = (24 h × 60 min × 60 s) × logging_rate_hz
                      = 86400 seconds/day ÷ sampling_interval_seconds
    ```

    For example, 2.5 s sampling (0.4 Hz) needs `epoch: 34560`, not `17280`.
    Chunk shape must equal **exactly one day's worth of epochs** for your
    site's actual sampling rate — `append_to_group()` commits once per day,
    so anything else (a fraction of a day, or a multiple of it) means most
    daily commits land mid-chunk and force a read-modify-write of the whole
    chunk instead of a clean append.

    Set `chunk_strategies` in `canvod-settings.yaml` to match **before** a
    group's first-ever write — chunk shape is fixed at creation and does not
    change on later config edits. An existing store needs an explicit
    `store.rechunk_group()` migration instead.

---

## Configuration

All knobs live under `processing.icechunk:` in `canvod-settings.yaml`, backed by
`IcechunkConfig` in `canvod-config`.

```yaml
# config/canvod-settings.yaml
processing:
  icechunk:
    compression_algorithm: zstd          # only valid value in icechunk ≥ 2.0
    compression_level: 3                 # 0 = off, 1–22; 3 is the recommended default
    inline_chunk_threshold_bytes: 512    # chunks ≤ this are inlined into the manifest
    get_partial_values_concurrency: 1    # concurrent range-request parallelism
    max_concurrent_requests: null        # null = icechunk picks a platform default
    zarr_async_concurrency: null         # null = zarr's own default (10); cap on
                                          # network-mounted stores (CIFS/NFS) that trip
                                          # connection-abort errors under a write burst

    chunk_strategies:
      gnss_store:
        epoch: 17280   # ≈ 24 h at 5 s cadence
        sid: -1        # no chunking along sid axis
      vod_store:
        epoch: 17280
        sid: -1

    # Manifest splitting (enabled by default; keeps manifests bounded for long deployments)
    manifest_splitting_enabled: true
    manifest_splitting_epoch_range: 17280   # match chunk_strategies epoch

    # Manifest preloading (off by default; useful for S3 read-heavy workloads)
    # manifest_preload_enabled: false
    # manifest_preload_max_refs: 10_000
    # manifest_preload_max_arrays_to_scan: 500
    # manifest_preload_pattern: "^(epoch|sid)$"

    # Chunk cache (relevant for S3; local FS uses OS page cache)
    # cache_num_chunk_refs: null
    # cache_num_bytes_chunks: null

    # Repo-info rewrite tuning (opt-in; null = icechunk's own internal defaults)
    # num_updates_per_repo_info_file: null
    # repo_update_max_tries: null
    # repo_update_initial_backoff_ms: null
    # repo_update_max_backoff_ms: null
```

| Key | Default | Description |
|-----|---------|-------------|
| `compression_algorithm` | `zstd` | Only `zstd` is supported in icechunk ≥ 2.0 |
| `compression_level` | `3` | 1 = fastest, 22 = maximum; 3 is the recommended write-heavy default |
| `inline_chunk_threshold_bytes` | `512` | Chunks ≤ this are stored inline in the manifest (coordinate arrays only) |
| `get_partial_values_concurrency` | `1` | Concurrent GET requests for partial array reads; increase for S3 |
| `max_concurrent_requests` | `null` | Global cap on concurrent object-store connections; `null` = icechunk default |
| `zarr_async_concurrency` | `null` | Cap on zarr's own async chunk write/read burst per array; `null` = zarr's default (10). Set on network-mounted stores (CIFS/NFS) hitting connection-abort errors — costs write throughput, so opt-in only |
| `chunk_strategies.*.epoch` | `17280` | Epochs per chunk; `-1` = no chunking |
| `chunk_strategies.*.sid` | `-1` | No chunking along sid axis (all SIDs in one chunk) |
| `manifest_splitting_enabled` | `true` | Split manifests every `manifest_splitting_epoch_range` indices |
| `manifest_splitting_epoch_range` | `17280` | Should match `chunk_strategies.epoch` |
| `manifest_preload_enabled` | `false` | Eagerly fetch coordinate manifests at store-open time |
| `manifest_preload_max_refs` | `10_000` | Cap on chunk refs preloaded |
| `manifest_preload_max_arrays_to_scan` | `500` | Arrays scanned during preload |
| `manifest_preload_pattern` | `^(epoch\|sid)$` | Regex for arrays to preload |
| `cache_num_chunk_refs` | `null` | LRU chunk-reference cache size; `null` = unlimited |
| `cache_num_bytes_chunks` | `null` | LRU decompressed-data cache in bytes; `null` = unlimited |
| `num_updates_per_repo_info_file` | `null` | Commits sharing one repo-info object before icechunk starts a new one; `null` = icechunk default. Lower = smaller write payloads, more read-time object fetches — tune deliberately |
| `repo_update_max_tries` | `null` | Max attempts updating the repo-info object under write contention; `null` = icechunk default (100) |
| `repo_update_initial_backoff_ms` | `null` | Initial retry backoff for repo-info updates; `null` = icechunk default (50 ms) |
| `repo_update_max_backoff_ms` | `null` | Retry backoff ceiling for repo-info updates; `null` = icechunk default (30,000 ms) |

### Migrating to S3

The storage backend (bucket, credentials, endpoint) is passed separately to
`icechunk.Repository.open(storage=...)` and is not part of `IcechunkConfig`.
Once the backend is wired up, tune these knobs in order of impact:

| Knob | Local default | Recommended S3 starting point |
|---|---|---|
| `get_partial_values_concurrency` | `1` | `10` |
| `max_concurrent_requests` | `null` | `50` |
| `cache_num_bytes_chunks` | `null` | `2_000_000_000` (2 GB) |
| `cache_num_chunk_refs` | `null` | `500_000` |
| `manifest_preload_enabled` | `false` | `true` |
| `manifest_preload_pattern` | `^(epoch\|sid)$` | `^(obs\|snr\|epoch\|sid)$` |
| `manifest_preload_max_refs` | `10_000` | `50_000` |
| `chunk_strategies.rinex_store.epoch` | `17280` | profile before changing |
| `compression_level` | `3` | `3` (no change) |
| `inline_chunk_threshold_bytes` | `512` | `512` (no change) |
| `manifest_splitting_enabled` | `true` | `true` (no change) |

---

## Usage

=== "Initialize / Open"

    ```python
    from canvod.store import MyIcechunkStore

    # Open or create (filesystem)
    store = MyIcechunkStore("/data/stores/examplesite/rinex")

    # Open existing (read-only)
    store = MyIcechunkStore("/data/stores/examplesite/rinex", read_only=True)
    ```

=== "Write with Versioning"

    ```python
    from canvod.site import Site

    site = Site("ExampleSite")

    # Append one day of observations → creates snapshot
    snapshot_id = site.rinex_store.append_dataset(
        ds,
        receiver_name="canopy_01",
    )
    print(f"Snapshot: {snapshot_id[:8]}")
    ```

=== "Version History"

    ```python
    # List all commits on main branch
    history = site.rinex_store.get_history()
    for entry in history:
        print(entry["snapshot_id"][:8], entry["written_at"], entry["commit_msg"])

    # Pretty-print — same output, one liner
    site.rinex_store.print_history(limit=20)

    # Open a specific historical snapshot
    ds_old = site.rinex_store.read(
        receiver_name="canopy_01",
        time_range=("2024-01-01", "2024-01-31"),
        snapshot=history[-1]["snapshot_id"],
    )

    # Visualise the commit DAG (SVG in notebooks, coloured text in terminal)
    site.rinex_store.ancestry_graph()

    # Repo-wide operations audit trail (commits, branch ops, GC, …)
    site.rinex_store.print_ops_log(limit=30)
    ```

=== "Query Time Range"

    ```python
    ds = site.rinex_store.read(
        receiver_name="canopy_01",
        time_range=("2024-01-01", "2024-06-30"),
    )

    # Lazily loaded — only reads chunks covering the range
    print(ds.epoch.values[[0, -1]])
    ```

---

## Cloud Deployment

=== "AWS S3"

    ```python
    # No code change — set the store path to an S3 URI
    store = MyIcechunkStore("s3://my-bucket/examplesite/rinex")
    ```

    Configure credentials via environment variables or instance roles:

    ```bash
    export AWS_DEFAULT_REGION=eu-central-1
    export AWS_ACCESS_KEY_ID=...
    export AWS_SECRET_ACCESS_KEY=...
    ```

=== "MinIO / S3-Compatible"

    ```python
    import os
    os.environ["AWS_ENDPOINT_URL"] = "https://minio.example.com"
    os.environ["AWS_ACCESS_KEY_ID"] = "minioadmin"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "minioadmin"

    store = MyIcechunkStore("s3://canvod-data/examplesite/rinex")
    ```

=== "Cloudflare R2"

    ```python
    os.environ["AWS_ENDPOINT_URL"] = "https://<account_id>.r2.cloudflarestorage.com"
    os.environ["AWS_ACCESS_KEY_ID"] = "<r2_access_key>"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "<r2_secret_key>"

    store = MyIcechunkStore("s3://canvod-data/examplesite/rinex")
    ```

!!! tip "Local → Cloud"
    Switch from filesystem to S3 by changing the `store_path` string —
    no other code changes required.

---

## Deduplication

canvod-store uses SHA-256 file hashes to skip re-ingesting the same file:

```python
# In MyIcechunkStore.append_dataset()
if self._file_already_ingested(ds.attrs["File Hash"]):
    log.info("file_skipped", hash=ds.attrs["File Hash"][:8])
    return None

# Otherwise write + record hash
snapshot = self._write_and_commit(ds, ...)
self._record_ingested_hash(ds.attrs["File Hash"])
return snapshot
```

!!! info "Hash source"
    The `"File Hash"` attribute is set by the reader (`SbfReader.file_hash` /
    `Rnxv3Obs.file_hash`) — a 16-character SHA-256 prefix of the raw file.
    Duplicate ingestion is impossible even if the same file is submitted twice.

---

!!! example "Try it"
    [11 · Icechunk Store](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/11_icechunk_store.py)
    on molab (no rendered copy here yet: it uses canvodpy code that is not
    released yet)
