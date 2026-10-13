---
name: store-safety
description: Check before writing to, repairing or maintaining a canvodpy Icechunk store (branches, dedup, write strategies, recovery, expiry and garbage collection). Use before any code or command that writes to a real store.
---

# Store safety

Stores hold the user's processed data; some cannot be recomputed quickly.
Never write to, reset or clean up a real store without the user's
go-ahead. Try changes on a copy, or on a branch of the store, first.
For the icechunk API itself see the `icechunk` guide.

## Before writing

1. **Which store and branch?** Runs write `main`. For experiments, create a
   branch (`MyIcechunkStore.create_branch`) and write there.
2. **Dedup**: writes go through the three checks of canvod-store (file
   hash, time overlap with stored files, overlap inside the batch). Code
   that writes around them (`to_icechunk` directly on a run's group) is a
   bug.
3. **Write strategy** (`processing.storage.gnss_store_strategy`; VOD
   writes always skip): `skip` is the safe default; `overwrite`
   replaces the stored time ranges of re-processed files;
   `unsafe_append` stores duplicates. Never switch a user to
   `unsafe_append`.
4. **One writer.** On local and network file systems icechunk cannot see a
   second process committing to the same branch: one of the two commits is
   lost without an error. Don't start a second run or maintenance while a
   run writes to that store.
5. **Preprocessing** must match what the group already holds; the store
   refuses a mix.
6. **Release tags** (no `/`, for example `v2026.1`) are written by
   `canvodpy stac release` only (`just stac-release TAG`), which tags every
   store under the data root and writes `releases/<tag>/`. Never create,
   move or delete a release tag by hand: a published release catalog
   points at it. Tags with a `/` (`keep/<receiver>/<yyyydoy>`) are
   canvod-store's own.

## Inspect

```bash
just store-list
just store-info <site> [gnss|vod]
just store-log <site> [gnss|vod]      # commits
just store-ops <site> [gnss|vod]      # operations log (expiry, GC, resets)
```

## Recover

| Problem | What to do |
|---|---|
| Bad commit on `main` | Find the last good snapshot in the history; the user decides; then `repo.reset_branch("main", <snapshot>)`. Snapshots stay until garbage collection |
| Need the old state alongside | Branch from the old snapshot instead of resetting |
| Failed rechunk left branches | `MyIcechunkStore.cleanup_stale_branches` |

## Maintenance (expiry, garbage collection, manifest compaction)

`uv run canvodpy store maintain <site>` reports by default and acts only
with `--execute`, after a confirmation. `canvodpy store maintain-due` is
the unattended form; it does nothing unless
`processing.storage.maintenance.enabled` is set and no run is active.
Garbage collection deletes files for good: always a dry run first, a
retention window of weeks to months, never while a run writes. Details in
`docs/packages/store/icechunk.md`.
