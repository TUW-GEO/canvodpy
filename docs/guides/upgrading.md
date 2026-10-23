---
title: Upgrading to v1.0.0
description: What to do before your first run with canVODpy v1.0.0 - migrate your stores, update your settings file, and replace deprecated code.
---

# Upgrading to v1.0.0

This page is for everyone who used canVODpy 0.x. Do the
[four steps](#before-your-first-run) before your first run with v1.0.0;
the rest of the page lists what changed, what is deprecated and what is new.

!!! warning "Stores written with 0.x must be migrated"

    A v1.0.0 run refuses a store written by canVODpy 0.x and names the
    command that migrates it. A nightly run stops there until you migrate.
    Migrating takes one command per site and keeps every earlier snapshot
    readable.

---

## Before your first run

### 1. Check the settings file

```bash
canvodpy config validate
```

It names every setting that is missing or no longer allowed, with its
dotted key. A settings file from 0.x typically needs:

| Setting | Why |
|---|---|
| `processing.logging.log_dir` | Required for a run: the folder of the log files. |
| `processing.metadata.publisher`, `processing.metadata.license`, `processing.metadata.naming_authority` | Required to create a store; the metadata standards (DataCite, STAC) ask for them. |
| `sites.<site>.store_description` | Required to create a store: one sentence about the site's data. |
| `processing.metadata.initials` | Required to migrate or amend a store: who changed its metadata. |
| `processing.storage.gnss_store_name`, `processing.storage.vod_store_name` | A store's folder is named by its kind (`gnss`, `vod`), optionally with a suffix (`vod-recompute`); other names are refused. Remove `gnss_store_name: rinex`: the GNSS store's folder is now `gnss`, and the migration moves it. Remove any other old name too, such as `vod_store_name: Site_VOD_store`, and move that store with `canvodpy store migrate SITE --rename Site_VOD_store=vod`; the settings check names the command. |
| `processing.preprocessing.temporal_aggregation.integer_method` | Required when temporal aggregation is set: `first`, `last` or `middle`. |

!!! warning "Preprocessing in your settings is now applied"

    In 0.x, `canvodpy run` didn't apply `processing.preprocessing`, and the
    settings template set `temporal_aggregation` and `grid_assignment` to
    `enabled: true`. Since v1.0.0 a run applies every preprocessing
    section that is set. A store you migrate records the preprocessing its
    data show, none for a store written by `canvodpy run` in 0.x, and runs
    with other preprocessing are refused. So if you copied the template,
    delete the `preprocessing` section. See
    [Preprocessing](../packages/ops/overview.md).

Settings that are deprecated still work and print a warning that says what
to do; they are listed [below](#deprecated-settings).

### 2. Back up your stores

The migration commits to the stores; earlier snapshots stay readable, but
keep a copy until you've checked the result. A store is a folder: copy it
(`cp -a`, `rsync -a`).

### 3. Migrate each site's stores

One command per site:

```bash
canvodpy store migrate SITE
```

It shows what it will do, asks once (`--yes` skips the question), and
then takes these steps, skipping each one that is done already:

1. **The folders.** A store's folder is named by its kind, `gnss` or
   `vod`, optionally with a suffix (`vod-recompute`,
   [Store folders](../packages/store/overview.md#store-folders)). The
   GNSS store's old folder `rinex` moves to `gnss`. Any other folder whose
   name isn't its kind needs its new name: `--rename vod_2024=vod-2024`.
   The store id is taken from the new name. A site that has both `rinex`
   and `gnss` is refused: decide which store to keep. The next steps
   migrate the stores your settings name (`gnss_store_name`,
   `vod_store_name`). Another store, such as `vod-2024`, is only moved,
   and the command says so: to migrate it, set
   `vod_store_name: vod-2024` and run the command again.
2. **The GNSS store, then the VOD store**, each with the steps of
   `migrate-metadata` and `migrate-layout` (described below).
3. **The clock.** A GNSS store written with CLK files holds a `clock`
   variable. v1.0.0 reads no CLK files by default, and VOD doesn't use
   the clock: the variable is removed and the store records
   `fetch_clock: false`. The VOD store records the GNSS store's new
   content-settings hash, so VOD runs go on.

If a step stops, fix the cause and run the command again.
`migrate-metadata` and `migrate-layout` run single steps of one store
(`--store gnss` or `--store vod`):

- **`migrate-metadata`** moves the store to repository metadata: its
  description, a store id and UUID, the time scale of its epochs, and
  its *content settings*, the settings that shape its data and that
  every later run must match
  ([Content settings](configuration.md#content-settings-fixed-for-each-store)).
  Metadata the store lacks, such as the publisher and license, comes from
  the settings file, marked `(from the settings)`. A store that is
  already migrated is left as it is.
- **`migrate-layout`** writes the groups again as day blocks, the layout
  v1.0.0 runs write ([Moving a store to day blocks](../packages/store/overview.md#moving-a-store-to-day-blocks)).
  An epoch stored twice keeps the entry written last.

Both show what they change and ask first. Each one is a single commit. The details are in
[Move an older store to the current form](../packages/store-metadata/overview.md#move-an-older-store-to-the-current-form).

**Settings the store doesn't record.** `migrate-metadata` takes the
content settings from the settings recorded in the store's first commit.
A value that commit doesn't record isn't guessed: the command stops,
lists it, and you give it with `--gnss-set` (or `--vod-set` for the VOD
store), as your settings file had it when the store was written. For a
GNSS store from canVODpy 0.4.0 these are typically:

```bash
canvodpy store migrate SITE \
  --gnss-set processing.params.store_sbf_metadata=true \
  --gnss-set processing.params.rinex_v3_parser=validated \
  --gnss-set "sites.SITE.receivers.reference_01.paired_canopies=[canopy_01]"
```

Some settings are read from the data instead, because canVODpy 0.x
recorded settings its runs didn't follow: the preprocessing (none, unless
the data show a step) and whether the stores hold `r`, `delta_snr` and
`radial_diff`. canVODpy 0.x always wrote `delta_snr` to the VOD store, so
a migrated store records `store_delta_snr: true`: set it in your settings
file too.

**Stores from SBF or NMEA files.** canVODpy 0.x stored their epochs in
UTC, 18 s behind the GPS time v1.0.0 uses for every epoch. The
migration refuses these stores before it writes anything, and so does
the VOD store computed from them: rebuild them from the raw files with
`canvodpy run`. Stores from RINEX files hold GPS time and migrate as
they are.

**Receivers with a naming recipe.** A GNSS store records each
receiver's naming recipe and the sha256 of the recipe file, and every
run compares them with the settings. Stores of canVODpy 0.x record the
recipe, if the receiver had one, without its sha256; a receiver that
used the `naming` block and now has a recipe records none. The
migration doesn't add them: it can't tell whether today's recipe file
is the one the store was built with. For each receiver with a naming
recipe, check that its recipe file is the one the store was built with,
then record it:

```bash
canvodpy store amend SITE --store gnss --update-recipe RECEIVER \
    --reason "recipe of the stored days, recorded after the migration"
```

Without this, the first run stops and prints the command. Sites whose
files have canonical canVOD names have no recipes and skip this.

### 4. Check the result

```bash
canvodpy store info SITE            # content settings: set, with their hash
canvodpy run --site SITE --start 2025001 --end 2025001
```

A run compares your settings with the store's content settings before it
reads a file, and stops if they differ, listing each setting with both
values. Change your settings to the store's values, or write a settings
file from the store with `canvodpy config init --from-store <store>`.
A dry run (`--dry-run`) lists the files a run would process, but doesn't
compare the settings.

---

## What changed

| Before (0.x) | Since v1.0.0 | What to do |
|---|---|---|
| Runs append each file to the store. | Runs write day blocks: every receiver-day has its slots, and a day processed again replaces its slots ([ADR 0016](../adr/0016-day-blocks-and-forked-writes.md)). | Migrate the stores (step 3). |
| A store had no fixed settings. | A store records its content settings when it is created; a run with other settings is refused ([ADR 0019](../adr/0019-content-settings-and-several-writers.md)). | To process with other settings, write a new store (`gnss_store_name: gnss-<suffix>`). |
| Opening a store created it. | Only a run creates a store; `open_gnss_store()` and `open_vod_store()` only open. | Create stores with `canvodpy run`. |
| A store's site came from its folder name. | It comes from the store's metadata. | Nothing; migrated stores have it. |
| The GNSS store's folder was `rinex`, and store folders could have any name. | A store's folder is named by its kind: `gnss`, `vod`, or the kind with a suffix ([Store folders](../packages/store/overview.md#store-folders)); the store id ends in it. | Migrate the stores (step 3); the migration moves `rinex` to `gnss`. |
| `canvodpy run` without dates resumed from the last stored day. | A run without dates stops. `--update-to-latest` processes the days from the earliest last stored day of the receivers with new files up to the latest day with files ([Which days a run processes](api-levels.md#which-days-a-run-processes)). | Add `--update-to-latest` to scheduled runs. |
| `processing.preprocessing` had no effect. | A run applies each section that is set. | See the warning in step 1. |
| Files were found in day folders with fixed names. | Each file's day comes from its name, in any folder layout. | Nothing; files with other names need a naming recipe ([File names](../packages/naming/overview.md)). |
| `max_memory_gb` was a memory limit a run checked while it worked. | It is the run's memory budget, applied before the work starts: it sizes the workers and the units of days a run commits at once ([Parallel processing](parallel-processing.md)). | Check its value. |
| A run computed the VOD of each day in the main process, from the day read back from the GNSS store, and committed the VOD store every day. | A run stores a unit of days, then computes their VOD in the worker processes from the GNSS store and commits the VOD store once per unit ([ADR 0021](../adr/0021-runs-work-in-units-of-days.md)). Nothing is read back for VOD. In Python, `pipeline.run()` does what `canvodpy run` does. The Airflow task `process_day` returns the groups that stored the day, no longer their number of epochs. | Use `pipeline.run()` instead of `process_range()` with `site.vod.compute_day_all()` to process and compute VOD. |
| A run processed `days_per_batch` days at a time and committed every day. | A run works in units of days and commits each unit once; it sizes the units from the memory budget, at most 31 days ([ADR 0021](../adr/0021-runs-work-in-units-of-days.md)). A day that fails still fails alone. | Remove `days_per_batch` (deprecated). |
| A store recorded the name of each receiver's naming recipe. | A GNSS store records each receiver's naming recipe and the sha256 of its file; a run stops if the settings give another recipe, or the recipe file changed ([File names](../packages/naming/overview.md)). | Record the recipes after migrating (step 3). After changing a recipe on purpose, `canvodpy store amend SITE --store gnss --update-recipe RECEIVER --reason "..."`. |
| `canvodpy[filemap]` installed canvod-filemap. | The extra is gone. | Install canvod-filemap from its tag ([Optional extensions](extensions.md)), or `uv sync --group filemap` in the repository. |
| canvod-grids installed canvod-store and canvod-store-metadata. | It doesn't. | Code that imports `canvod.store` declares canvod-store itself. |

---

## Deprecated

Deprecated code and settings still work in every v1.x release, warn when
used, and are removed in v2.0.0 ([ADR 0005](../adr/0005-deprecate-until-next-major.md)).
The rest of the documentation leaves them out.

### Ways to run

All of these are replaced by one entry point: `canvodpy run`, or
`canvodpy.Site(<site>).pipeline()` in Python
(see [the command line and Python](api-levels.md)).

| Deprecated | Use instead |
|---|---|
| `canvodpy.process_date()` | `Site(<site>).pipeline().process_date(<date>)` |
| `canvodpy.calculate_vod()`, `Pipeline.calculate_vod()` | `canvodpy run`, or `Site(<site>).vod.compute_bulk(<analysis>, start=..., end=...)` |
| `canvodpy.preview_processing()` | `Site(<site>).pipeline(dry_run=True).preview()` |
| `FluentWorkflow`, `VODWorkflow` | `Site(<site>).pipeline()` and `Site(<site>).vod` |
| `canvodpy.functional` (all functions) | `canvodpy run`; for grids `canvod.grids.create_hemigrid()` and `add_cell_ids_to_ds_fast()` |
| Airflow tasks `check_rinex`, `check_sbf` | `check_day` |
| Airflow tasks `process_rinex`, `process_sbf`, `fetch_aux_data`, `cleanup` | `process_day` |
| `DataDirMatcher`, `PairDataDirMatcher`, `DataDirectoryValidator` | `canvodpy run` finds the files; `canvodpy config validate` checks them |

### Deprecated settings

| Setting | Use instead |
|---|---|
| `sites.<site>.naming`, `sites.<site>.receivers.<name>.naming` | `recipe` on each receiver with non-canonical file names |
| `sites.<site>.receivers.<name>.scs_from` | `paired_canopies` |
| `processing.metadata.store_description` | `sites.<site>.store_description` |
| `processing.storage.vod_store_strategy` | nothing (no effect); to recompute VOD, set `vod_store_name` to another name, such as `vod-recompute` |
| `processing.logging.log_file_name` | nothing (no effect); log files have fixed names under `log_dir` |
| `processing.params.days_per_batch`, `canvodpy run --days-per-batch`, argument `days_per_batch` of `Site.pipeline()` and `Pipeline` | nothing; the run sizes its units of days from `max_memory_gb`. Until v2.0.0 the value only caps the days per unit |

### Python API

| Deprecated | Use instead |
|---|---|
| `create_gnss_store()`, `create_vod_store()` | `open_gnss_store()`, `open_vod_store()` |
| `canvod.grids.store_grid()`, `load_grid()`, `canvod.grids.analysis.AnalysisStorage` | `canvod.store.store_grid()`, `load_grid()`, `AnalysisStorage` |
| `add_cell_ids_to_vod()`, `add_cell_ids_to_vod_fast()`, argument `data_var` of `add_cell_ids_to_ds_fast()` | `add_cell_ids_to_ds_fast(ds, grid, grid_name)` |
| `store_dataset_with_cell_ids()` | `canvod.ops.assign_grid_cells_in_store()` |
| `GnssResearchSite.calculate_vod()`, `store_vod()`, `store_vod_analysis()`, `store_vod_analyses_batch()` | `Site(<site>).vod.compute_days(<days>)` (writes), `Site(<site>).vod.compute_bulk(<analysis>, write=False)` (computes only) |
| Writing VOD with `VodComputer.compute_day()` or `compute_day_all()` (`write=True`, the default), `VodComputer.write_day()` | `pipeline.run()` or `Site(<site>).vod.compute_days(<days>)`; pass `write=False` to compute without writing |
| `VODCalculator.from_icechunkstore()`; argument `align` of `from_datasets()` | `Site(<site>).vod.compute_bulk(<analysis>, write=False)`; `align` is ignored |
| `IcechunkDataReader` | `canvodpy run` or `Site(<site>).pipeline().process_date(<date>)` |
| `VodDataValidator` | `canvod.readers.validate_vod_dataset` |
| `scan_stores_as_stac`, `to_stac_collection`, `to_stac_collection_json`, `write_stac_collection`, `write_stac_catalog` | `canvod.store_metadata.build_catalog`, `store_item`, `write_catalog` (or `canvodpy run --write-catalog`) |
| `apply_updates()`, `update_metadata()` | `amend_metadata()` (`canvodpy store amend`); every commit writes the snapshot summary |
| `StoreMetadata.from_root_attrs()`, `history_entry()` | `read_metadata()`; the history is the commit log (`show_metadata`) |
| `SiteNamingConfig`, `ReceiverNamingConfig`, `FilenameMapper`, `match_pattern` | a naming recipe (`recipe` on the receiver, canvod-filemap) |
| `StorageConfig.get_rinex_store_path()` | `get_gnss_store_path()` |
| `SiteConfig.resolve_scs_from()` | `resolve_paired_canopies()` |
| `ProcessingConfig.processing`, `ProcessingConfig.compression`, `CompressionConfig` | `params`, `netcdf_compression`, `NetcdfCompressionConfig` |
| `LoggingConfig.get_log_file()`; argument `logfile` of `configure_logging()` | `get_log_dir()`; `log_dir` |
| `canvodpy.logging.get_logger`, `get_file_logger`, `canvodpy.logging.context` | `structlog.get_logger(__name__)`, `.bind(file=...)`, `structlog.contextvars.bound_contextvars` |
| `canvod.readers.gnss_specs.utils.file_hash`, `isfloat` | `canvod.utils.tools.file_hash`, `isfloat` |
| `canvodpy.orchestrator.matcher.DatasetMatcher`, `canvodpy.orchestrator.interpolator.*` | `canvod.auxiliary.matching.DatasetMatcher`, `canvod.auxiliary.interpolation.*` |
| `ProductSpec.sampling_rate`, `ProductSpec.duration`, `AuxFile.generate_filename_based_on_type()` | `ProductSpec.sp3_samplings` (every product file covers one day), `AuxFile.candidate_filenames` |

??? note "Internal helpers, rarely used directly"

    | Deprecated | Use instead |
    |---|---|
    | `AugmentationFactory`, `AugmentationContext`, `AugmentationStep` | a `canvod.ops.Op` in a `canvod.ops.Pipeline` |
    | `SphericalCoordinateAugmentation`, `AuxDataAugmenter`, the `example_*` functions of `canvod.auxiliary.augmentation` | `canvod.auxiliary.position.add_spherical_coords_to_dataset` |
    | `ClockCorrectionAugmentation` | nothing: it left the data unchanged |
    | `worker_task()`, `worker_task_append_only()` | `preprocess_with_hermite_aux()` |
    | `DistributedRinexDataProcessor`, `SingleReceiverProcessor`, `parsed_rinex_data_gen_2_receivers()`, `parsed_rinex_data_gen_parallel()` | `Site(<site>).pipeline()` |
    | `VodComputer.check_preprocessing` | `check_gnss_hash` |
    | `Rnxv3Obs.parse_observation_slice` | `Rnxv3Obs.iter_epochs()`, `to_ds()` |
    | `canvod.readers.rinex.v2_11._register_factory()` | nothing: it never registered anything |

---

## New in v1.0.0

- **Stores on S3**: runs write GNSS and VOD stores to S3-compatible object
  storage ([Stores on S3](../packages/store-metadata/overview.md#stores-on-s3)).
- **Store metadata** after DataCite and ACDD, checked against the
  standards, and a **STAC catalog** of all stores
  (`canvodpy run --write-catalog`; [Store metadata](../packages/store-metadata/overview.md)).
- **Join or reproduce a store**: `canvodpy config init --from-store`
  writes the settings file of a store ([Settings file](configuration.md#join-or-reproduce-a-store)).
- **Run history and dashboard**: every run records itself, its stage
  timings and resource use ([Diagnostics and monitoring](diagnostics.md)).
- **Data check**: `canvodpy config validate` checks the receiver data the
  way a run finds it, and runs warn about files they don't process and
  about incomplete receiver-days.
- **Memory budget and units of days**: `max_memory_gb` sizes the workers
  and the units of days a run commits at once, and a run reads the next
  unit while it computes VOD
  ([Parallel processing](parallel-processing.md)).
- **Plugins**: your own readers and VOD calculators from installed
  packages ([Your own readers and VOD calculators](plugins.md)).
- **Comparing stores** within fixed tolerances, and `canvodpy config explain`.
- **Stores that don't record the computer**:
  `processing.metadata.record_machine: false` leaves the operating
  system, architecture, CPU count, memory and free disk out of every
  commit, for stores that are published
  ([Settings](settings.md#processing-metadata-record_machine)). It is
  true by default, so nothing changes for you.
- **Demo data**: `canvodpy.demo_data()` downloads the demo day; the
  [notebooks](https://canvodpy.eu/notebooks/) use it.

The full list is in the [changelog](https://github.com/nfb2021/canvodpy/blob/main/CHANGELOG.md).
