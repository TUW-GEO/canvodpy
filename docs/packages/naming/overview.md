# canvod-preflight

`canvod-preflight` defines the canVOD filename convention: `CanVODFilename` parses and
builds canonical names, and `find_overlaps` finds files whose named time spans overlap.
Runs from the command line and from Python use both to decide which files they
process.

---

## The canVOD filename convention

Every canVOD-compatible GNSS file follows this naming format:

```
{SIT}{T}{NN}{AGC}_R_{YYYY}{DOY}{HHMM}_{PERIOD}_{SAMPLING}_{CONTENT}.{TYPE}[.{COMPRESSION}]
```

<iframe src="../../diagrams/naming-convention-embed.html" style="width:100%;height:320px;border:none;display:block;margin:1.5rem 0;" loading="lazy"></iframe>

### Fields

| Field | Width | Description | Example |
|-------|-------|-------------|---------|
| `SIT` | 3 | Site ID, uppercase | `ROS`, `HAI` |
| `T` | 1 | Receiver type: **R** = reference, **A** = active (below the canopy) | `R`, `A` |
| `NN` | 2 | Receiver number, zero-padded | `01`, `35` |
| `AGC` | 3 | Data provider / agency ID | `TUW`, `GFZ` |
| `_R` | 2 | RINEX data-source field, always `R` (receiver-generated) | `_R` |
| `YYYY` | 4 | Year | `2025` |
| `DOY` | 3 | Day of year (001--366) | `001` |
| `HHMM` | 4 | Start time (hours + minutes) | `0000` |
| `PERIOD` | 3 | Batch duration: value + unit | `01D`, `15M` |
| `SAMPLING` | 3 | Data frequency: value + unit | `05S`, `01S` |
| `CONTENT` | 2 | User-defined content code | `AA` |
| `TYPE` | 2--8 | File format, lowercase; runs read `rnx`, `sbf` and `nmea`, and the type of each installed [reader plugin](../../guides/plugins.md) | `rnx`, `sbf`, `nmea`, `ubx` |
| `COMPRESSION` | -- | Optional compression extension; runs do not read compressed files (warning `compressed_files_not_processed`), decompress them first | `zip`, `gz` |

### Duration codes

| Unit | Meaning | Example |
|------|---------|---------|
| `S` | Seconds | `05S` = 5 seconds |
| `M` | Minutes | `15M` = 15 minutes |
| `H` | Hours | `01H` = 1 hour |
| `D` | Days | `01D` = 1 day |

### Example

```
ROSR01TUW_R_20250010000_01D_05S_AA.rnx
```

| Part | Field | Meaning |
|------|-------|---------|
| `ROS` | Site | Site ID `ROS` |
| `R` | Type | Reference receiver |
| `01` | Number | Receiver 01 |
| `TUW` | Agency | TU Wien |
| `2025001` | Date | 2025, day of year 001 |
| `0000` | Start | 00:00 GPS time |
| `01D` | Period | 1-day file |
| `05S` | Sampling | 5-second intervals |
| `AA` | Content | Default |
| `rnx` | Type | RINEX observation |

As in the RINEX 3 long names, the start time is in the time scale of the
observations, which for canVODpy is GPS time.

!!! example "Try it in a notebook"

    Open [Naming convention](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/04_naming_convention.py?mode=edit) in molab, the online notebook service of marimo.

---

## Which files a run processes

A run scans each receiver's `directory` recursively, in any folder layout (all
files in one folder, one folder per day, or deeper nesting). A file's day comes from the
date in its name, not from its folder. Without a naming recipe, only files that follow
the convention are processed. A run stops before reading any data if

1. a directory holds files of more than one receiver,
2. two files map to the same canonical name, or
3. two files cover the same time, for example a daily file next to the 15-minute files
   of the same day.

### Folders of other days come from the file index

Listing a folder on a network drive is slow: about 50 ms per day folder on
an SMB share, so a few years of day folders take most of a minute per
receiver. A run therefore keeps a **file index**, the names it found in
each folder, in the [run history](../../guides/diagnostics.md#the-run-history).
A run lists

- every folder that holds a day the run processes,
- folders without a data file (for example the receiver directory itself
  and year folders), and
- folders that are not in the index yet.

Every other folder comes from the index, without asking the drive. A run
therefore finds every file of the days it processes, also a file added
to an old folder since the previous run. A run without `--start` starts
where the stores end, so a daily run lists only a few folders.

One case is not seen: a file for a day the run processes, put into a
folder that held only other days. Say the folder `25001` held only files
of 2025-001, and a file of 2025-100 is copied into it. A run of 2025-100
takes `25001` from the index and misses the file. Run once with `--start`
and `--end` covering the folder's days (here `--start 2025001 --end 2025001`),
or delete the run history; either way the folder is listed again. The same
holds for a file deleted, renamed or compressed in a folder of other days.
A file replaced in place, with the same name and new content, is your
responsibility: a run finds files by name and does not compare contents.

The Airflow tasks follow the same rule for their day. The data check,
`canvodpy config validate`, always lists every folder. If the run history
is deleted or its index can't be read, the next run lists every folder and
writes the index again. A dry run reads the index but never writes it, so
it shows the files a run would find. See
[ADR 0020](../../adr/0020-run-lists-folders-of-its-days.md) for the
reasons.

With `reader_format: auto`, the reader is detected per day: SBF and NMEA by file type, and
RINEX 2 or 3 by the file header. A day whose files need different readers stops the
run; set `reader_format`, or keep each format in its own directory.

Files a run does not process (names that neither the recipe nor the convention
recognizes, or a file type the receiver's `reader_format` does not read) do not stop it.
The run processes the other files and logs one warning per receiver,
`files_not_processed`, with the number of such files per file type and an example.

Compressed files are never processed, with or without a recipe: general compression
and archives (`.gz`, `.Z`, `.zip`, `.bz2`, `.xz`, `.zst`, `.7z`, `.tgz`, `.tar`, and `.rar`) and Hatanaka-compressed RINEX (`.crx`,
RINEX 2 `.yyd`). They get a warning of their own, `compressed_files_not_processed`.
Decompress them first (for Hatanaka, `crx2rnx`). A receiver directory holding only
compressed files fails the check below.

Check a site before processing it; the check finds the files exactly as a run does and
also lists the files a run would pass over:

```bash
canvodpy config validate --site <site>
```

---

## Files that don't follow the convention

A run processes only files with canonical names. For files with other names,
for example RINEX v2 short names or the names a receiver's firmware gives its
SBF files, set a naming recipe on the receiver:

```yaml
sites:
  my_site:
    receivers:
      reference_01:
        recipe: my_site_reference
```

The recipe gives each file a canonical name without renaming it on disk.
Naming recipes need an optional extension; see
[Optional extensions](../../guides/extensions.md).

A recipe can also be read from a URL, so that every machine uses the same
recipe from one repository. The URL is the raw link of the file, pinned to
a commit or a tag:

```yaml
        recipe: https://raw.githubusercontent.com/<account>/<recipes-repo>/<commit>/my_site/my_site_reference.yaml
```

A tag is written `refs/tags/<tag>` in the URL; a branch is refused. A
commit is the only pin that never changes: a tag can be moved. The
store records the URL and the sha256 of the file it was made with. A
fetched recipe is cached in the system's temporary folder, so a run
without network access works once the recipe was fetched. A recipe in a
private repository needs a GitHub token with read access in `GH_TOKEN`
or `GITHUB_TOKEN`; canvodpy never stores it
([ADR 0022](../../adr/0022-credentials-from-the-environment.md)).
