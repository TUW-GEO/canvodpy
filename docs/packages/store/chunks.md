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
day (its **cadence**). The cadence may change from one day to the next.
A day has

$$
\text{slots} = \left\lceil \frac{86400\,\text{s}}{\text{cadence}} \right\rceil
$$

and its block always holds a whole number of chunks, so days never share
a chunk. When the slots don't fill the last chunk, the block is padded with
empty epochs, which loading leaves out. With the default of 180 epochs:

| Cadence | Slots per day | Padding |
| --- | --- | --- |
| 1 s, 5 s, 15 s, 30 s, 1 min | 86400, 17280, 5760, 2880, 1440 | none |
| 7 s | 12343 | 77 |
| 45 s | 1920 | 60 |
| 15 min | 96 | 84 |

Every cadence fits; the padding costs at most one chunk per day.

How many files share a chunk depends on the cadence. At 5 s, a chunk of
180 epochs is one 15-minute file. At 30 s, a chunk is 90 minutes, so six
15-minute files share it; at 15 min, the whole day is one chunk. The files
that share a chunk are always written together by one worker, so no write
replaces the data of another file.

To change the chunks of an existing group made of day blocks, use
`store.rechunk_group()`. It refuses an epoch chunk that doesn't divide the
length of every day block of the group, padding included.

### Groups written by appending

A group written by canVODpy versions before day blocks appended each file
to the end of the `epoch` axis, so a file that ended inside a chunk made
the next file rewrite that chunk. Runs refuse such a store;
`canvodpy store migrate-layout` writes its groups again as day blocks,
with the chunks of the settings (see
[Moving a store to day blocks](overview.md#moving-a-store-to-day-blocks)).

## VOD store

A VOD store group made of [day blocks](overview.md#the-vod-store) is
chunked like the GNSS store: each day is a block of whole chunks, padded
where its slots don't fill the last one. A day of VOD has the cadence of
its GNSS data.

## Reads are lazy

`read_group()` opens a group with `xarray.open_zarr()`, so every data
variable is a Dask array. Nothing is read until a value is needed (for
example `.compute()`, `.values`, or a plot), and then only the chunks the
result needs. With `date` or `time_slice`, a group made of day blocks opens
only the blocks of the days selected, so reading a day takes the same time
however many days the store holds.

With the default `sid: -1`, a chunk holds all signals, so one signal over a
year at 5 s reads 35,040 chunks of either store, 96 per day. If you read
single signals over long periods, rechunk the group along `sid` with
`rechunk_group()`.

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
