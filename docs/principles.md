---
title: Design Principles
description: The engineering and scientific principles that shape canVODpy — why the system works the way it does.
---

# Design Principles

This page explains the engineering and scientific choices behind canVODpy. It is
the "why" companion to [Architecture](architecture.md), which covers the "what"
and "how". Reading these principles will help you make changes that fit the grain
of the codebase — and understand why certain things that look configurable are, in
fact, hard constraints.

---

## 1. One data shape everywhere

**What:** Every GNSS reader — RINEX v2, RINEX v3, Septentrio SBF, NMEA — produces an
`xarray.Dataset` with exactly two dimensions: `epoch` (observation timestamps) and
`sid` (signal identifier, format `SV|Band|Code`, e.g. `G01|L1|C`). No other shape
is accepted downstream.

**Why (scientific):** A GNSS observation is fundamentally a value indexed by *when*
it was measured (`epoch`) and *which satellite signal* it came from (`sid`). All
subsequent operations — aligning canopy and reference receivers, retrieving VOD,
writing to the store — only need those two coordinates. The data shape is the
minimal common language of the pipeline.

**Why (engineering):** Reader-agnostic code. Augmentation, VOD retrieval, and
storage never ask "is this RINEX or SBF?". They operate on datasets by dimension
name. Adding a new reader requires only that it produce the `(epoch, sid)` shape.

**How:** `canvod.readers.validate_dataset` checks every reader's output: the two
dimensions, the signal coordinates (`sv`, `system`, `band`, `code`, frequencies),
an `SNR` variable, and attributes including `"File Hash"` (SHA-256 of the source
file). It lists every violation at once and raises; nothing is skipped silently.
VOD results have their own contract, `canvod.readers.validate_vod_dataset`
(`VOD`, `theta`, `phi` in radians), which the VOD store enforces on every write.

!!! note "What is a 'data contract'?"
    A data contract is an agreed shape for data passed between components. Here it
    means: dimensions `epoch` and `sid`, the required coordinates, variables and
    attributes. Components are free to add extra variables (polar angle, azimuth,
    further observables), but the contract is never optional.

---

## 2. Validation as a hard gate

**What:** Before any file is read or stored, `canvodpy run` finds every receiver's
files and checks them. If two files map to the same canonical name, if two files
overlap in time, or if one directory holds files of more than one receiver, the run
stops and prints a diagnostic listing the problem files. There is no "skip and
continue" mode for these cases.

**Why (scientific):** Two files covering the same time window would double-count
epochs, biasing SNR statistics and corrupting VOD. Files of two receivers in one
directory would be stored under the wrong receiver. The cost of a false alarm
(manual inspection) is far lower than the cost of silently wrong data.

**Why (engineering):** Fail-loud design. The error message always names the files,
so it tells the operator exactly what to fix.

**How:** `canvodpy.orchestrator.discovery`, used by `canvodpy run`, `Site.pipeline()`
and the Airflow tasks alike. `canvodpy config validate` (and `validate_data_dirs()` in
Airflow) runs the same discovery before processing and additionally lists the files a
run passes over because neither the naming convention nor a recipe recognizes them.

!!! warning "The naming convention is a hard gate, not an overridable default"
    Without a naming recipe, only files that follow the naming convention are
    processed. Configuring a `NamingRecipe` for non-standard filenames is the
    correct response to data that is not recognized, not renaming files by hand.

---

## 3. Reproducibility via versioned storage

**What:** Every write to a canVODpy data store ends with an immutable commit. The
entire state of the store — every array, every coordinate, every attribute — is
captured as a snapshot with an ID. Previous snapshots are never modified; they are
deleted only by store maintenance (snapshot expiry and garbage collection), which
runs only when you start it or switch it on (`canvodpy store maintain`).

**Why (scientific):** A published VOD time series must be traceable to the exact
data that produced it. If a processing bug is discovered and a reanalysis is run,
the original run and the corrected run must be distinguishable. Icechunk stores work
like a version-controlled repository: every commit has an ID that can be cited in a
paper or included in a data-publication record.

**Why (engineering):** Processing mistakes are survivable. Committing bad data does
not destroy the previous good state — rolling back is a one-line operation. This
removes the pressure to get every run perfect before writing.

**How:** `canvod-store` wraps the Icechunk v2 API: `repo.writable_session()` opens
a transaction, writes proceed inside it, and `session.commit()` finalizes the
snapshot. The commit log is accessible via `store.get_ops_log()` or visualized as
a history graph via `store.plot_commit_graph()` (which delegates to Icechunk's
native `repo.ancestry_graph()`).

!!! note "What does 'immutable snapshot' mean?"
    Once a commit is finalized, its contents cannot be changed. Subsequent writes
    create a *new* commit that extends the history. Reading an old snapshot
    (`repo.readonly_session(snapshot_id=...)`) always returns the data as it was
    at that point in time — regardless of what has been written since.

---

## 4. Layered, upward-free dependencies

**What:** Packages are arranged in layers (Foundation → Data I/O → Computation →
Persistence → Orchestration). No package imports from a package above it in the
stack. `canvod-vod` does not know about `canvod-store`; `canvod-store` does not
know about `canvodpy`.

**Why (scientific):** Scientists often want to apply one algorithm in isolation —
run the VOD formula on data from a different source, or use the hemispheric grid
without the full pipeline. Upward-free dependencies make this possible: install
`canvod-vod` alone and it works.

**Why (engineering):** Independent testing. The VOD formula can be unit-tested
without a store, a reader, or an internet connection.

**How:** Declared in each package's `pyproject.toml`; a test
(`canvodpy/tests/test_package_boundaries.py`) keeps every package from importing
the umbrella package. `canvod-utils` has no inter-package dependencies at all.
One exception remains to be removed: `canvod-grids` and `canvod-store` depend on
each other. See
[Architecture → Dependency Graph](architecture.md#dependency-graph) for the full
declaration.

---

## 5. Self-describing filenames as provenance

**What:** The naming convention encodes every piece of identity information — site,
receiver type, date, period, sampling interval, data format — into the filename
itself. No external database is needed to know what a file contains or which
receiver produced it.

**Why (scientific):** Provenance should survive a file copy. A GNSS archive that
relies on a separate metadata database to interpret its filenames becomes opaque
the moment that database is unavailable. A self-describing filename is still
meaningful when found on a USB drive years later.

**Why (engineering):** The canonical name drives these operations without
additional configuration:

- **Day and receiver assignment** — the date, start time and receiver identity
  come from the name, in any folder layout.
- **Overlap checks** — period and start time give each file's time span, so
  duplicates and overlapping files are found before anything is read.
- **Reader selection** — the type field (`rnx`, `sbf`, `nmea`) says which reader
  family applies.

Which canopy receiver is paired with which reference receiver is set in the
settings (`vod_analyses`), not derived from names.

**How:** The convention lives in `canvod-preflight` (`CanVODFilename`). Files with
other names are processed through a naming recipe (`canvod-filemap`): physical
files are never renamed, the recipe attaches a canonical name to each physical
path. All downstream processing uses the canonical name; the physical path is
retained only for opening the file.

---

## 6. Three-layer deduplication — never write the same data twice

**What:** Before any dataset is appended to the store, three successive checks run:
(1) does a file with this exact hash already exist? (2) does the time window of
this file overlap with data already in the store? (3) does this file overlap with
another file in the current batch? A file that fails a check is treated as already
stored: with the default write strategy (`skip`) it is not written, and the run
logs it; with `overwrite` its time range is replaced.

**Why (scientific):** Duplicate epochs in the store corrupt canopy/reference
alignment. If the reference receiver's DOY 1 is written twice, every
canopy/reference SNR difference computed from that day will be wrong, without any
error. The deduplication guard makes this class of mistake structurally
impossible.

**Why (engineering):** Idempotent ingestion. Running the same processing job twice
(for example, after a crash and restart) produces the same store state, not a store
with doubled data. The hash check is the fast path: identical content is detected
before any write occurs.

**How:** `_check_existing_with_temporal_overlap()` in the orchestrator runs all
three checks against the store's log of ingested files before writing;
`append_to_group()` in `canvod-store` checks hash and time overlap again at the
write itself. Together they cover both inter-run and intra-run duplication.

!!! note "What does 'idempotent' mean?"
    An operation is idempotent if running it twice produces the same result as
    running it once. Here: ingest the same file twice → the store contains exactly
    one copy of the data. The first run writes it; the second run detects the hash
    match and skips without error.

---

## 7. Code principles

Four rules for all canVODpy code. New code is checked against them in review.

**Explicit over implicit.** Problems fail loudly, with a message that says what
to do. There is no silent failure and no silent default: a default you can see
(in a function signature, or documented on a settings model) is fine; library
code that reads the settings file behind the caller's back, or falls back to a
value when something goes wrong, is not. Entry points (`canvodpy run`, `Site`)
read the settings and pass the values down. One exception is deliberate: a long
`canvodpy run` does not stop for one bad file; it warns, names the file and
goes on.

**One implementation per job (don't repeat yourself).** Every task has one code
path, used by the CLI, the Python API and Airflow alike. Two implementations of
the same job drift apart and give different results; the older one is
deprecated and points to the one that stays.

**Composition over inheritance.** Objects get their collaborators passed in
(dependency injection) instead of inheriting behavior. Inheritance is used for
pydantic models and for implementing an interface.

**Interfaces are abstract base classes.** Readers, ephemeris providers, VOD
calculators, grid builders and preprocessing steps implement an ABC
(`GNSSDataReader`, `EphemerisProvider`, `VODCalculator`, `BaseGridBuilder`,
`Op`), so a missing method fails as soon as the class is used, not halfway through
a run.

---

## File Naming Convention

canVODpy uses a canonical naming convention for all GNSS observation files,
designed to be compatible with the
[RINEX v3.04 long-name convention](https://files.igs.org/pub/data/format/rinex304.pdf)
while extending it with GNSS-Transmissometry–specific fields.

### Why the naming convention matters

A self-describing filename enables automatic **deduplication** (same canonical name
= same data), **receiver pairing** (reference and canopy files share all fields
except the single receiver-type character), and **provenance tracking** (date, site,
and format are readable without opening the file). This is why the convention is a
hard validation gate rather than a default that can be bypassed — see
[Principle 2](#2-validation-as-a-hard-gate) above.

### Format

```
{SIT}{T}{NN}{AGC}_R_{YYYY}{DOY}{HHMM}_{PERIOD}_{SAMPLING}_{CONTENT}.{TYPE}[.{COMPRESSION}]
```

<iframe src="diagrams/naming-convention-embed.html" style="width:100%;height:320px;border:none;display:block;margin:1.5rem 0;" loading="lazy"></iframe>

### Fields

| Field | Width | Description | Example |
|-------|-------|-------------|---------|
| `SIT` | 3 | Site ID, uppercase | `ROS`, `HAI`, `FON`, `LBS` |
| `T` | 1 | Receiver type: **R** = reference, **A** = active (below-canopy) | `R`, `A` |
| `NN` | 2 | Receiver number, zero-padded (01–99) | `01`, `35` |
| `AGC` | 3 | Data provider / agency ID, uppercase | `TUW`, `GFZ`, `MPI` |
| `_R` | 2 | RINEX data-source field — always `R` (receiver-generated) | `_R` |
| `YYYY` | 4 | Year | `2025` |
| `DOY` | 3 | Day of year (001–366) | `001`, `222` |
| `HHMM` | 4 | Start time (hours + minutes) | `0000`, `1530` |
| `PERIOD` | 3 | Batch size: 2-digit value + unit (S/M/H/D) | `01D`, `15M`, `01H` |
| `SAMPLING` | 3 | Data frequency: 2-digit value + unit (S/M/H/D) | `01S`, `05S`, `05M` |
| `CONTENT` | 2 | User-defined content code, default `AA` | `AA` |
| `TYPE` | 3–4 | File format, lowercase | `rnx`, `sbf`, `ubx`, `nmea` |
| `COMPRESSION` | — | Optional compression extension (part of the convention; runs do not read compressed files and warn about them, decompress them first) | `zip`, `gz`, `bz2`, `zst` |

!!! note "Receiver type: 'active' vs 'canopy'"
    In the filename, `T=A` denotes an **active** receiver — the below-canopy unit
    actively receiving attenuated signals. In the configuration API and validator,
    this role is called **canopy** (`ReceiverType.ACTIVE` in the code maps to
    `"canopy"` in configuration). Both terms refer to the same physical receiver;
    the difference reflects the code's adoption of the IGS convention (`A`) while
    the config API uses the more descriptive scientific term (`canopy`).

!!! note "The `_R` separator"
    `_R` is not simply "R for Receiver". It is the RINEX v3.04 **data-source
    field**, specifying how the data was produced: `R` means the file was generated
    directly by the receiver hardware (as opposed to `S` for a stream or `U` for
    unknown). canVODpy fixes this field to `R` because all ingested files originate
    from receiver hardware.

### Duration codes

The `PERIOD` and `SAMPLING` fields use a 2-digit value followed by a unit
character:

| Unit | Meaning | Example |
|------|---------|---------|
| `S` | Seconds | `05S` = 5 seconds |
| `M` | Minutes | `15M` = 15 minutes |
| `H` | Hours | `01H` = 1 hour |
| `D` | Days | `01D` = 1 day |

### Receiver types

| Code | Role | Description |
|------|------|-------------|
| `R` | Reference | Above canopy — unobstructed sky view |
| `A` | Active / canopy | Below canopy — signal attenuated by vegetation |

### Examples

**Daily merged, 5-second sampling (reference):**

```
ROSR01TUW_R_20250010000_01D_05S_AA.rnx
│  │ │ │     │       │    │   │   │  └── RINEX observation
│  │ │ │     │       │    │   │   └── content: default
│  │ │ │     │       │    │   └── sampling: 5 seconds
│  │ │ │     │       │    └── period: 1 day
│  │ │ │     │       └── start: 00:00
│  │ │ │     └── 2025, DOY 001
│  │ │ └── agency: TU Wien
│  │ └── receiver number 01
│  └── R = reference
└── site: ExampleSite
```

**Daily merged, 5-second sampling (active / below-canopy):**

```
ROSA01TUW_R_20250010000_01D_05S_AA.rnx
   ^
   A = active (below-canopy)
```

**15-minute sub-daily file, SBF format:**

```
ROSR35TUW_R_20232221530_15M_05S_AA.sbf
    ^^                  ^^^        ^^^
    receiver #35        15-min     Septentrio Binary Format
```

**Compressed daily file, 1-second sampling:**

```
HAIA01GFZ_R_20250010000_01D_01S_AA.rnx.zip
^^^                                    ^^^^
Hainich                                zip compressed
```

### SP3 and CLK files

SP3 orbit and CLK clock product files already follow the IGS long-name convention
and **do not** need renaming under this scheme.

[Full naming convention reference](packages/naming/overview.md)

---

*Questions or suggestions? Open a discussion on
[GitHub](https://github.com/nfb2021/canvodpy/discussions).*

---

**Next in the trail:** [API Levels](guides/api-levels.md) · [Contributor Setup](guides/contributor-setup.md) · [Architecture](architecture.md) · [Developing with coding agents](guides/ai-development.md)
