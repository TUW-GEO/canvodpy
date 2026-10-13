# canvod-store

Versioned Icechunk stores for observations and VOD: writing with dedup,
reading, history, maintenance. Built on icechunk 2 (see the `icechunk`
guide).

## Where things live

| Path (under `src/canvod/store/`) | What |
|---|---|
| `store.py` | `MyIcechunkStore`: sessions, group writes and appends, the metadata table, dedup checks, VOD writes, maintenance (`maintenance_due`, `compact_manifests`, expiry, GC), branches and tags |
| `manager.py` | `GnssResearchSite`: a site's observation and VOD stores |
| `viewer.py` | `IcechunkStoreViewer`: inspection and summaries |
| `reader.py` | `IcechunkDataReader`: deprecated second ingestion path, not used by any run |
| `zarr_concurrency.py` | Zarr async concurrency cap (shared or network mounts) |

Background: `docs/packages/store/overview.md`,
`docs/packages/store/icechunk.md` (concurrency, settings),
`docs/packages/store/storage-strategies.md`.

## Invariants

- **Dedup before writing**, in three layers: file hash already in the
  metadata table; time range overlapping stored files; overlap inside the
  batch. A rejected file is reported, never written silently.
- **Write strategies** (`processing.storage.gnss_store_strategy`):
  `skip`, `overwrite`, `unsafe_append`; VOD writes always skip
  (`vod_store_strategy` is deprecated, has no effect). Their
  meaning is documented on the settings model in
  `packages/canvod-config/src/canvod/config/models/storage.py`; keep code
  and that description in step.
- **VOD writes** check `validate_vod_dataset` (canvod-readers) first.
- **Release tags** (no `/`) belong to the release command
  (`create_release` in canvod-store-metadata, `canvodpy stac release`);
  this package never creates, moves or deletes one. Its own tags hold a
  `/` (`keep/{receiver}/{yyyydoy}`).
- **Preprocessing record**: a dataset carries its record in memory
  (`PREPROCESSING_ATTR`, canvod-config); every write drops it from the data
  (`prepare.prepare_write`, call it before every `to_icechunk`/`to_zarr`;
  pass `append_dim=` for an append, `None` otherwise: an append whose
  variables along it differ from the group's raises
  `GroupVariablesMismatchError`, one whose labels of another dimension, e.g.
  `sid`, differ from the group's raises `GroupCoordinatesMismatchError`)
  and the log-book row stores it in the `preprocessing` column (GNSS: the
  record; VOD: `{receiver: [records]}`). Never store it as a data attribute.
  A group refuses data whose settings differ from any record in its log book
  (`check_preprocessing_matches`, raises `PreprocessingMismatchError`, which
  is not a `ValueError` so runs stop on it). Runs call
  `check_settings_match` with `canvod.ops.planned_settings` before any
  processing; both checks share the comparison. A group-wide row (action
  `add_variables`, from `add_group_variables`) adds its steps to every
  earlier row (`preprocessing_records`).
- **Log-book rows are JSON or text only** (`_json_log_row`).
- **One committer per branch.** On local or network file systems icechunk
  cannot detect concurrent commits; the second silently wins. Parallel
  writes go through fork/merge into one session and one `commit()`.
- canvod-store does not import `canvodpy`.
- Grids and the analysis results on them are stored by `grid_storage.py`
  and `analysis_storage.py`; canvod-store depends on canvod-grids, never
  the other way round.

## Store layout

One Icechunk repository per store; one group per receiver (observation
store) or per analysis (VOD store), each with a log of the
ingested files (`{group}/metadata/table`). The store metadata is in
Icechunk's repository metadata, with a copy and the snapshot summary in
the root attributes of every snapshot (see canvod-store-metadata).

## Tests

```bash
just test-package canvod-store
```
