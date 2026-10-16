---
title: Chunks
description: What a chunk is, how the GNSS store and the VOD store are chunked, and how to choose the chunk sizes.
---

# Chunks

The stores keep each variable, such as `SNR`, as an array with the
dimensions `epoch` and `sid`. An array isn't stored as one piece: it's cut
into **chunks**, blocks of a fixed number of epochs and signals. A chunk is
the unit that is read, compressed and written:

- To read one value, the store reads the whole chunk that holds it.
- To change part of a chunk, the store writes the whole chunk again.

So the chunk size decides how much a read loads and how much a write
rewrites. It's set per store in `canvod-settings.yaml`:

```yaml
processing:
  icechunk:
    chunk_strategies:
      gnss_store:
        epoch: 180    # epochs per chunk
        sid: -1       # all signals in one chunk
      vod_store:
        epoch: 180
        sid: -1
```

| Store | Default chunk | What it covers at 5 s |
|---|---|---|
| GNSS store | 180 epochs, all signals | one 15-minute file ($900\,\text{s} / 5\,\text{s}$) |
| VOD store | 180 epochs, all signals | 15 minutes of VOD ($900\,\text{s} / 5\,\text{s}$) |

`chunk_strategies` has exactly two keys, `gnss_store` and `vod_store`. A
store that you leave out keeps the default, and any other key fails
validation. A store that you set needs `epoch`; `sid` defaults to `-1`,
which puts all signals in one chunk.

!!! warning "A group keeps the chunk size it was created with"
    A changed setting applies to groups created from then on. Set
    `chunk_strategies` before the first run that writes a store.

For what each setting means, see
[`gnss_store`](../../guides/settings.md#processing-icechunk-chunk_strategies-gnss_store)
and
[`vod_store`](../../guides/settings.md#processing-icechunk-chunk_strategies-vod_store)
in the settings reference, or run
`canvodpy config explain gnss_store.epoch`.

## GNSS store

A new GNSS store is made of [day blocks](overview.md#day-blocks): each
receiver-day is a block of slots, one slot per sampling interval of the
day (its **cadence**). A day always holds a whole number of chunks, so
the cadence must divide the length of one chunk:

$$
\frac{86400\,\text{s}}{\text{epoch}}
\qquad\text{for example}\qquad
\frac{86400\,\text{s}}{180} = 480\,\text{s}
$$

With the default of 180 epochs, cadences of 1 s, 5 s, 15 s, 30 s, or 1 min
fit, for example. A run refuses a day whose cadence doesn't fit, and the
message names the setting that can fix it,
`processing.preprocessing.temporal_aggregation.freq`.

How many files share a chunk depends on the cadence. At 5 s, a chunk of
180 epochs is one 15-minute file. At 30 s, a chunk is 90 minutes, so six
15-minute files share it. The files that share a chunk are always written
together by one worker, so no write replaces the data of another file.

To change the chunks of an existing group made of day blocks, use
`store.rechunk_group()`. It refuses an epoch chunk that doesn't divide every
day of the group into whole chunks.

### Groups written by appending

A GNSS store whose groups were written by canVODpy versions before day
blocks is still written by appending each file to the end of the `epoch`
axis. In such a group, a file that ends inside a chunk makes the next
file rewrite that chunk. The epoch chunk works best when it equals the
epochs of one file:

$$
\text{epoch} = \frac{\text{file length in s}}{\text{sampling interval in s}}
$$

!!! note "GNSS stores created before 1.0.0b1"
    Before 1.0.0b1, the GNSS store default was `epoch: 17280`. Groups
    created then keep those chunks: reads work as before, but every file a
    run adds rewrites the last chunk. To change a group to the current
    default:

    ```python
    store.rechunk_group("canopy_01", {"epoch": 180, "sid": -1})
    ```

## VOD store

A run adds VOD results one day at a time. A day that ends inside a chunk
makes the next day rewrite that chunk, so set the epoch chunk to the
epochs of one day:

$$
\text{epoch} = \frac{86400\,\text{s}}{\text{sampling interval in s}}
$$

For example, data at a 2.5 s interval need `epoch: 34560`. To change the
chunks of an existing VOD store group, use `store.rechunk_group()`.

## Reads are lazy

`read_group()` opens a group with `xarray.open_zarr()`, so every data
variable is a Dask array. Nothing is read until a value is needed (for
example `.compute()`, `.values`, or a plot), and then only the chunks the
result needs.

With the default `sid: -1`, a chunk holds all signals, so one signal over a
year reads 365 chunks of the VOD store and 35,040 of the GNSS store at
5 s. If you read single signals of the VOD store over long periods,
rechunk it along `sid` with `rechunk_group()`.

`read_group()` returns Dask chunks equal to the chunks on disk, whatever
`chunk_strategies` says now. Its `chunks` argument sets other Dask chunks
for the returned dataset; it doesn't change the chunks on disk:

```python
ds = store.read_group(
    "canopy_01",
    time_slice=slice("2024-01-01", "2024-01-31"),
    chunks={"epoch": 3600, "sid": -1},
)
```

Variables that you compute from a read and add with
`add_group_variables()` are rechunked to the group's chunks before they are
written.
