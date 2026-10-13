# Each receiver-day is a day block at its own cadence; workers write forks, one commit per day

A group's epoch axis is made of **day blocks**: one block per
receiver-day (one per VOD analysis and day in the VOD store), covering
the whole day at that day's **cadence**. The cadence comes from the
sampling interval in the canVOD file names (or the aggregation interval,
when aggregation is set), so a block's length and each file's place in
it are known before any file is read. A day with files of different
sampling takes the finest interval. Blocks are added at the end of the
axis in the order days are first written; a day is found by its epoch
coordinate, and loading puts the blocks in time order. There is no
origin and no setting. A day that has a block reuses it, so writing a
file again writes the same region and no duplicates arise.

Slots without data hold the standard missing value, set as both the
Zarr `fill_value` and the CF `_FillValue` (NaN for floats, a declared
value for integers). The epoch coordinate never has missing values: a
slot with data holds the epoch's real time, an empty slot its grid time
(00:00 plus a multiple of the cadence). An epoch goes to the nearest
slot; nothing is interpolated or moved, and a file with two epochs in
one slot is refused (ADR 0004). Loading returns every slot;
`drop_empty=True` drops slots where every SNR is missing. Coverage and
counts count epochs with data, never the length of the axis.

The epoch chunk stays at 180 epochs: one 15-minute file at 5 s, and a
whole number of chunks per day for every cadence that divides 480 s
(1 s, 5 s, 15 s, 30 s, 1 min). Other cadences are refused, and the
error names the aggregation setting.

A run grows the axis once per batch, in one small commit, only for the
days whose ephemerides are ready, so days that cannot be processed never
get a block. Workers read a file and write its region into a fork of
one session; with aggregation, one task writes the files of one chunk,
because two forks must never write the same chunk. A writer thread, not
the loop that collects results, merges the forks of all receivers of a
day and commits once per store and day, with the day's log-book rows
and its snapshot summary, built from the numbers each worker returns.
Phase 1 of the next day and VOD of the previous day overlap with
reading. `commit_lock` makes commits of other runs on the same machine
wait; a growth commit that loses a conflict retries, a data commit
rereads the log book, drops the files now stored and retries once, then
fails loudly. Two machines never write one store.

Memory is a budget (`max_memory_gb`, in `auto` the available memory):
the run sizes its workers and `days_per_batch` to fit it and fails at
the start if one file alone does not fit. There is no hard limit; no
portable one exists.

Existing stores are moved to this layout by one explicit command,
`canvodpy store migrate-layout`, after `migrate-metadata`; a store not
yet moved is refused with a message naming it. The temporal-overlap
check, deduplication on read and the overwrite branch are not needed
for day blocks and are deprecated (ADR 0005). On S3 the same single
writer works; several independent writers on S3 are a later design,
after v1.0.0, and need no change to this layout, since different days
are different chunks.

## Considered options

- **Keep appending, write only the receivers of a day in parallel.** No
  layout change, but the files of one receiver stay serial in the main
  process (about 3 s per receiver-day); the gain stops at the number of
  receivers.
- **Appends in workers.** Two appends to one group both resize the
  array; the second commit fails (measured).
- **A fixed origin for the axis** (first day processed, or a setting).
  An origin needs refusing or rewriting earlier days, or a setting to
  get right; the time order only matters when loading.
- **One cadence per group, with aggregation to the sampling interval
  by default.** A receiver that moves from 1 s to 5 s would be stored
  padded at 1 s, and aggregation would run when nobody asked for it.
- **Snapping epochs to the grid within a tolerance.** It moves
  observation times, which changes the data.
- **One chunk per day.** Zarr has one chunk size per array, so days of
  different cadence could not share a group, and one task would write a
  whole receiver-day. Its old drawback (each append rewrote the growing
  chunk, about 48 times the disk) is gone with day blocks.
- **Growing the axis for the whole run at once.** A run usually stops
  before its last days because their orbit products are not out yet,
  which would leave empty blocks.
- **One commit per receiver-day, or per batch.** Per receiver-day keeps
  today's commit count, which slows the store over time; per batch
  loses more work when one day fails.
- **Dropping empty slots on every load.** Matches the old behavior but
  scans SNR on every read.
