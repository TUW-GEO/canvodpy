---
title: Write strategies
description: What a run does with a file that is already in the GNSS store.
---

# Write strategies

The write strategy sets what a run does with a file that's already in the
GNSS store: a file with the same hash, or one whose time span overlaps
stored data (see [Duplicate checks](overview.md#duplicate-checks)). A run
always writes new files, whatever the strategy.

Set the strategy in `canvod-settings.yaml`:

```yaml
processing:
  storage:
    gnss_store_strategy: skip
```

`MyIcechunkStore` has no `strategy` argument; the strategy comes from the
settings. `canvodpy config show` prints the strategy in use under
**Storage**.

!!! note "The VOD store always skips"
    The strategy applies to the GNSS store only. A run skips a VOD result
    when the VOD store already holds one computed from the same source
    files, or one whose epoch range overlaps it; the log book records
    `skip`. To compute VOD again for days that are already in the VOD
    store, write to a new VOD store: set another
    `processing.storage.vod_store_name`.

## The strategies

| Strategy | File already stored | New file |
|---|---|---|
| `skip` (default) | Not written; the run logs it. | Written |
| `overwrite` | Its time range is replaced. | Written |
| `unsafe_append` | Written again, next to the stored data. | Written |

### `skip`

A file that's already stored isn't written, and the store doesn't change.
Running again over the same files writes nothing new. This is the default.

### `overwrite`

The run replaces the stored data in the file's time range with the file's
data. Use it to correct stored data, for example after a fix in a reader
or another ephemeris source.

- The run merges the group's other epochs with the new data and rewrites
  the group in epoch order, so an overwrite writes the whole group.
- The log book keeps all its rows. For an SBF receiver, `sbf_obs` loses
  that time range and gets the new file's rows.
- The new version is written to a temporary branch,
  `overwrite_{receiver}_{YYYYDOY}`, and moved to `main` only if nothing
  else was committed to `main` in the meantime. Otherwise the run stops
  with `BranchMovedError`: `main` keeps the other commit, and the new
  version stays on the temporary branch.
- The replaced data stays in earlier snapshots until they're expired and
  garbage is collected (`canvodpy store maintain`).

### `unsafe_append`

The run writes the file's data again, with no check for epochs that are
already stored. The group then holds the same `epoch` values twice, and
xarray doesn't require unique index values.

!!! danger "Duplicate epochs break reads that don't remove them"
    Two reads remove duplicate epochs:

    - `GnssResearchSite.read_receiver_data()` reads with
      `read_group_deduplicated()` when the strategy is `unsafe_append`.
    - `VodComputer.compute_bulk()` removes duplicate epochs from every read,
      whatever the strategy.

    `MyIcechunkStore.read_group()` doesn't. On data with duplicate epochs,
    `.sel()` can raise an error or return several values, and aligning two
    datasets that both have the duplicates (for example canopy and
    reference) pairs each duplicate with each other one, without an
    error.

    The duplicates are stored: garbage collection doesn't remove them,
    because the current snapshot still uses them. Don't use
    `unsafe_append` unless you have a specific reason.
