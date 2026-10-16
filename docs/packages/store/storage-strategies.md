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

!!! note "The VOD store"
    The strategy applies to the GNSS store only. A run skips a VOD result
    when the VOD store already holds one computed from the same GNSS
    files. A result from other files replaces the stored VOD of its day
    (see [The VOD store](overview.md#the-vod-store)). To compute VOD again
    from the same GNSS files, write to a new VOD store: set another
    `processing.storage.vod_store_name`.

!!! note "Stores written by appending"
    A run writes [day blocks](overview.md#day-blocks) only. A store whose
    groups were written by appending files, by canVODpy versions before
    day blocks, is refused until it is moved to day blocks with
    `canvodpy store migrate-layout` (see
    [Moving a store to day blocks](overview.md#moving-a-store-to-day-blocks)).

## The strategies

| Strategy | File already stored (same hash) | Another file over stored epochs | New file |
|---|---|---|---|
| `skip` (default) | Not written; the run logs it. | The run stops and names both files. | Written |
| `overwrite` | Its slots are replaced; the log book says `overwritten`. | Replaces the stored data; the log book says `overwritten`. | Written |
| `unsafe_append` | As `overwrite` | As `overwrite` | Written |

"Another file over stored epochs" is a file with another hash whose time
span overlaps data stored from another file, for example a file that was
exported again with other content, or another run's file for the same
time. Neither file is preferred silently. The run checks this before it
writes and again at the tip, just before each commit, so a run that lost
a conflict to another run finds that run's files too.

### `skip`

A file that's already stored isn't written, and the store doesn't change.
Running again over the same files writes nothing new. This is the default.

### `overwrite`

The run writes the file into the slots of its day again, in the run's
commit. Use it to correct stored data, for example after a fix in a reader
or another ephemeris source.

- All of the file's slots are replaced, also those of its earlier write
  (found in the log book by its canonical name) it now has no epochs for.
  Slots inside another stored file's span are never emptied.
- No epoch is stored twice, and no other day is written.
- The log book keeps all its rows and records `overwritten`. The `sbf_obs`
  of an SBF file stays as first stored.
- The replaced data stays in earlier snapshots until they're expired and
  garbage is collected (`canvodpy store maintain`).

### `unsafe_append`

Kept from versions before day blocks, where it wrote a file again next to
the stored data, so the group held its epochs twice. In a store made of
day blocks, a file written again goes into the same slots, so
`unsafe_append` does what `overwrite` does.
