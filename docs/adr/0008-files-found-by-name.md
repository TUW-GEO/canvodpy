# Runs find files by their names, in any folder layout

A file's canVOD name carries its receiver identity and start time, so a
run scans each receiver's folder recursively, in any layout, and groups
files by the date in their names. Files with other names need a naming
recipe (canvod-filemap), which is then the truth for their identity;
having canvod-filemap installed never changes discovery by itself. Each
receiver needs its own folder, no two receivers may share an identity, and
two files that map to the same name, or overlap in time, stop the run.

## Considered options

An `identity` setting that would let one folder hold several receivers was
rejected: sorting the data is the user's job, and an extra setting that
can be wrong is a hidden source of mixed-up data.
