# canvod-store-metadata

Store-level provenance of an Icechunk store: identity, creators, software,
environment, standards (DataCite, ACDD, STAC). Not the per-file log of
canvod-store (`{group}/metadata/table`).

## Where things live

| Path (under `src/canvod/store_metadata/`) | What |
|---|---|
| `schema.py` | The metadata models: `RepositoryMetadata` in Icechunk's repository metadata, `StoreMetadata` as read from one snapshot (repository metadata, snapshot summary and commit metadata); the old root attribute `canvod_metadata` only in snapshots from before ADR 0014 |
| `amend.py`, `migration.py` | `amend_metadata` (amendable fields, with a reason) and `migrate_metadata` (stores from before ADR 0014) |
| `identity.py` | Store id, UUID, naming authority and catalog link of a new store |
| `collectors.py` | `collect_metadata`: fills the model from settings, dataset and environment |
| `io.py` | Write a new store's metadata, read a snapshot's; `commit_with_rebase`, the one commit function |
| `snapshot.py` | What every commit writes: root copy, snapshot summary, commit metadata, lockfile text in the reserved group `canvod` |
| `validate.py` | Checks against the schema and the standards |
| `catalog.py` | The STAC catalog of all stores under a data root (ADR 0015), on pystac: `write_catalog`, `build_catalog`, `store_item`. The STAC functions in `inventory.py` are the older per-store form |
| `inventory.py`, `show.py`, `summary.py` | Several stores at once; reports |
| `testing.py` | Stores with the made-up site's metadata, for tests |

Background: `docs/packages/store-metadata/overview.md`. The `metadata-*`
recipes run these from the command line (`just metadata-show <store>`,
`just metadata-validate <store>`).

## Invariants

- The import is `canvod.store_metadata`, not `canvod.store.metadata`.
- Repository metadata is written once, when the store gets its metadata;
  every commit through `commit_with_rebase` then writes the root copy and
  the snapshot summary and checks the root copy (ADR 0014).
- `commit_with_rebase` refuses a store without repository metadata. Tests
  that write to a store directly give it made-up metadata first with
  `canvod.store_metadata.testing.give_test_metadata`.
- A store created by canVODpy has no validation failures:
  `validate_all(meta, recommended=False)` is empty. CF 1.11 and ACDD 1.3
  are checked on a netCDF export by IOOS compliance-checker in
  `canvodpy/tests/test_store_compliance.py`; its known exceptions are listed
  there.

## Tests

```bash
just test-package canvod-store-metadata
```
