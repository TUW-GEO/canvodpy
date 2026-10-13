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
canvodpy doctor             # show which settings file canVODpy found
```

`canvodpy config show` prints the settings after the
[overlay file](#overlay-file) is applied, so a value set there appears
instead of the value in `canvod-settings.yaml`.

---

## Overlay file

To change settings for one machine, such as the store path on a cluster,
use an overlay file instead of editing `canvod-settings.yaml`.

Pass `--config` to any command that accepts it:

```bash
# Inspect or validate with an overlay applied
canvodpy config --config cluster-overlay.yaml validate
canvodpy config --config cluster-overlay.yaml show

# Run the pipeline with an overlay
uv run canvodpy run --site mysite --start 2025001 --end 2025028 \
    --config cluster-overlay.yaml
```

Only the fields present in the overlay are changed; everything else is read from the main file.

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
    initials: JD  # recorded with each change of store metadata; required to amend or migrate
    # optional: orcid, institution_ror, department, research_group,
    # website, publisher_url, license_uri (required when license is "other")

  credentials:
    nasa_earthdata_acc_mail: null

  aux_data:
    agency: COD          # SP3/CLK analysis center code
    product_type: final  # final or rapid; the agency must publish it
    # fetch_clock: true  # false skips the CLK files; VOD does not use them

  params:
    keep_gnss_observables: [SNR]   # observables to keep (SNR, Pseudorange, Phase, Doppler)
    rinex_v3_parser: validated     # 'unvalidated_fast' is DANGEROUS: no checks, your responsibility
    store_radial_distance: false   # store satellite distance (r)
    receiver_position_mode: shared # or per_receiver
    file_pairing: complete         # or paired
    ephemeris_source: final        # or broadcast (SBF only)
    days_per_batch: 1              # calendar days per processing wave (1–30)

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
        epoch: 17280  # epochs per day (5 s sampling)
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
| `params.ephemeris_source`       | `final`, `broadcast`     | `final` computes satellite positions from agency SP3/CLK products. `broadcast` uses the satellite angles the receiver computed from the broadcast ephemeris (SBF SatVisibility blocks; almanac-based angles are not used; SBF only, no SP3/CLK download, faster but less accurate). |
| `aux_data.fetch_clock`          | `true`, `false`          | Whether to download and interpolate CLK clock-correction files alongside SP3 (only applies to `ephemeris_source: final`). Default `true`. VOD does not use clock data; `false` saves the download, reading, and interpolation. |
| `params.days_per_batch`         | 1–30                     | Calendar days pooled per parallel processing wave.                                                                                                                                       |
| `params.resource_mode`          | `auto`, `manual`         | `auto` detects available CPU cores and leaves two free for the operating system. `manual` uses the limits you set (`n_max_threads` is then required); use it on shared servers.      |
| `params.store_radial_distance`  | `true`, `false`          | Whether to store satellite radial distance in the output.                                                                                                                                |
| `params.store_sbf_raw_observables` | `true`, `false`       | SBF only: add the pre-correction observables (`SNR_raw`, `Pseudorange_unsmoothed`, `Pseudorange_raw`, `Phase_raw`) to the observations. Default `true`. |
| `params.store_sbf_metadata`     | `true`, `false`          | SBF only: store the per-file metadata dataset `sbf_obs` (SatVisibility geometry, MeasExtra, PVT, DOP, receiver status) under `{group}/metadata/sbf_obs`, in the same commit as the observations. Default `true`. |
| `storage.stores_root_dir`       | folder                   | Local folder that holds the stores, one folder per site. A URL such as `s3://bucket/prefix` is refused: processing writes stores to local folders only. |
| `storage.gnss_store_strategy`   | `skip`, `overwrite`, `unsafe_append` | What to do when a file already exists in the store. `skip` (default) is the normal case. See warning below before ever using `unsafe_append`.                              |
| `logging.log_dir`               | folder                   | Folder of the log files. Required: a run stops if it is not set. [Diagnostics](diagnostics.md) describes the files. |

[Parallel processing](parallel-processing.md) explains `resource_mode`,
`days_per_batch`, `n_max_threads` and the other resource settings.

!!! warning "`gnss_store_strategy: unsafe_append` writes duplicate epochs"

    `skip`, the default, leaves a file that is already in the store
    alone, so a second run over the same files changes nothing.
    `overwrite` deletes the stored epochs of the file's time span and
    writes the file again. Use it after a fix in canVODpy, such as in a
    reader, to recompute stored data.

    `unsafe_append` writes the file again on top of the stored data,
    without checking for epochs that are already there. The store then
    holds each of these epochs twice, and the extra chunks stay in the
    store. The pipeline and `Site.vod.compute_bulk()` remove the duplicates when they
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
for example two files that cover the same time. To check one site:

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
