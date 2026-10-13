---
title: Design principles
description: The rules that shape canVODpy, why they exist, and where the code enforces them.
---

# Design principles

This page explains the rules that shape canVODpy and why they exist. Each
section says what the rule is, why canVODpy follows it, and where the code
enforces it. [Architecture](architecture.md) describes the packages and how
data flows through them.

Some of these rules can look like settings that you could switch off. They
aren't: each one protects the data from a mistake that would otherwise go
unnoticed.

---

## One data shape everywhere

Every reader returns an `xarray.Dataset` with two dimensions:

- `epoch`: the time of the observation;
- `sid`: the signal identifier, `SV|Band|Code`, for example `G01|L1|C`.

All later steps work on these two dimensions only: the matching of canopy
and reference receivers, the VOD calculation, and the store. They
never ask whether the data came from RINEX, SBF, or NMEA. A new reader only
has to return the same shape.

`canvod.readers.validate_dataset` checks the output of every reader:

- the two dimensions;
- the signal coordinates `sv`, `system`, `band`, `code`, `freq_center`,
  `freq_min`, and `freq_max`;
- the data variables, every one on `(epoch, sid)`;
- the attributes `Created`, `Software`, `Institution`, and `File Hash`.

It lists every problem it finds and then raises a `ValueError`. VOD
datasets have their own check, `canvod.readers.validate_vod_dataset`: the
same dimensions and coordinates, and the variables `VOD`, `theta` and
`phi`, with the angles in radians. The VOD store runs it on every VOD
write.

A reader can add more variables, such as further observables. It can't
leave out what the check requires.

---

## Problems stop the run before it reads a file

Before a run reads a file, it finds the files of every receiver and checks
them. The run stops, and lists the files concerned, if:

- two files map to the same canVOD file name;
- two files of the same type cover overlapping time spans, for example a
  daily file next to the 15-minute files of the same day;
- one folder holds the files of more than one receiver.

There is no option to skip these files and go on. Two files for the same
hours would write those epochs twice, and the files of two receivers in one
folder would be stored under the wrong receiver. Looking at a list of files
costs less than finding wrong data in a store later.

The checks live in `canvodpy.orchestrator.discovery`. `canvodpy run`,
`Site.pipeline()`, and the Airflow tasks all use it. `canvodpy config
validate`, and `validate_data_dirs()` in Airflow, run the same checks
without processing anything. They also list the files that a run passes
over because neither the naming convention nor a naming recipe recognizes
them.

---

## Every write is a versioned commit

Every write to a canVODpy store ends with a commit. The commit is a
snapshot of the whole store, with an ID. Later writes add new snapshots and
never change old ones. Only store maintenance deletes old snapshots:
`canvodpy store maintain`, or `canvodpy store maintain-due` after you turn
it on in the settings (`maintenance.enabled`).

A published VOD time series has to be traceable to the data that produced
it. If you find a processing error and process the data again, the first
and the corrected results stay apart, each under its own snapshot ID. You
can cite that ID in a paper or a data publication. A bad write doesn't
destroy the good state before it: Icechunk's `reset_branch` moves a branch
back to an earlier snapshot.

`canvod-store` uses Icechunk for this. Each write opens a session, writes
into it and commits it. To see the history:

- `store.get_ops_log()` lists the operations on the store;
- `store.plot_commit_graph()` draws the commits as a graph, with Icechunk's
  `repo.ancestry_graph()`;
- `canvodpy store log` prints both in the terminal.

To read the store as it was at an earlier commit, open a read-only session
on that snapshot:
`store.repo.readonly_session(snapshot_id=...)`.

!!! example "Try it in a notebook"

    Open [Icechunk store](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/11_icechunk_store.py?mode=edit) in molab, the online notebook service of marimo.

---

## Packages depend only on the layers below them

The packages form layers: foundation, data input, computation, persistence,
presentation, and orchestration. A package imports only from packages in its own layer or
below. [Architecture](architecture.md#packages-and-layers) lists which package
sits in which layer.

This lets you use one part on its own. For example, you can run the VOD
calculation on data from another source without a store or a reader. It
also lets you test each package on its own.

Each package declares its dependencies in its `pyproject.toml`.
`canvodpy/tests/test_package_boundaries.py` makes sure that no package
imports the `canvodpy` umbrella package. `canvod-utils` depends on no other
canVODpy package.

One exception remains: `VODCalculator.from_icechunkstore()` in
`canvod-vod` imports `canvod-store`, which `canvod-vod` doesn't declare.
The method is left over from development and is removed with the
next major version. The old names `store_grid`, `load_grid`, and
`AnalysisStorage` in `canvod-grids` also import `canvod-store`; they
moved to `canvod-store` and are removed with the next major version
as well.

---

## The filename says what the file holds

A canVOD file name holds everything that identifies the file: site,
receiver, date and start time, the time span the file covers, the
sampling interval, and the file format. No database is needed to know what
a file holds or which receiver recorded it, and that information survives
when the file is copied.

From the name alone, a run:

- assigns the file to its day and its receiver, in any folder layout;
- finds duplicates and overlapping files before it reads any of them;
- picks the reader from the file type: `rnx`, `sbf`, `nmea`, or the type
  of an installed reader plugin.

Which canopy receiver is paired with which reference receiver is set in
the settings, under `vod_analyses`, not read from the names.

The convention is defined in `canvod-preflight` (`CanVODFilename`). Files
with other names are read through a naming recipe of the optional
`canvod-filemap` extension (see [Optional extensions](guides/extensions.md)).
The recipe gives each file a canVOD file name and never renames the file
itself. All later steps use the canVOD file name; the file's own path is
used only to open it. The fields of the name are listed in
[canvod-preflight](packages/naming/overview.md#the-canvod-filename-convention).

!!! example "Try it in a notebook"

    Open [Naming convention](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/04_naming_convention.py?mode=edit) in molab, the online notebook service of marimo.

---

## The same data is never written twice by default

Before a file's data goes into the GNSS store, the run checks three things:

1. Does the store already hold a file with the same hash?
2. Does the file's time span overlap data already in the store?
3. Does the file's time span overlap another file of the same batch?

A file that fails a check counts as already stored. What happens then
depends on `gnss_store_strategy` in the settings:

- `skip`, the default: the data isn't written, and the run logs the file.
- `overwrite`: the epochs of the file's time span are deleted and written
  again.
- `unsafe_append`: the data is written again on top of what's there. The
  store then holds the same epochs twice. Use it only if you have a
  specific reason.

Epochs stored twice break the matching of canopy and reference receivers
without an error. With `skip`, running the same job twice, for example
after a crash, leaves the store as it was after the first run.

The run makes the three checks in
`_check_existing_with_temporal_overlap()` of the orchestrator.
`append_to_group()` in `canvod-store` checks the hash and the time span
again when it writes.

---

## Code principles

Four rules apply to all canVODpy code. Reviews check new code against them.

**Explicit over implicit.** A problem stops the code with a message that
says what to do. Nothing fails silently, and nothing falls back to a
default silently. A default that you can see is fine: one in a function signature, or one
documented on a settings model. Library code that reads the settings file behind
the caller's back, or picks a value when something goes wrong, isn't.
Entry points such as `canvodpy run` and `Site` read the settings and pass
the values down. One exception is deliberate: a long `canvodpy run`
doesn't stop for one bad file. It warns, names the file, and goes on.

**One implementation per task.** Every task has one code path, which the
command line, the Python API, and Airflow all use. Two implementations of
the same task drift apart and give different results. When two exist, the
older one is deprecated and its warning names the one that stays.

**Composition over inheritance.** Objects get the objects they work with
passed in, instead of inheriting behavior. Inheritance is used for Pydantic
models and to implement an interface.

**Interfaces are abstract base classes.** Readers, ephemeris providers, VOD
calculators, grid builders, and preprocessing steps implement an abstract
base class: `GNSSDataReader`, `EphemerisProvider`, `VODCalculator`,
`BaseGridBuilder`, and `Op`. A class that lacks a method then fails when you
create it, not halfway through a run.

---

**Next:** [architecture](architecture.md) · [API levels](guides/api-levels.md) ·
[contributor setup](guides/contributor-setup.md) ·
[developing with coding agents](guides/ai-development.md)
