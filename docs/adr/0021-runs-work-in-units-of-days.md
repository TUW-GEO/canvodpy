# A run works in units of days, keeps its stores' state in memory, and computes VOD in a phase of its own

*Proposed 2026-10-18 (#418). Amends ADR 0016: one commit per unit, not per day.*

Measurements of a year of data at 58ee7ab8 (#418) showed that from about
16 workers on, the main process sets a run's wall time, and that its
work per day grows with the days already stored. Three choices caused it:
the store was the run's only memory, the day was the unit of every
step, and the main process did all serial work, VOD included. Only live
operation needs the day as a unit: receivers send 24 hours of data every
24 hours. A backlog (historical data, reprocessing, a new site) has no
such constraint.

**Work per day does not grow with the store.** A step that runs per day
or per unit reads only what that day or unit needs: the blocks of its
days (ADR 0016), the log-book rows near its days, the commits made since
it started. Reading a whole group, a whole log book or the whole summary
again for each day is a defect.

**A run keeps its stores' state in memory.** At its start, a run reads
each group's log book and block index once. It plans, checks overlaps
(#351) and decides what to skip against that state, and adds to it what
it commits. The summary written with each commit (ADR 0014) is updated
from the rows of that commit, not rebuilt from the whole log book.
Several runs may still write one store (ADR 0019): when a commit has to
rebase onto commits of another run, the run reads only the rows that run
added. The log book only grows at its end and numbers its rows, so these
are the rows past the last number the run knows.

**A run works in units of days.** The days of a unit grow their blocks
in one commit, are planned together, and are committed once per store.
The number of days in a unit is derived, not a setting: enough that
every worker gets several tasks within the memory budget, at most 31,
so that a conflict or a crash loses little. A live run's unit is its one
day. A unit holds only the days whose ephemerides are ready; the other
days get no blocks and stay open for the next run, as before. A day
fails alone, never its unit: a file that fails gets no log-book row and
is tried again by the next run. A unit whose commit loses a conflict is
planned again on the new tip and tried again (ADR 0016). Tasks are the
groups of files that share an epoch chunk, or with preprocessing set a
time bin (ADR 0016); the memory planner sizes workers by these tasks
(#417).

**VOD is a phase of its own.** VOD is computed after the GNSS data of
its days are committed, by tasks in the worker pool: one per analysis
pair and day, reading the day from the GNSS store's committed snapshot
and writing its region into a fork of the VOD store. The main process
merges the forks and commits once per unit. A run chains the phase after
its GNSS phase (a live run: one day of GNSS data, then that day's VOD),
and the phase runs on its own over any range of days already in the GNSS
store, for example once after a backlog. The GNSS phase no longer reads
its days back.

## Considered options

- **Fix each growing step on its own** (read-back, summary, log-book
  reads, planning). Each fix helps, but the next step added would read
  the whole store again; the rule in this decision makes that a defect
  to review against.
- **Speed up the summary's rebuild and keep rebuilding it.** About 2.5 times
  faster on a year store, but it still grows with the store. Kept as
  the fallback where a whole rebuild is needed (`summarize_store`, a
  store's first commit in a run).
- **A fixed number of days per unit, or `days_per_batch`.** A fixed
  number is wrong for most machines; the memory budget and the worker
  count already give the right size.
- **One unit per run (grow and commit everything at once).** A conflict
  or a crash would lose the whole run's work, and the days without
  ephemerides would fail the rest.
- **A failed day fails its unit.** Simpler, but days without SP3/CLK
  products are common at the end of a backlog, and the days with
  products must not wait for them.
- **Only one run writes a store at a time.** It would make the
  in-memory state simpler, but ADR 0019 allows several writers, on S3
  from several machines.
- **VOD from the data in memory instead of the store.** It saves the
  read, but nothing checks that memory equals the store after removing
  duplicates and padding; with VOD in the worker pool the read is parallel and costs
  the same for every day.
- **Parallel commits to one branch.** Icechunk serializes them on the
  branch tip.
- **Store maintenance as a speed-up.** Compacting manifests and expiring
  snapshots changed none of the measured times.
