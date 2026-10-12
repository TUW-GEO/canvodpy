# canvod-preflight

`canvod-preflight` enforces the canVOD filename convention at the pipeline boundary.
Before any data is read, it validates that every file in a receiver directory can be
unambiguously identified and that no two files cover the same time window.

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
| `_R` | 2 | Literal separator | `_R` |
| `YYYY` | 4 | Year | `2025` |
| `DOY` | 3 | Day of year (001--366) | `001` |
| `HHMM` | 4 | Start time (hours + minutes) | `0000` |
| `PERIOD` | 3 | Batch duration: value + unit | `01D`, `15M` |
| `SAMPLING` | 3 | Data frequency: value + unit | `05S`, `01S` |
| `CONTENT` | 2 | User-defined content code | `AA` |
| `TYPE` | 2--4 | File format, lowercase | `rnx`, `sbf` |
| `COMPRESSION` | -- | Optional compression extension | `zip`, `gz` |

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
| `0000` | Start | 00:00 UTC |
| `01D` | Period | 1-day file |
| `05S` | Sampling | 5-second intervals |
| `AA` | Content | Default |
| `rnx` | Type | RINEX observation |

---

## Pre-pipeline validation

`canvod-preflight` is a **mandatory hard gate** that runs before any data is read.
It checks two things for each receiver directory:

1. **Every file can be identified** — each filename matches a known naming pattern.
   Unrecognised files block processing with a diagnostic listing the problem files.
2. **No temporal overlaps** — no two files cover the same time window.
   Overlapping files are ambiguous; they block processing until resolved.

```bash
# CLI — validate a single receiver directory
canvod-preflight validate /data/my_site/01_reference \
    --site ROS --agency TUW --receiver 1 --role reference

# Shortcut for a site configured in canvod-settings.yaml
just config-check-data <site>
```

Validation is also triggered automatically by `just config-validate` (which calls
`uv run canvodpy config validate`).

---

## Files that don't follow the convention

If your GNSS receiver outputs files in a proprietary or legacy format (RINEX v2
short names, Septentrio binary, etc.), the optional
[`canvod-filemap`](https://github.com/nfb2021/canvodpy-extensions) package provides
a **recipe-based mapping layer** that virtualises physical filenames to canonical names
without renaming anything on disk.

Install it separately from the [canvodpy-extensions](https://github.com/nfb2021/canvodpy-extensions)
repo (see [Optional Extensions](../../guides/extensions.md) for details and alternatives):

```bash
uv add "canvod-filemap @ git+https://github.com/nfb2021/canvodpy-extensions.git@v0.1.0#subdirectory=packages/canvod-filemap"
```

Then reference a recipe from `canvod-settings.yaml`:

```yaml
sites:
  my_site:
    receivers:
      reference_01:
        recipe: my_site_reference   # → config/recipes/my_site_reference.yaml
```

### NamingRecipe YAML format

A recipe tells the mapper how to extract canonical fields from a physical filename:

```yaml
name: examplesite_reference
description: Septentrio RINEX v2 files from ExampleSite reference receiver
site: ROS
agency: TUW
receiver_number: 1
receiver_type: reference
sampling: "05S"
period: "15M"
file_type: rnx
layout: yyddd_subdirs   # or yyyyddd_subdirs, flat
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
| `hour_letter` | RINEX v2 hour letter (a--x = 0--23) |
| `minute` | Minute (0--59) |
| `skip` | Ignore N characters |

`uv run canvodpy config init` copies recipe templates to `config/recipes/`
alongside `canvod-settings.yaml`. See the
[canvod-filemap documentation](https://github.com/nfb2021/canvodpy-extensions)
for the full API (`FilenameMapper`, `VirtualFile`, `FilenameCatalog`).

---

!!! example "Try it"
    [04 · Naming Convention](../../notebooks/_build/04_naming_convention.html){target=_blank}
    · [view source on molab](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/04_naming_convention.py)
