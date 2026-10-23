# A run lists the folders of the days it processes

A run finds every file of the days it processes, without a flag. It lists
the folders that hold one of those days, the folders without a data file
(the receiver directory, year folders) and the folders not yet in the file
index. Every other folder comes from the file index in the run history
(ADR 0018). The scan runs once the run's range is known. A run without
dates gets its range from where the stores end, so a daily run lists a
few folders. The Airflow tasks use the same rule, with the task's day as
the range. The data check (`canvodpy config validate`) lists every folder.

## Considered options

- **No file index.** Every run lists every folder. Always right, but a
  cold listing on a network share costs about 50 ms per day folder: about
  42 s per receiver for a few years of day folders, on every run, also
  for a daily run of one day.
- **The index, with folders of the last 30 days listed again** (the first
  design, never released). Older folders came from the index, so a file
  added to one of them was missed without a message; `canvodpy run
  --rescan` listed every folder. It happened twice in testing: an
  end-to-end run found 81 and 79 of 96 files and skipped the VOD
  silently, and a test of a day written in forks stored 8640 of 17280
  epochs. The 30 days counted from today, not from the run's range, so
  reprocessing an old range always hit it.
- **The index, plus each folder's modification time.** A folder whose
  modification time changed is listed again. That needs one call per
  folder, which on a network share costs about as much as listing it, and a file
  replaced in place does not change the folder's time on every file
  system.
- **The index, with the folders of the run's range listed** (chosen). The
  days a run processes are always listed, so the run sees all their
  files; the folders of other days, the bulk of an archive, come from the
  index.

## Consequences

- `--rescan`, `Site.pipeline(rescan=True)` and the 30-day rule are gone.
  They were never released, so nothing is deprecated.
- One case remains: a file for a day in the range, put into a folder that
  held only days outside it. The run takes that folder from the index and
  misses the file. A run whose `--start`/`--end` cover that folder's days
  finds it, and so does every run after the run history is deleted. The
  docs name this case.
- A file replaced in place (same name, new content) is the user's
  responsibility: the run finds it by name and does not compare contents.
- Reprocessing an old range lists that range's folders cold, about 18 s
  per receiver per year of day folders on a network share. A daily run lists only the
  folders of its days, and the in-process cache serves every lookup after
  the first.
