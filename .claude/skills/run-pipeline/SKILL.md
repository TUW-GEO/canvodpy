---
name: run-pipeline
description: Run canvodpy on a site's data (process days, compute VOD, backfill missing VOD), or help a user do so. Use when asked to run, process or ingest data, or to set up a first run.
---

# Run the pipeline

Running on real data writes to the user's stores and can take hours: get
the user's go-ahead before every run, and say which site, days and
settings file.

## 1. Check the setup

```bash
just doctor                       # version, environment, which settings file
just config-validate              # the settings file
just config-check-data <site>     # which files each receiver would use
```

`config-check-data` uses the same file discovery as a run: a file it does
not list is not processed. Files with other than canonical names need a
naming recipe (`just naming-init <site> <name>`, canvod-filemap installed
with `uv sync --group filemap`); see `docs/packages/naming/overview.md`.

## 2. Preview, then run

```bash
uv run canvodpy run --site <site> --start <YYYYDOY> --end <YYYYDOY> --dry-run
just run <site> <YYYYDOY> <YYYYDOY>
```

The recipe and the `canvodpy run` command are the same code. Without
`--start`, `canvodpy run` resumes after the last day in the store; other
options (`--no-vod`, `--workers`, `--ephemeris-source`, `--config`,
`--write-catalog`) are in
`docs/guides/api-levels.md`. A settings folder other than the default:
`just config_dir=<folder> run ...`.

From Python, `Site(site).pipeline()` gives the same results; use it only
when the user scripts runs (several sites, a notebook). Never suggest the
deprecated surfaces (`FluentWorkflow`, `process_date()`, `VODWorkflow`,
`canvodpy.functional`).

## 3. Check the result

- The run ends with a summary; files it did not process are listed
  (`files_not_processed`; compressed ones apart,
  `compressed_files_not_processed`). Report them to the user.
- `just store-info <site>` and `just store-log <site>` show what the
  store holds and its history.
- With `--write-catalog`, the run writes the STAC catalog of the data
  root after its last commit. If a store can't be described, the run
  exits with code 1, its data stays committed, and the error lists each
  store with its reason. Fix those stores, then run
  `uv run canvodpy stac write`.

## VOD only

- `uv run canvodpy vod --site <site> --analysis <name>`: VOD from an
  existing GNSS store, without reading files again.
- `uv run canvodpy vod-reconcile --site <site> --analysis <name>`: lists
  days with observations but no VOD; `--execute` computes them.
