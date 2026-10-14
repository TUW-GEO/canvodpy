# Every run records itself in a run history, one SQLite file per machine

A run records what it does in the **run history**: one SQLite file per
machine, in the log folder (`processing.logging.log_dir`), opened in WAL
mode. A run writes its start (settings, canvodpy version and commit,
machine facts, worker count, an optional free-text label), the
receiver-days it plans, its progress per receiver-day, the time of each
stage, samples of CPU, memory and free disk, its warnings and errors, and
its end and result. Every entry point writes it the same way, because
canvodpy writes it, not the command line, Python, or a scheduler around
it. Rows are kept; nothing rotates them away.

The run dashboard (`canvodpy dashboard`) reads only the run history. The
paper benchmark reads it too: its figures come from a script outside
canvodpy that groups runs by label. The log files stay for diagnosing a
run; they are no longer a data source.

The same file may hold an index of the files found per receiver folder,
in tables of its own. If the index is lost or out of date, the next run
builds it again.

## Considered options

- **Keep reading the log files** (the dashboard until now). The
  performance log rotates, so history disappears after a few weeks of a
  long run, and every refresh parses every line again.
- **One JSON-lines file per run.** Easy to write, but every question
  across runs (all runs of a site, the repetitions of a label) reads and
  parses every file, and there is no query language.
- **DuckDB.** Fast for analysis and works with marimo's SQL cells, but
  only one process may open a file for writing, and while it does, other
  processes cannot read it: the dashboard would be locked out of a
  running run.
- **The store's log book.** A store records what was written to it, not
  how long it took or on which machine; runs that fail before writing
  leave nothing there.

SQLite comes with Python (no new dependency); it allows one writer and any
number of readers across processes at the same time in WAL mode, and
marimo's SQL cells, pandas, and DuckDB read it.

## Consequences

- The run history must be on a local disk, because SQLite's WAL mode needs
  shared memory and does not work on a network drive.
- Runs happen on one machine (user, 2026-10-14), so one file per machine
  sees every run of that machine. Runs on several machines have several
  run histories.
