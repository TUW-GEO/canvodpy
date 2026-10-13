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
| `catalog.py` | The STAC catalog of all stores under a data root (ADR 0015), on pystac: `write_catalog`, `build_catalog`, `store_item`. The STAC functions in `inventory.py` are the older per-store form, deprecated and removed in v2.0.0 (#243); `validate_all(store_path=)` warns about a catalog link without its item |
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
- Rules from the standards (the license is SPDX or `other` with
  `license_uri`, vendored list in `standards/`; ORCID, ROR, DOI,
  coordinates, durations, URLs, the creator and publisher types, the
  store types; the list is in the store-metadata docs) live in the
  pydantic models, as annotated types in `schema.py` (the license rule,
  which reads two fields, as a model validator of `Publisher`), not in their
  users. `ACDD_TYPES` (`schema.py`) and `STORE_TYPES` (`identity.py`)
  are the one list of their values. New metadata breaking one fails. Metadata
  read from a store goes through `validate_existing` in `schema.py`: the
  value is kept with a `MetadataRuleWarning`, and `amend_metadata` is
  strict only on the fields it changes; a migration is strict on all of
  them except `COMPUTED_FIELDS`, which its commit computes again. A new read path of stored metadata uses `validate_existing`,
  never a plain `model_validate`. `context=READ_CONTEXT` directly only
  where the metadata was read, and warned about, already (amendment
  replay) or where the breaks are reported otherwise (`validate_all`,
  under `rules`).
  Tests make such stores with `testing.write_unchecked`.
- The catalog reads every store before it writes: if one can't be
  described, one `ValueError` lists them all and nothing is written.
- A store created by canVODpy has no validation failures:
  `validate_all(meta, recommended=False)` is empty. CF 1.11 and ACDD 1.3
  are checked on a netCDF export by IOOS compliance-checker in
  `canvodpy/tests/test_store_compliance.py`; its known exceptions are listed
  there.

## Tests

```bash
just test-package canvod-store-metadata
```
