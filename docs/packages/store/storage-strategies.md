# Storage Strategies

The write strategy controls what `MyIcechunkStore` does when a file's hash/time-range
already exists in the store (new files are always written, regardless of strategy). Set
it per store type in `canvod-settings.yaml` under `processing.storage:` —
`gnss_store_strategy` for the GNSS observation store, `vod_store_strategy` for the VOD
store.

<div class="grid cards" markdown>

-   :fontawesome-solid-forward-step: &nbsp; **Skip**

    ---

    No-op if the file already exists. Never writes, never touches existing data.

    *Best for: initial ingestion, pipeline restarts (default)*

-   :fontawesome-solid-arrows-rotate: &nbsp; **Overwrite**

    ---

    Deletes the existing epochs for that file's range, then writes the new version.
    Each run produces a new Icechunk snapshot for audit.

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
    vod_store_strategy: overwrite  # recompute as algorithms improve
```

The strategy is read from config, not passed to `MyIcechunkStore()` directly — there is
no `strategy=` constructor argument. `GnssResearchSite` (what `Site` wraps internally)
picks it up automatically:

```python
from canvod.store import GnssResearchSite

site = GnssResearchSite("ExampleSite")
site.gnss_store._gnss_store_strategy   # → "skip" (from config)
site.vod_store._gnss_store_strategy    # → "overwrite" (from config)
```

---

## Recommended Defaults

!!! success "Raw GNSS observations → `skip`"
    Raw GNSS data doesn't change after collection — there's no legitimate "two versions
    of the same file." A re-run over already-ingested files should be a no-op, not a
    rewrite. `skip` is the default for exactly this reason.

!!! info "Processed VOD products → `overwrite`"
    As the tau-omega inversion improves or auxiliary data quality changes, re-running the
    pipeline should replace old values. Each overwrite creates a new Icechunk snapshot so
    you can compare before/after.

!!! danger "`unsafe_append` can corrupt unguarded reads"
    `unsafe_append` does **not** merge or deduplicate — it writes the file's data again on
    top of what's already there, producing duplicate `epoch` coordinate values in the Zarr
    array. xarray does not enforce unique index values.

    The two built-in pipeline read paths already guard against this:
    `GnssResearchSite.read_receiver_data()` routes through `read_group_deduplicated()`
    whenever this strategy is set, and `VodComputer.compute_bulk()` unconditionally
    deduplicates every read via `_dedup_sort()` regardless of strategy. But
    `MyIcechunkStore.read_group()` itself — the low-level API used directly by custom
    scripts/notebooks, and by the deprecated L1 `Pipeline.calculate_vod()` — has **no**
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
| `overwrite` | Moderate — delete + write | Low (old chunks GC'd) | Safe |
| `unsafe_append` | Slowest — full write, no dedup check | Higher (old + new chunks kept) | Unsafe outside the two guarded read paths above |

!!! tip "Garbage collection"
    Overwritten chunks remain in the Icechunk object store until you run GC. The old
    versions are still accessible via snapshot IDs — useful for auditing before cleaning
    up. `unsafe_append`'s duplicate chunks are unaffected by GC in the same way, since
    they're still referenced by the current snapshot — GC only reclaims chunks that
    nothing references anymore.

---

!!! example "Try it"
    [13 · Store Operations](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/13_workflow_store_operations.py)
    on molab (no rendered copy here yet: it uses canvodpy code that is not
    released yet)
