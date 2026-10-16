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

The epoch chunk stays at 180 epochs: one 15-minute file at 5 s. A day
has ceil(86400 s / cadence) slots, and its block is padded to whole
chunks, so days never share a chunk and every cadence is stored. Padding
epochs lie between the day's last slot and the next day, hold missing
values, and are dropped on load. Because a block's length no longer gives
its cadence, the group keeps a block index in its attributes
(`day_block_index`: start, stop, slots and cadence per day).

*Amended 2026-10-16 (#376).* The first version refused every cadence
that does not divide 86400 s / 180 = 480 s, so that a day held whole
chunks without padding. Existing users store such cadences (for example
15 min after aggregation), so blocks are padded instead.

A run grows the axis once per batch, in one small commit, only for the
days whose ephemerides are ready, so days that cannot be processed never
get a block. Workers read a file and write its region into a fork of
one session. Two forks must never write the same chunk: Icechunk merges
forks chunk by chunk, so the fork merged last replaces a shared chunk
whole and the other's data in it are lost without an error (measured).
The files whose names put them into one chunk therefore go to one task,
with aggregation or without (six 15-minute files at 30 s share a chunk
of 180 epochs); with preprocessing set, a time bin can span two files,
so one task writes all files of a receiver-day. A file whose epochs
reach beyond its task's chunks is written by the writer thread. The
writer thread, not the loop that collects results, merges the forks of
all receivers of a day and commits once per store and day, with the
day's log-book rows (also of skipped files) and its snapshot summary,
built from the numbers each worker returns. The first write of a new
group, which creates it, is one session in the main process.
Phase 1 of the next day and VOD of the previous day overlap with
reading. `commit_lock` makes commits of other runs on the same machine
wait; a growth commit that loses a conflict retries. A day whose commit
loses a conflict is planned again on the new tip, against its log
book, and its tasks run again; a commit is tried up to five times, with
a growing, partly random wait in between. If the day or the growth
loses every try, the run records the receiver-days as failed with the
error and goes on with the next days. Several machines write one store
only on S3 (ADR 0019).

Memory is a budget (`max_memory_gb`, in `auto` the available memory):
the run sizes its workers and `days_per_batch` to fit it and fails at
the start if one file alone does not fit. There is no hard limit; no
portable one exists.

Existing stores are moved to this layout by one explicit command,
`canvodpy store migrate-layout`, after `migrate-metadata`; a store not
yet moved is refused with a message naming it. The temporal-overlap
check, deduplication on read and the overwrite branch are not needed
for day blocks and are deprecated (ADR 0005). Several runs on different
machines write one store on S3 (ADR 0019); this layout needs no change
for them, since different days are different chunks.

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
