---
name: icechunk
description: Icechunk 2 (the versioned Zarr storage under canvodpy's stores) - repositories, sessions, fork/merge parallel writes, branches and tags, history, repository metadata, maintenance, spec versions. Use when reading or changing code that calls icechunk, or when working on a store directly.
---

# Icechunk 2 in canvodpy

canvodpy requires icechunk 2 (`icechunk>=2.0`, locked version in
`uv.lock`); everything here was checked against icechunk 2.1.1. Icechunk 1
code and docs differ in many places: when in doubt, check the installed
API (`uv run python -c "import icechunk; help(icechunk.Repository)"`), not
memory or old examples. For what canvodpy builds on top (dedup, write
strategies, recovery), read `packages/canvod-store/AGENTS.md` and the
`store-safety` guide. canvodpy's wrapper is `MyIcechunkStore` in
`packages/canvod-store/src/canvod/store/store.py`; use its methods before
calling icechunk directly.

## Facts that matter for canvodpy

- **Storage is the local file system** (an SSD or a network mount, never an
  object store). Local storage makes no conditional writes
  (`unsafe_use_conditional_update` is `False`), so icechunk cannot detect
  two commits to the same branch at the same moment: one can be lost
  without an error. icechunk itself warns: "The LocalFileSystem storage is
  not safe for concurrent commits". Rule: one process commits to a branch
  at a time; parallel work uses fork/merge into one session (below).
- **Out-of-date sessions rebase.** A session opened before another commit
  landed on its branch raises `ConflictError` on commit, unless it rebases.
  Every canvodpy commit goes through
  `canvod.store_metadata.io.commit_with_rebase` (`rebase_with=
  icechunk.ConflictDetector()`): changes to other groups are rebased onto
  the new tip; changes to the same nodes raise `RebaseFailedError`. Never
  call `session.commit()` directly.
- **A commit ends a session.** After `session.commit()` the session is
  read-only; start a new `repo.writable_session(branch)`.
- **Read with `consolidated=False`**: `xr.open_zarr(session.store,
  consolidated=False)`. Icechunk keeps metadata itself.
- **Write with `icechunk.xarray.to_icechunk`**, not `to_zarr`; it handles
  dask arrays and forks.
- **Every `to_icechunk` call flushes a new manifest.** One call per file
  in a day's batch gives one manifest per file. Batch writes; compact with
  `rewrite_manifests` (canvodpy: `MyIcechunkStore.compact_manifests`).
- **Nothing is deleted by default.** Every snapshot stays until expiry and
  garbage collection run.

## Repository

```python
import icechunk

storage = icechunk.local_filesystem_storage("/path/to/store")
repo = icechunk.Repository.open(storage)  # or .create / .open_or_create
icechunk.Repository.exists(storage)  # is there a repository?
repo.spec_version  # on-disk format: SpecVersion.v1 or .v2
```

`Repository.create(storage, config=..., spec_version=...)` creates spec
v2 by default. `RepositoryConfig` (caching, compression, manifest
splitting and preloading, `max_concurrent_requests`,
`num_updates_per_repo_info_file`, `repo_update_retries`) is built from
the settings in `MyIcechunkStore.__init__`; `repo.save_config()` stores it
in the repository, `Repository.fetch_config(storage)` reads it back.

## Sessions

```python
session = repo.writable_session("main")
session = repo.readonly_session("main")  # branch tip
session = repo.readonly_session(tag="v1")  # or snapshot_id=...
session = repo.readonly_session("main", as_of=some_datetime)  # branch at a time
session.store  # zarr store for xarray/zarr
session.status()  # Diff of uncommitted changes
session.has_uncommitted_changes
session.discard_changes()
snapshot_id = session.commit("message", metadata={"key": "value"})
```

`commit` also takes `allow_empty=` and `rebase_with=`/`rebase_tries=`
(useless on local storage, see above). `session.amend(message)` replaces
the previous snapshot instead of adding one; `session.flush(message)`
writes an anonymous snapshot without moving the branch.

`with repo.transaction("main", message="...") as store:` commits when the
block ends; an exception in the block skips the commit, nothing is
written to the branch.

### Parallel writes: fork and merge

```python
session = repo.writable_session("main")  # must have no uncommitted changes
forks = [session.fork() for _ in jobs]  # ForkSession objects, picklable
# each worker writes into its own fork (to_icechunk(ds, fork, ...)) and returns it
session.merge(*finished_forks)
session.commit("one commit for all workers")
```

`fork()` raises `ValueError` if the session already has uncommitted
changes or is read-only. Forks write chunk data in parallel; only the
final `commit()` moves the branch, so this is safe on local storage.
canvodpy's processor uses it per receiver group; dedup checks must run
before the forks are handed out.

### Rearranging nodes

`repo.rearrange_session(branch)` gives a session that only allows
`session.move(from_path, to_path)` (rename or move groups and arrays
without copying data), then `commit`. `Session.shift_array` and
`Session.reindex_array` move chunks inside an array.

## Branches, tags, history

```python
repo.list_branches()
repo.lookup_branch("main")  # tip snapshot id
repo.create_branch("try-fix", snapshot_id=repo.lookup_branch("main"))
repo.reset_branch("main", snapshot_id, from_snapshot_id=expected_tip)
repo.delete_branch("try-fix")
repo.create_tag("v1", snapshot_id)
repo.lookup_tag("v1")
repo.list_tags()
repo.delete_tag("v1")  # the name can never be used again
# SnapshotInfo: id, parent_id, written_at, message, metadata
for snap in repo.ancestry(branch="main"):
    ...
repo.lookup_snapshot(snapshot_id)
# Diff: new/updated/deleted arrays and groups, moved nodes
repo.diff(from_snapshot_id=a, to_branch="main")
repo.ancestry_graph()  # printable history of all branches
repo.ops_log()  # administrative operations: resets, expiry, GC, ...
```

`reset_branch(..., from_snapshot_id=)` only resets if the tip is still
the expected one; use it. On a mismatch it raises a plain
`IcechunkError`. canvodpy promotes temporary branches (overwrite,
rechunk) only through `MyIcechunkStore.promote_branch`, which raises
`BranchMovedError` and keeps the temporary branch.

## Repository metadata and status (new in icechunk 2)

- `repo.get_metadata()`, `repo.set_metadata(d)` (replaces),
  `repo.update_metadata(d)` (merges): metadata of the repository itself,
  readable without opening a session. canvodpy keeps a store's
  repository metadata here (ADR 0014, canvod-store-metadata): write it
  only through `write_metadata`, `amend_metadata` or `migrate_metadata`,
  never with `set_metadata` or `update_metadata` directly. Each commit,
  through `commit_with_rebase`, copies it into the root attributes and
  refuses a root group that differs.
- `repo.set_default_commit_metadata(d)`: merged into every later commit's
  metadata (sessions opened afterwards only).
- `repo.get_status()` / `repo.set_status(icechunk.RepoStatus(...))`:
  availability `online` or `read_only`, e.g. to freeze a store during
  maintenance.
- `repo.feature_flags()`, `repo.set_feature_flag(name, setting)`: switch
  operations such as tag creation or node moves off for a repository.

## Maintenance

| Step | Call | Effect |
|---|---|---|
| Expire | `repo.expire_snapshots(older_than, delete_expired_branches=False, delete_expired_tags=False)` | History before `older_than` (commit time) becomes unreachable; no file deleted yet. Branch tips and the root stay |
| Collect | `repo.garbage_collect(delete_object_older_than, dry_run=True)` | Deletes unreachable files for good; returns `GCSummary`. Always a dry run first |
| Compact | `repo.rewrite_manifests(message, branch="main")` | Merges fragmented manifests into a new commit; old manifests go at the next expiry and collection |
| Size | `repo.total_chunks_storage()`, `repo.chunk_storage_stats()` | Storage used by chunks |

Only one expiry or collection at a time, never while a run writes, and a
retention window of weeks to months. canvodpy wraps this in
`canvodpy store maintain` and `canvodpy store maintain-due`; see the
`store-safety` guide.

## Spec versions: stores written by icechunk 1

icechunk 2 reads and writes spec v1 repositories, but some features need
spec v2 (for example `commit_method="amend"` in `rewrite_manifests`).
`icechunk.upgrade_icechunk_repository(repo, dry_run=True)` migrates v1 to
v2. It is an administrative operation: nobody else may use the store
while it runs, the returned `Repository` replaces the old object, and the
user decides when it runs (dry run first, a backup of the store first).

## Pitfalls

| Pitfall | Do instead |
|---|---|
| Writing after `commit()` | New `writable_session` |
| Two processes committing to one branch | fork/merge, one `commit()` |
| `consolidated=True` or default in `open_zarr` | `consolidated=False` |
| `to_zarr` on a session store | `to_icechunk` |
| One `to_icechunk` per file | Batch; compact manifests periodically |
| Garbage collection without a dry run | `dry_run=True` first, read the summary |
| Re-creating a deleted tag | Pick a new name; deleted tag names stay reserved |
| Icechunk 1 names (`WritableSession`, `ReadonlySession`, `unsafe_overwrite_refs`) | `Session`, `ForkSession`; check `dir(icechunk)` |
