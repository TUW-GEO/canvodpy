# canvod-preflight

`canvod-preflight` defines the canVOD filename convention: `CanVODFilename` parses and
builds canonical names, and `find_overlaps` finds files whose named time spans overlap.
`canvodpy run` uses both to decide which files it processes.

---

## The CanVODFilename Convention

Every canVOD-compatible GNSS file follows this naming format:

```
{SIT}{T}{NN}{AGC}_R_{YYYY}{DOY}{HHMM}_{PERIOD}_{SAMPLING}_{CONTENT}.{TYPE}[.{COMPRESSION}]
```

<iframe src="../../diagrams/naming-convention-embed.html" style="width:100%;height:320px;border:none;display:block;margin:1.5rem 0;" loading="lazy"></iframe>

### Fields

| Field | Width | Description | Example |
|-------|-------|-------------|---------|
| `SIT` | 3 | Site ID, uppercase | `ROS`, `HAI` |
| `T` | 1 | Receiver type: **R** = reference, **A** = active (below-canopy) | `R`, `A` |
| `NN` | 2 | Receiver number, zero-padded | `01`, `35` |
| `AGC` | 3 | Data provider / agency ID | `TUW`, `GFZ` |
| `_R` | 2 | RINEX data-source field, always `R` (receiver-generated) | `_R` |
| `YYYY` | 4 | Year | `2025` |
| `DOY` | 3 | Day of year (001--366) | `001` |
| `HHMM` | 4 | Start time (hours + minutes) | `0000` |
| `PERIOD` | 3 | Batch duration: value + unit | `01D`, `15M` |
| `SAMPLING` | 3 | Data frequency: value + unit | `05S`, `01S` |
| `CONTENT` | 2 | User-defined content code | `AA` |
| `TYPE` | 3--4 | File format, lowercase; runs read `rnx`, `sbf` and `nmea` | `rnx`, `sbf`, `nmea`, `ubx` |
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

| Part | Value | Meaning |
|------|-------|---------|
| `ROS` | Site | ExampleSite |
| `R` | Type | Reference (above-canopy) |
| `01` | Number | Receiver 01 |
| `TUW` | Agency | TU Wien |
| `2025001` | Date | 2025, DOY 001 |
| `0000` | Start | 00:00 GPS time |
| `01D` | Period | 1-day file |
| `05S` | Sampling | 5-second intervals |
| `AA` | Content | Default |
| `rnx` | Type | RINEX observation |

As in the RINEX 3 long names, the start time is in the time scale of the
observations, which for canvodpy is GPS time.

---

## Which files a run processes

`canvodpy run` scans each receiver's `directory` recursively, in any folder layout (all
files in one folder, one folder per day, or deeper nesting). A file's day comes from the
date in its name, not from its folder. Without a naming recipe, only files that follow
the convention are processed. A run stops before reading any data if

1. a directory holds files of more than one receiver,
2. two files map to the same canonical name, or
3. two files cover the same time, for example a daily file next to the 15-minute files
   of the same day.

With `reader_format: auto`, the reader is detected per day: SBF and NMEA by file type,
RINEX 2 or 3 from the file header. A day whose files need different readers stops the
run; set `reader_format`, or keep each format in its own directory.

Files a run does not process (names that neither the recipe nor the convention
recognizes, or a file type the receiver's `reader_format` does not read) do not stop it.
The run processes the other files and logs one warning per receiver,
`files_not_processed`, with the number of such files per file type and an example.

Compressed files are never processed, with or without a recipe: general compression
(`.gz`, `.Z`, `.zip`, `.bz2`, `.xz`, `.zst`, ...) and Hatanaka-compressed RINEX (`.crx`,
RINEX 2 `.yyd`). They get a warning of their own, `compressed_files_not_processed`.
Decompress them first (for Hatanaka, `crx2rnx`). A receiver directory holding only
compressed files fails the check below.

Check a site before processing it; the check finds the files exactly as a run does and
also lists the files a run would pass over:

```bash
just config-check-data <site>   # canvodpy config validate --site <site>
```

!!! note "Deprecated"
    The `canvod-preflight` command and the mapping and validation classes of this
    package (`FilenameMapper`, `DataDirectoryValidator`, `SiteNamingConfig`,
    `ReceiverNamingConfig`) are left over from development and will be removed with the
    next major version. Use `canvodpy config validate` and naming recipes instead.

---

## Files that don't follow the convention

If your GNSS receiver outputs files in a proprietary or legacy format (RINEX v2
short names, Septentrio binary, etc.), the optional
[`canvod-filemap`](https://github.com/nfb2021/canvodpy-extensions) package provides
a **recipe-based mapping layer** that virtualises physical filenames to canonical names
without renaming anything on disk.

In a canvodpy checkout, install it with `uv sync --group filemap`; elsewhere from
GitHub (see [Optional Extensions](../../guides/extensions.md)).

Then reference a recipe from `canvod-settings.yaml`:

```yaml
sites:
  my_site:
    receivers:
      reference_01:
        recipe: my_site_reference   # → <config dir>/recipes/my_site/my_site_reference.yaml
```

### NamingRecipe YAML format

A recipe tells canvodpy how to extract canonical fields from a physical filename:

```yaml
name: examplesite_reference
description: Septentrio RINEX v2 files from ExampleSite reference receiver
site: ROS
agency: TUW
receiver_number: 1
receiver_type: reference
sampling: "05S"
period: "15M"
content: "AA"
file_type: rnx
glob: "*.??o"
fields:
  - skip: 4          # "rref"
  - doy: 3           # "001"
  - hour_letter: 1   # "a"
  - minute: 2        # "15"
  - skip: 1          # "."
  - yy: 2            # "25"
  - skip: 1          # "o"
```

| Field key | Description |
|-----------|-------------|
| `year` | 4-digit year |
| `yy` | 2-digit year (80--99 = 19xx, 00--79 = 20xx) |
| `doy` | Day of year |
| `month` / `day` | Month + day of month (converted to DOY) |
| `hour` | Hour (0--23) |
| `hour_letter` | RINEX v2 session letter (a--x = hours 0--23; `0` = daily file, its period becomes `01D`) |
| `minute` | Minute (0--59) |
| `skip` | Ignore N characters |

Recipe files are kept per site, in `<config dir>/recipes/<site>/<recipe>.yaml`.
`just naming-init my_site my_site_reference` creates one from the template that
ships with canvod-filemap. See the
[canvod-filemap documentation](https://github.com/nfb2021/canvodpy-extensions)
for the full recipe API.

---

!!! example "Try it"
    [01 — Naming Convention](../../notebooks/_build/01_naming_convention.html){target=_blank}
    · [view source on molab](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/01_naming_convention.py)
