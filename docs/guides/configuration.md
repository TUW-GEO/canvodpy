# Configuration guide

canVODpy reads its settings from one file, `canvod-settings.yaml`. The
file holds what canVODpy cannot know on its own:

- **Where your data is.** Paths differ on every machine.
- **Who you are.** Your name, institution, and ORCID go into the
  metadata of each store.
- **How much of the machine to use.** By default, canVODpy sizes the
  workers to the machine; you can set limits.

Everything else, such as the signals to keep or the chunk sizes, has a
default that you can change.

canVODpy checks the file with
[`pydantic-settings`](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)
when it loads it. A misspelled field name, or text where a number
belongs, stops the load with the location of the error.

---

## Configuration commands

```bash
canvodpy config init        # create canvod-settings.yaml from the template
canvodpy config edit        # open canvod-settings.yaml in $EDITOR
canvodpy config validate    # check the settings and the receiver data of all sites
canvodpy config show        # print the settings canVODpy uses
canvodpy config explain processing.storage.stores_root_dir  # what a setting means
canvodpy doctor             # show which settings file canVODpy found
```

Every setting is described in the [Settings reference](settings.md), and
the template links each setting to its entry there.
`canvodpy config explain` prints the same entry in the terminal; it takes
the setting's path, or its end (`gnss_store.epoch`), and names a site or
receiver as in your file (`sites.my_site.receivers.reference_01.directory`).
In `canvodpy config init --interactive`, answer `?` to a question to see
the entry of the setting it asks for.

`canvodpy config show` prints the settings after the
[overlay file](#overlay-file) is applied, so a value set there appears
instead of the value in `canvod-settings.yaml`.

---

## Overlay file

To change settings for one machine, such as the store path on a cluster,
use an overlay file instead of editing `canvod-settings.yaml`.

Pass `--config` to any command that accepts it:

```bash
# Validate or inspect with an overlay applied
canvodpy config validate --config cluster-overlay.yaml
canvodpy config --config cluster-overlay.yaml show

# Run the pipeline with an overlay
uv run canvodpy run --site mysite --start 2025001 --end 2025028 \
    --config cluster-overlay.yaml
```

`canvodpy config` also takes `--config` before its command, for every
command: `canvodpy config --config cluster-overlay.yaml validate` works
too.

Only the fields present in the overlay are changed; everything else is read from the main file.
A list in the overlay, such as `sids.custom_sids`, replaces the list of the main file as a
whole; its entries are not added to the main file's.

### An overlay can add and change settings, not remove them

The overlay is merged **on top of** the base `canvod-settings.yaml`; it can add new keys or
override existing ones, but it cannot remove a key that exists in the base file. If your base
file defines a site (or any other field) that isn't mentioned in the overlay, that entry stays
in the settings canVODpy uses, no matter what the overlay contains.

!!! warning "Rename the template site"

    The template from `canvodpy config init` contains a site `my_site`
    under `sites:`. Rename it to your site. If you add your site next to
    it, `my_site` stays, with paths such as
    `/path/to/your/gnss/data/my_site`, and `canvodpy config validate` and
    `canvodpy run` fail on it. An overlay can't remove it; remove it from
    `canvod-settings.yaml`. To start over, run
    `canvodpy config init --force`, which overwrites the file.

---

## Where canVODpy finds the settings

canVODpy looks for `canvod-settings.yaml` in the first of these folders
that exists:

1. `$CANVOD_CONFIG_DIR`, or the folder passed with `--config-dir`
2. `config/` of a canVODpy clone
3. `~/.config/canvodpy`

The same folder holds the naming recipes, in `recipes/`.
`CANVOD_CONFIG_FILE` names an overlay file, like `--config`.

### Settings from a GitHub repository

`--config-dir` and `CANVOD_CONFIG_DIR` also take the raw link of a
settings file in a GitHub repository, at a commit, a tag or a branch:

```bash
canvodpy run --site ExampleSite --start 2025001 --end 2025007 \
  -c https://raw.githubusercontent.com/<account>/<repo>/refs/tags/<tag>/config/canvod-settings.yaml
```

- A receiver's `recipe:` name is read from the same repository at the
  same commit, tag or branch, from `recipes/<site>/<name>.yaml` next to
  the settings file, as in a local folder. A `recipe:` that is a URL is
  read from that URL.
- Every run downloads the files again, into a folder of the run that
  only you can read. A run is a `canvodpy` command, a new `Site` in
  Python (also the second one in the same notebook) or an Airflow task.
  The folders are removed when the process ends: the command, the
  notebook kernel or the Airflow worker. A run needs network access.
- Each Airflow task is a run of its own, so the tasks of one DAG run read
  the link again; they read other settings if the branch moved in
  between.
- `canvodpy doctor` names the link and the sha256 of the settings file.
- The link is not recorded. Stores keep the settings, the run history
  keeps the settings of each run, and both name a recipe URL by its file
  name only.
- A private repository needs a GitHub token in `GH_TOKEN` or
  `GITHUB_TOKEN`, for example `export GH_TOKEN=$(gh auth token)`.
- The folders of your machine (stores, auxiliary files, logs) go into an
  overlay file with `--config`, so one settings file serves every machine.
- `canvodpy config init` and `canvodpy config edit` write the settings
  file, so they need a local folder; change settings from a link in their
  repository.

Settings come from these sources, the first one wins:
overlay file, `canvod-settings.yaml`, package default. Write only the fields you want to change.

canVODpy rejects unknown field names. The error names the closest
allowed field and lists all allowed fields; canVODpy never corrects a
name by itself:

```text
processing.icechunk.chunk_strategies.vod_stores
  Unknown key 'vod_stores'. Did you mean 'vod_store'? Allowed keys: gnss_store, vod_store
```

---

## Minimal working example

A `canvod-settings.yaml` that can create stores needs only these fields;
the rest have defaults:

```yaml
processing:
  metadata:
    author: Jane Scientist
    email: jane.scientist@example.edu
    institution: Example University
    naming_authority: edu.example
    publisher: Example University
    license: CC-BY-4.0

  storage:
    stores_root_dir: /data/stores

  logging:
    log_dir: /data/logs

sites:
  mysite:
    gnss_site_data_root: /data/mysite
    store_description: GNSS-T observations below a beech canopy

    receivers:
      reference_01:
        type: reference
        directory: 01_reference
        paired_canopies: all
      canopy_01:
        type: canopy
        directory: 02_canopy

    vod_analyses:
      canopy_01_vs_reference_01:
        canopy_receiver: canopy_01
        reference_receiver: reference_01
```

---

## Content settings: fixed for each store

Some settings shape the data a store holds: which signals are kept, how
the files are read, the orbit product, the preprocessing, the chunk
sizes and the compression. These are the store's **content settings**.
The run that creates a store records them in it, and every later run that
writes to the store must have the same ones, also a run on another
computer. Data written with other content settings would sit next to the
old data in one store without anything showing the difference.

A run compares its settings with the store's twice: when it starts,
before it reads a file, and again just before each commit, because
another run may have created the store or written to it meanwhile. On a
difference the run stops and lists each setting with the store's value
and its own. You then have two options:

- use the store's settings: `canvodpy config init --from-store <store>`
  writes a settings file from them, or
- write to a new store: set `processing.storage.gnss_store_name` to the
  kind plus a suffix (for example `gnss-recompute`, see
  [Store folders](../packages/store/overview.md#store-folders)), or set
  another `stores_root_dir`.

There is no option to write anyway. A store's content settings never
change; to process with other settings, create a new store.

| Content setting | Where |
| --------------- | ----- |
| The signals kept | `sids.mode`, `sids.preset`, `sids.custom_sids`, and the list of signals they give |
| Observables and how they are stored | `processing.params.keep_gnss_observables`, `aggregate_glonass_fdma`, `store_radial_distance`, `store_delta_snr`, `store_radial_diff`, `store_sbf_raw_observables`, `store_sbf_metadata` |
| How files are read and paired | `processing.params.rinex_v3_parser`, `file_pairing`, `receiver_position_mode`, `ephemeris_source` |
| The orbit product | `processing.aux_data.agency`, `product_type`, `fetch_clock` |
| Preprocessing | all of `processing.preprocessing`, statistics included |
| Store layout | `processing.icechunk.compression_algorithm`, `compression_level`, `inline_chunk_threshold_bytes`, `manifest_splitting_enabled`, `manifest_splitting_epoch_range`, `chunk_strategies.gnss_store` |
| Maintenance | all of `processing.storage.maintenance` |
| Each receiver | `type`, `reader_format`, `paired_canopies` |

A VOD store keeps its own content settings too. It has no SIDs, receivers
or site entries of its own; it records the settings that shape the VOD
output and the content-settings hash of the GNSS store it was computed
from (`gnss_content_hash`), so a run that computes VOD from a GNSS store
with other content settings stops.

| VOD content setting | Where |
| ------------------- | ----- |
| The VOD output options | `processing.params.store_delta_snr`, `store_radial_diff` |
| Store layout | `processing.icechunk.compression_algorithm`, `compression_level`, `inline_chunk_threshold_bytes`, `manifest_splitting_enabled`, `manifest_splitting_epoch_range`, `chunk_strategies.vod_store` |
| Maintenance | all of `processing.storage.maintenance` |
| Where the VOD came from | `gnss_content_hash` (the GNSS store's content-settings hash) |

The calculator and its parameters are recorded per VOD group
(`{calculator}/{analysis}`) when the group is first written, and every
later write compares them: a group never holds results computed with
other calculator parameters. On a difference the run stops and names each
parameter with both values; use a new analysis name
(`canvodpy store amend --add-vod-analysis`) or a new VOD store.

Every other setting may differ from run to run: the resources
(`resource_mode`, `n_max_threads`, memory), the
Icechunk cache and concurrency settings, `aux_data.ftp_timeout_s`,
logging, folders, credentials, the store strategies, `keeper_tags`,
`netcdf_compression`, and a receiver's `directory`, `naming` and
`recipe`. The metadata (`processing.metadata`, `processing.references`,
descriptions, receiver hardware and antenna) is written into the store
when it's created and changes only with `canvodpy store amend`.

`canvodpy store info <site>` shows when and by whom a store's content
settings were set, and their hash. In Python,
`show_metadata(store_path, section="content")` from
`canvod.store_metadata` lists them in full.
A receiver added to a store with `canvodpy store amend --add-receiver`
brings its own three content settings from the settings file.

A store created before canVODpy kept content settings is refused by
runs until it has them. `canvodpy store migrate-metadata <site>` takes
them from the settings recorded in the store's first commit. A setting
that commit doesn't record, such as the `paired_canopies` of a reference
receiver, isn't guessed: the command stops, lists it, and you give the
value the data was written with, for example
`--set sites.mysite.receivers.reference_01.paired_canopies=[canopy_01]`.
A setting the data show, such as `processing.preprocessing` or
`store_delta_snr`, is read from the data, since canVODpy 0.x recorded
settings its runs didn't follow
([Move an older store](../packages/store-metadata/overview.md#move-an-older-store-to-the-current-form)).

ADR 0019 records why ([Decisions](../adr/index.md)).

---

## Join or reproduce a store

A store's content settings are what a second machine must match to write
into that store. `canvodpy config init --from-store <store>` writes a
settings file from them, which is how a fresh worker joins a store, and
how anyone reproduces the processing of a store they can open (a published
one, or a copy):

```bash
canvodpy config init --from-store /data/stores/fangorn/gnss
canvodpy config init --from-store s3://my-bucket/fangorn/gnss
```

`<store>` is the store's directory, or its `s3://bucket/prefix` URL. The
written file keeps:

- the store's content settings, unchanged. They must stay as they are:
  other settings mean a different store (see
  [Content settings](#content-settings-fixed-for-each-store));
- the site and its receivers as the store describes them (the site name,
  description, coordinates, the store's description, and each receiver's
  description, recipe and recorded data directory as the default);
- `processing.storage.stores_root_dir` and `gnss_store_name`, taken from
  the store argument: `<root>/<site>/<name>`;

and writes `TODO` for the values the run owner fills in: the folders of
their computer, which stores never record (`gnss_site_data_root`,
`aux_data_dir`, `shared_aux_cache_dir`, `log_dir`), each receiver's
`directory`, and `processing.metadata.author`, `email` and
`institution`. Interactive (the default) asks for each and
offers the store's recorded receiver directory as the default;
`--no-interactive` keeps the `TODO` values.

Credentials are never written. At the end the command prints the
environment variables to set instead: the NASA Earthdata one for CDDIS,
and the `AWS_*` ones for a store on S3. An existing settings file is not
overwritten, also with `--force`.

`canvodpy config validate` lists every `TODO` value with its dotted key
and exits with code 1, so a settings file written this way is easy to
finish. A store without content settings (created before canVODpy kept
them) is refused, naming `canvodpy store migrate-metadata`.

---

## `processing:`

Metadata, resources, storage, and ephemeris products.

```yaml
processing:
  metadata:
    author: Your Name
    email: your.email@example.com
    institution: Your Institution
    naming_authority: org.example  # your domain in reverse; required to create a store
    publisher: Example University  # required to create a store
    license: CC-BY-4.0  # SPDX identifier, or "other"; required to create a store
    initials: JD  # who set a new store's content settings or changed its metadata; required to amend or migrate
    # optional: orcid, institution_ror, department, research_group,
    # website, publisher_url, license_uri (required when license is "other")

  credentials:
    nasa_earthdata_acc_mail: null

  aux_data:
    agency: COD          # SP3/CLK analysis center code
    product_type: final  # final or rapid; the agency must publish it
    # fetch_clock: false # true adds the CLK files; VOD does not use them

  params:
    keep_gnss_observables: [SNR]   # observables to keep (SNR, Pseudorange, Phase, Doppler)
    rinex_v3_parser: validated     # 'unvalidated_fast' is DANGEROUS: no checks, your responsibility
    store_radial_distance: false   # store satellite distance (r)
    receiver_position_mode: shared # or per_receiver
    file_pairing: complete         # or paired
    ephemeris_source: precise      # or broadcast (SBF, or RINEX with nav_directory)

    # --- Resource management ---
    resource_mode: auto            # auto or manual
    # n_max_threads: 4             # required if manual
    # cpu_affinity: [0, 1, 2, 3]  # CPU cores (manual only; not on macOS)
    # nice_priority: 10            # manual only; 0=normal, 19=lowest priority

  # Optional; nothing is applied unless set (see Preprocessing)
  # preprocessing:
  #   temporal_aggregation:
  #     freq: "1min"               # divides one day
  #     method: median             # mean or median (floating-point variables)
  #     integer_method: first      # first, last or middle (integer flags)
  #   grid_assignment:
  #     grid_type: equal_area
  #     angular_resolution: 2.0    # degrees

  netcdf_compression:              # NetCDF files written by the RINEX readers
    zlib: true
    complevel: 5

  icechunk:
    compression_level: 3
    compression_algorithm: zstd
    inline_chunk_threshold_bytes: 512
    chunk_strategies:
      gnss_store:
        epoch: 180    # epochs per file (15 min at 5 s sampling)
        sid: -1
      vod_store:
        epoch: 180    # as gnss_store
        sid: -1

  storage:
    stores_root_dir: /path/to/stores
    gnss_store_strategy: skip         # skip, overwrite, or unsafe_append; see the warning below

  logging:
    log_dir: /path/to/logs            # required for a run
```

### Key fields

| Field                           | Values                   | Description                                                                                                                                                                              |
| ------------------------------- | ------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `params.keep_gnss_observables`  | list                     | GNSS observables to retain (default `[SNR]`). With the `validated` parser, only the fields of these observables are read and checked, so a malformed field of a left-out observable doesn't drop its epoch. |
| `params.rinex_v3_parser`        | `validated`, `unvalidated_fast` | How RINEX v3 files are parsed. `validated` (default) checks every epoch and drops (and logs) epochs that fail. `unvalidated_fast` is **dangerous**: no checks, corrupted records can enter the store, and the results are entirely your responsibility; every use emits an `UnvalidatedParserWarning`. Both give the identical dataset for a valid file. |
| `params.receiver_position_mode` | `shared`, `per_receiver` | `shared` uses canopy receiver position for all receivers (enables 1:1 SNR comparison). `per_receiver` uses each receiver's own position.                                                 |
| `params.file_pairing`           | `complete`, `paired`     | `complete` ingests all files per receiver independently. `paired` only processes dates where both receivers have data.                                                                   |
| `params.ephemeris_source`       | `precise`, `broadcast`   | `precise` computes satellite positions from the SP3/CLK products of an analysis center (`final` is the old name of `precise`; it works until v2.0.0 and warns). `broadcast` uses the broadcast ephemeris the receiver recorded: the SatVisibility angles of SBF files (almanac-based angles are not used), or for RINEX files the receiver's navigation files (`nav_directory`); no SP3/CLK download ([Ephemeris sources](../packages/readers/ephemeris-sources.md)). |
| `aux_data.fetch_clock`          | `true`, `false`          | Whether to download and interpolate CLK clock-correction files alongside SP3 (only applies to `ephemeris_source: precise`). Default `false`: VOD does not use clock data. `true` adds each satellite's clock correction to the GNSS store as the variable `clock`. |
| `params.days_per_batch`         | 1–30                     | Deprecated, removed in v2.0.0; prints a `FutureWarning`. Only caps the days per unit, which the run sizes from the memory budget ([Parallel processing](parallel-processing.md)). Leave it out. |
| `params.resource_mode`          | `auto`, `manual`         | `auto` starts one worker per physical CPU core and leaves at least two CPU threads free for the operating system. `manual` uses the limits you set (`n_max_threads` is then required); use it on shared servers.      |
| `params.store_radial_distance`  | `true`, `false`          | Whether to store satellite radial distance in the output.                                                                                                                                |
| `params.store_sbf_raw_observables` | `true`, `false`       | SBF only: add the pre-correction observables (`SNR_raw`, `Pseudorange_unsmoothed`, `Pseudorange_raw`, `Phase_raw`) to the observations. Default `true`. |
| `params.store_sbf_metadata`     | `true`, `false`          | SBF only: store the per-file metadata dataset `sbf_obs` (SatVisibility geometry, MeasExtra, PVT, DOP, receiver status) under `{group}/metadata/sbf_obs`, in the same commit as the observations. Default `true`. |
| `storage.stores_root_dir`       | folder or S3 URL         | Where the stores are, one folder per site: a local folder, or `s3://bucket/prefix` to write the stores on S3, experimental ([Stores on S3](s3.md)). Credentials, region and endpoint of S3 come only from the environment. Other URLs are refused. |
| `storage.gnss_store_strategy`   | `skip`, `overwrite`, `unsafe_append` | What to do when a file already exists in the store. `skip` (default) is the normal case. See warning below before ever using `unsafe_append`.                              |
| `logging.log_dir`               | folder                   | Folder of the log files. Required: a run stops if it is not set. [Diagnostics](diagnostics.md) describes the files. |

[Parallel processing](parallel-processing.md) explains `resource_mode`,
`n_max_threads`, `max_memory_gb` and the other resource settings.

!!! warning "`gnss_store_strategy: unsafe_append` writes duplicate epochs"

    `skip`, the default, leaves a file that is already in the store
    alone, so a second run over the same files changes no data; the
    log book gets a row per file it saw, with `action` set to `skipped`. A run
    finds the days whose files are all stored by the files' hashes,
    before it downloads auxiliary data or reads a file, writes their
    rows in one commit and passes the days on to the VOD phase, which
    computes only VOD that is missing.
    `overwrite` deletes the stored epochs of the file's time span and
    writes the file again. Use it after a fix in canVODpy, such as in a
    reader, to recompute stored data. The VOD of those days stays as it
    was: the rewritten files are the same files, so their VOD results
    are skipped. For VOD of the recomputed data, write it to a new VOD
    store (set `storage.vod_store_name` to another name, such as `vod-recompute`).

    `unsafe_append` writes the file again on top of the stored data,
    without checking for epochs that are already there. The store then
    holds each of these epochs twice, and the extra chunks stay in the
    store. The pipeline and `Site.vod.compute_bulk(..., write=False)` remove the duplicates when they
    read; `MyIcechunkStore.read_group()` does not. On duplicated epochs,
    `.sel()` can fail or return several matches, and aligning canopy and
    reference data multiplies the rows. Don't use `unsafe_append` unless
    you need it.

### Ephemeris data sources

canVODpy downloads SP3 and CLK products from **ESA GSSC**, which needs
no account. If you set `credentials.nasa_earthdata_acc_mail` to the email
address of a (free) NASA Earthdata account, canVODpy downloads from
**NASA CDDIS** first and falls back to ESA GSSC when that download fails.

`aux_data.agency` and `aux_data.product_type` must name a product of the
[product registry](../packages/auxiliary/products.md), which also lists the
GNSS each product covers; a run and `canvodpy config validate` stop on any
other combination and name the closest products. Ultra-rapid products are
not supported.

---

## `sites:`

Your sites, their receivers, and the receiver pairs to compute VOD for.
Each key under `sites:` is the name of a site.

```yaml
sites:
  my_site:
    gnss_site_data_root: /data/my_site
    description: null        # optional free-text description
    country: null            # ISO 3166-1 alpha-2, e.g. AT
    latitude: null           # WGS84 decimal degrees
    longitude: null
    altitude_m: null         # meters above WGS84 ellipsoid

    receivers:
      reference_01:
        type: reference
        directory: 01_reference
        reader_format: auto           # auto, rinex3, rinex3_stripped, rinex2, sbf, nmea, or a reader plugin
        paired_canopies: all          # 'all' or list of canopy receiver names
      canopy_01:
        type: canopy
        directory: 02_canopy
        reader_format: auto

    vod_analyses:
      canopy_01_vs_reference_01:
        canopy_receiver: canopy_01
        reference_receiver: reference_01
```

### Receiver fields

| Field             | Default | Description                                                                                                                                                                                                                                        |
| ----------------- | ------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `type`            | --      | `reference` or `canopy`.                                                                                                                                                                                                                           |
| `directory`       | --      | Subdirectory under `gnss_site_data_root` holding this receiver's files.                                                                                                                                                                            |
| `reader_format`   | `auto`  | Reader for the receiver's files: `rinex3`, `rinex3_stripped` (signal strengths only, faster), `rinex2`, `sbf`, `nmea`, or the name of an installed reader plugin ([Your Own Readers and VOD Calculators](plugins.md)). `auto` detects it per day, never choosing a plugin: SBF and NMEA by file type, and the RINEX version from the header. A day whose files need different readers stops the run with an error; then set the reader, or keep each format in its own directory. A canopy receiver and its reference must record the same file format (`rinex3` and `rinex3_stripped` both read RINEX 3); mixed formats are rejected when the settings load, or, with `auto`, by `canvodpy config validate` and at the start of a run. |
| `paired_canopies` | --      | Which canopy receivers this reference is paired with: `all` or a list of canopy receiver names. Required for reference receivers, must not be set for canopy receivers. |
| `receiver_hardware` | --    | Optional: `manufacturer`, `model`, `serial_number` and `firmware` of the receiver. Copied into the GNSS store's metadata when the store is created or the receiver is added to it. |
| `antenna`         | --      | Optional: `manufacturer`, `model` and `radome` (IGS names), `serial_number`, `height_m` (meters), `choke_ring` (`true` or `false`) and `polarization` (`RHCP`, the standard, `LHCP` or `dual-pol`) of the antenna. Copied into the GNSS store's metadata like `receiver_hardware`. |

Leave out the receiver and antenna details you don't want to disclose; every
field in them is optional.

---

## `sids:`

The signals (signal IDs, SIDs) to keep. There are three modes:

| Mode     | Behavior                                           |
| -------- | -------------------------------------------------- |
| `all`    | Keep every SID in the file                         |
| `preset` | Use a named built-in list (see below)              |
| `custom` | Keep only the SIDs you list explicitly             |

=== "Default preset"

    canVODpy has one preset, `default`: 271 SIDs of MEO satellites of GPS,
    Galileo, BeiDou, and GLONASS. It leaves out:

    - GEO satellites, which stand still in the sky, and IGSO satellites,
      which cover only a narrow track;
    - SBAS, IRNSS, and QZSS;
    - GPS L2W: semi-codeless tracking gives a less precise SNR and higher,
      more variable VOD (Bader et al., 2026, *Remote Sensing of
      Environment* 345, 115580).

    The list names PRNs, and PRNs are reassigned to other satellites over
    time. BeiDou C13 and C16 are left out: both were IGSO satellites until
    2026-04-18 (IGS satellite metadata), and C13 is a MEO satellite from
    2026-04-19 on. For data from 2026-04-19 on, add the C13 SIDs with
    `mode: custom` if you want them. `SatelliteCatalog` shows which satellite
    held a PRN on a given day ([Satellite Catalog](../packages/readers/satellite-catalog.md)).
    All are RINEX 3 signals. RINEX 2 band-only SIDs (e.g. `L1|u`) are not
    included and must be selected explicitly, see
    [RINEX v2.11 Parsing](../packages/readers/rinex-v2-format.md#default-sid-preset).

    ```yaml
    sids:
      mode: preset
      preset: default
    ```

    This is the default. To keep every SID, use `mode: all`.

=== "All signals"

    ```yaml
    sids:
      mode: all
    ```

=== "Custom list"

    ```yaml
    sids:
      mode: custom
      custom_sids:
        - "G01|L1|C"
        - "E01|E1|C"
    ```

---

## Check the settings and the data

`canvodpy config validate` checks the settings file (types, required
values, unknown fields), then finds the files of each receiver exactly
as `canvodpy run` does. It reports the days and files a run would
process, the files it would skip, and the problems that would stop it,
for example two files that cover the same time. A first run, and
`config validate`, refuse to start when a setting the new store needs is
missing (its description, publisher, license or naming authority). To
check one site:

```bash
canvodpy config validate --site <site>
```

---

## Optional: non-canonical filenames

A run processes only files that follow the
[file naming convention](../packages/naming/overview.md). For a receiver
whose files have other names, set a naming recipe:

```yaml
sites:
  my_site:
    receivers:
      reference_01:
        recipe: my_site_reference
```

The recipe is read from `<config dir>/recipes/<site>/<recipe>.yaml` and gives
each file a canonical name without renaming it on disk. Naming recipes need an
optional extension; see [Optional extensions](extensions.md). Where you can,
rename the files to the convention instead.

A recipe can also be read from a raw GitHub link, so that every machine
uses the same recipe from one repository; see
[Files that don't follow the convention](../packages/naming/overview.md#files-that-dont-follow-the-convention).
