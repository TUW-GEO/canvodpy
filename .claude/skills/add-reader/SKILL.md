---
name: add-reader
description: Add a reader for a new GNSS file format to canvod-readers and wire it into runs (contract, registration, discovery, settings, store labels, tests). Use when supporting a new receiver file format.
---

# Add a reader

A reader turns one file into a dataset that passes `validate_dataset`. The
contract lives in `packages/canvod-readers/src/canvod/readers/base.py`;
read it first, and `docs/packages/readers/building-a-reader.md`. Use the
closest existing reader as the template:
`packages/canvod-readers/src/canvod/readers/rinex/v3_04.py` (text),
`packages/canvod-readers/src/canvod/readers/sbf/reader.py` (binary).

## 1. The reader

- A new folder under `packages/canvod-readers/src/canvod/readers/`, a class
  that subclasses `GNSSDataReader` and implements every abstract member
  of `packages/canvod-readers/src/canvod/readers/base.py`.
- Build the dataset with `DatasetBuilder` (`packages/canvod-readers/src/canvod/readers/builder.py`), passing
  `time_system="GPS"`: every stored epoch is GPS time, so convert other
  scales first (UTC: `gnss_specs.leap_seconds.utc_to_gps`). Don't build SIDs or
  frequency coordinates by hand.
- Fail loudly on corrupt input; never return a partial dataset silently.
- No settings reads: options are arguments with visible defaults.

## 2. Wire it into runs

Each of these names the formats it knows; keep them in step:

| Where | What |
|---|---|
| `canvodpy/src/canvodpy/__init__.py` | register in `_register_builtin_components` |
| `canvodpy/src/canvodpy/orchestrator/discovery.py` | `_READER_FILE_TYPES`, `_ALL_FILE_TYPES` |
| `packages/canvod-preflight/src/canvod/preflight/convention.py` | `FileType`, if the file type is new |
| `canvodpy/src/canvodpy/factories.py` | `ReaderFactory._detect_format`, if `reader_format: auto` should find it |
| `packages/canvod-config/src/canvod/config/models/sites.py` | the `reader_format` values and description |
| `packages/canvod-store/src/canvod/store/viewer.py` | `_FORMAT_LABELS` |

## 3. Tests and docs

- Tests in `packages/canvod-readers/tests/`: `validate_dataset` passes,
  epochs and time system are right, corrupt files fail with a clear
  message. Real files go into the test-data repository; tests that need
  them are marked `integration`.
- A page under `docs/packages/readers/`, the readers' `AGENTS.md` table.
- `just test-package canvod-readers`, then `just test-package canvodpy`.
