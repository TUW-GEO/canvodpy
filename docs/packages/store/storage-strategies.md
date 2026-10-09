# Storage Strategies

The write strategy controls what a run does when a file is already in the
GNSS store (same file hash, or an overlapping epoch range). New files are
always written, whatever the strategy. Set it in `canvod-settings.yaml`
under `processing.storage.gnss_store_strategy`.

!!! note "VOD writes always skip"
    The strategy applies to the GNSS store only. A VOD result is always
    skipped when the VOD store already holds one computed from the same
    source files, or one whose epoch range overlaps it; the log book records
    `skip`. To recompute VOD for days already in the store, write to a new
    VOD store (set another `processing.storage.vod_store_name`).

<div class="grid cards" markdown>

-   :fontawesome-solid-forward-step: &nbsp; **Skip**

    ---

    No-op if the file already exists. Never writes, never touches existing data.

    *Best for: initial ingestion, pipeline restarts (default)*

-   :fontawesome-solid-arrows-rotate: &nbsp; **Overwrite**

    ---

    Deletes the existing epochs for that file's range, then writes the new version.
    The log book keeps all rows; `sbf_obs` loses that range and gets the
    new file's `sbf_obs`, if stored. Each run produces a new Icechunk snapshot for audit. The new version is
    staged on a temporary branch (`overwrite_{receiver}_{YYYYDOY}`) and moved to
    `main` only if nothing else was committed to `main` meanwhile; otherwise the
    run stops with `BranchMovedError`, `main` keeps the other commit, and the
    staged version stays on the temporary branch.

    *Best for: correcting already-ingested data after a pipeline bug fix*

-   :fontawesome-solid-triangle-exclamation: &nbsp; **Unsafe append**

    ---

    Writes the file's data again on top of what's already there, with **no
    epoch-level uniqueness check**. See the warning below before using this.

    *Best for: essentially nothing in normal operation — see warning*

</div>

---

## Behaviour Reference

| Strategy | File already exists | File is new | Version snapshot |
|----------|:--------------------:|:------------:|:----------------:|
| `skip` | No write | Write | On write |
| `overwrite` | Delete old epochs, write new | Write | Always |
| `unsafe_append` | Write again on top (duplicates epochs) | Write | Always |

---

## Usage

```yaml
processing:
  storage:
    gnss_store_strategy: skip      # raw observations are immutable
```

The strategy comes from the settings file; `MyIcechunkStore()` has no
`strategy=` argument. `canvodpy config show` prints the value in use under
**Storage**.

---

## Recommended Defaults

!!! success "Raw GNSS observations → `skip`"
    Raw GNSS data doesn't change after collection — there's no legitimate "two versions
    of the same file." A re-run over already-ingested files should be a no-op, not a
    rewrite. `skip` is the default for exactly this reason.

!!! danger "`unsafe_append` can corrupt unguarded reads"
    `unsafe_append` does **not** merge or deduplicate — it writes the file's data again on
    top of what's already there, producing duplicate `epoch` coordinate values in the Zarr
    array. xarray does not enforce unique index values.

    The two built-in pipeline read paths already guard against this:
    `GnssResearchSite.read_receiver_data()` routes through `read_group_deduplicated()`
    whenever this strategy is set, and `VodComputer.compute_bulk()` unconditionally
    deduplicates every read via `_dedup_sort()` regardless of strategy. But
    `MyIcechunkStore.read_group()` itself — the low-level API used directly by custom
    scripts — has **no**
    such guard: `.sel()` on a duplicated label can raise or silently return multiple
    matches, and aligning two datasets that both carry the duplicate (e.g. canopy vs.
    reference) produces a cartesian product at those epochs, corrupting results without
    raising an error.

    The duplication is also physical, not just a read-time artifact: Icechunk stores the
    extra chunks permanently, regardless of whether the read side protects against it.
    Avoid `unsafe_append` unless you have a specific reason, and be aware any read path
    outside the two guarded ones above is unprotected.

---

## Performance

| Strategy | Typical write throughput | Storage overhead | Read safety |
|----------|--------------------------|-------------------|-------------|
| `skip` | Fastest — hash check only | None | Safe |
| `overwrite` | Slowest — rewrites the receiver's whole group | Low after garbage collection | Safe |
| `unsafe_append` | Like a new file — full write, no check | Higher (old + new chunks kept) | Unsafe outside the two guarded read paths above |

!!! tip "Garbage collection"
    Overwritten chunks remain in the Icechunk object store until you run garbage collection (`canvodpy store maintain <site>`, a dry run unless you pass `--execute`). The old
    versions are still accessible via snapshot IDs — useful for auditing before cleaning
    up. `unsafe_append`'s duplicate chunks are unaffected by GC in the same way, since
    they're still referenced by the current snapshot — GC only reclaims chunks that
    nothing references anymore.
