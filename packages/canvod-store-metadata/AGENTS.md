# canvod-store-metadata

Store-level provenance of an Icechunk store: identity, creators, software,
environment, standards (DataCite, ACDD, STAC). Not the per-file log of
canvod-store (`{group}/metadata/table`).

## Where things live

| Path (under `src/canvod/store_metadata/`) | What |
|---|---|
| `schema.py` | The metadata models; stored as the root attribute `canvod_metadata`, the repository part (`RepositoryMetadata`) in Icechunk's repository metadata |
| `identity.py` | Store id, UUID, naming authority and catalog link of a new store |
| `collectors.py` | `collect_metadata`: fills the model from settings, dataset and environment |
| `io.py` | Read, write, update the metadata of a store; `commit_with_rebase`, the one commit function |
| `snapshot.py` | What every commit writes: root copy, snapshot summary, commit metadata, lockfile text in the reserved group `canvod` |
| `validate.py` | Checks against the schema and the standards |
| `inventory.py`, `show.py`, `summary.py` | Several stores at once; reports |

Background: `docs/packages/store-metadata/overview.md`. The `metadata-*`
recipes run these from the command line (`just metadata-show <store>`,
`just metadata-validate <store>`).

## Invariants

- The import is `canvod.store_metadata`, not `canvod.store.metadata`.
- Repository metadata is written once, when the store gets its metadata;
  every commit through `commit_with_rebase` then writes the root copy and
  the snapshot summary and checks the root copy (ADR 0014).

## Tests

```bash
just test-package canvod-store-metadata
```
