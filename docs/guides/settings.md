---
title: Settings reference
description: Every setting of canvod-settings.yaml, with its description, type and default.
---

<!-- Written by scripts/settings_docs.py from the descriptions on the
     settings models. Don't edit this page: change the descriptions in
     packages/canvod-config and run `just settings-docs`. -->

# Settings reference

Every setting of `canvod-settings.yaml`, in the order of the file. For how
the file is found and checked, see the [Configuration guide](configuration.md).

A name in angle brackets is a name you choose: `sites.<site>` is a site,
`<receiver>` a receiver and `<analysis>` a VOD analysis. `[]` marks a list:
each item has the settings listed under it. To print a setting's entry in
the terminal, run `canvodpy config explain SETTING`, for example
`canvodpy config explain gnss_store.epoch`.

## `processing` {#processing}

How canVODpy processes the data, and where the results go

### `processing.metadata` {#processing-metadata}

Who made the stores, and under which license

#### `processing.metadata.author` {#processing-metadata-author}

Your full name, written into the metadata of the stores you create (for example `Jane Forester`)

- Type: text
- Default: none, you have to set it

#### `processing.metadata.email` {#processing-metadata-email}

Your contact email, written into the metadata of the stores you create (for example `jane@boku.ac.at`)

- Type: email address
- Default: none, you have to set it

#### `processing.metadata.orcid` {#processing-metadata-orcid}

ORCID identifier

- Type: text, or null
- Default: `null`

#### `processing.metadata.institution` {#processing-metadata-institution}

Your institution or organization name (for example `University of Natural Resources and Life Sciences Vienna`)

- Type: text
- Default: none, you have to set it

#### `processing.metadata.institution_ror` {#processing-metadata-institution_ror}

ROR identifier

- Type: text, or null
- Default: `null`

#### `processing.metadata.department` {#processing-metadata-department}

Department name

- Type: text, or null
- Default: `null`

#### `processing.metadata.research_group` {#processing-metadata-research_group}

Research group name

- Type: text, or null
- Default: `null`

#### `processing.metadata.website` {#processing-metadata-website}

Institution/group website

- Type: text, or null
- Default: `null`

#### `processing.metadata.license` {#processing-metadata-license}

SPDX license identifier (for example `CC-BY-4.0`), or `other` for a license outside SPDX (then `license_uri` is required). Required when a store is created.

- Type: text, or null
- Default: `null`

#### `processing.metadata.license_uri` {#processing-metadata-license_uri}

URI of the license text; required when license is `other`

- Type: text, or null
- Default: `null`

#### `processing.metadata.publisher` {#processing-metadata-publisher}

Publisher name. Required when a store is created.

- Type: text, or null
- Default: `null`

#### `processing.metadata.publisher_url` {#processing-metadata-publisher_url}

Publisher URL

- Type: text, or null
- Default: `null`

#### `processing.metadata.naming_authority` {#processing-metadata-naming_authority}

Your institution's domain in reverse order, lowercase (for example `at.ac.tuwien`). Required when a store is created: with the store id it gives the store's id in the STAC catalog.

- Type: text, or null
- Default: `null`

#### `processing.metadata.store_description` {#processing-metadata-store_description}

Deprecated: one description for the stores of every site. Use `sites.<name>.store_description` instead.

- Type: text, or null
- Default: `null`

#### `processing.metadata.initials` {#processing-metadata-initials}

How a store's metadata records who set its content settings or changed it (for example `NFB`); the author when not set. Required to amend or migrate a store's metadata.

- Type: text, or null
- Default: `null`

### `processing.credentials` {#processing-credentials}

Credentials for external data services

#### `processing.credentials.nasa_earthdata_acc_mail` {#processing-credentials-nasa_earthdata_acc_mail}

NASA Earthdata email for CDDIS authentication (optional)

- Type: email address, or null
- Default: `null`

### `processing.aux_data` {#processing-aux_data}

The orbit and clock products to download

#### `processing.aux_data.agency` {#processing-aux_data-agency}

Analysis center code

- Type: text
- Default: `COD`

#### `processing.aux_data.product_type` {#processing-aux_data-product_type}

Product type. The agency must publish it: see the product registry of canvod-auxiliary (`products.toml`).

- Type: one of `final`, `rapid`
- Default: `final`

#### `processing.aux_data.ftp_timeout_s` {#processing-aux_data-ftp_timeout_s}

FTP connection timeout in seconds

- Type: whole number
- Limits: >= 1
- Default: `30`

#### `processing.aux_data.fetch_clock` {#processing-aux_data-fetch_clock}

Download and interpolate the CLK clock files with the SP3 orbit files. VOD doesn't use clock corrections; set false to skip them.

- Type: true or false
- Default: `true`

#### `processing.aux_data.zarr_async_concurrency` {#processing-aux_data-zarr_async_concurrency}

Limit on Zarr's concurrent chunk reads and writes in the orbit and clock cache; null keeps Zarr's default of 10. Set it when `shared_aux_cache_dir` is on a network mount (CIFS or NFS) that drops connections during writes.

- Type: whole number, or null
- Limits: >= 1
- Default: `null`

### `processing.params` {#processing-params}

What a run reads and computes, and how many workers it uses

#### `processing.params.resource_mode` {#processing-params-resource_mode}

`auto`: OS auto-detects workers and memory (local machines). `manual`: hard caps via `n_max_threads`, `cpu_affinity` and `nice_priority` (shared servers).

- Type: one of `auto`, `manual`
- Default: `auto`

#### `processing.params.n_max_threads` {#processing-params-n_max_threads}

Max worker processes. Required when `resource_mode`=`manual`. Ignored in `auto`.

- Type: whole number, or null
- Limits: >= 1, <= 100
- Default: `null`

#### `processing.params.auto_uncapped` {#processing-params-auto_uncapped}

Remove the automatic CPU core cap of `resource_mode` `auto`. On a shared machine, this can starve other users' processes: set it to true only when the machine is yours alone.

- Type: true or false
- Default: `false`

#### `processing.params.keep_gnss_observables` {#processing-params-keep_gnss_observables}

GNSS observables to keep (SNR, Pseudorange, Phase, Doppler)

- Type: list of text
- Default: `["SNR"]`

#### `processing.params.rinex_v3_parser` {#processing-params-rinex_v3_parser}

How RINEX v3 observation files are parsed. `validated`: every epoch is checked (epoch line, satellite IDs, satellite count, observation fields); epochs that fail are dropped and logged. `unvalidated_fast`: DANGEROUS. Parses by fixed columns without any check, so corrupted records can enter the store as partial or wrong values. On valid files both give the same dataset. canVODpy takes no responsibility for results of the unvalidated parser; checking the input files is entirely the user's responsibility. Every use emits an UnvalidatedParserWarning.

- Type: one of `validated`, `unvalidated_fast`
- Default: `validated`

#### `processing.params.aggregate_glonass_fdma` {#processing-params-aggregate_glonass_fdma}

Aggregate GLONASS FDMA sub-bands into effective G1/G2 bands. When false, the GLONASS signal IDs name the FDMA bands (`G1_FDMA`, `G2_FDMA`), for the observations and the orbit data alike. RINEX only: the SBF and NMEA readers refuse false. It changes the GLONASS signal IDs, so an existing store refuses data written with the other value.

- Type: true or false
- Default: `true`

#### `processing.params.store_radial_distance` {#processing-params-store_radial_distance}

Store radial distance (r) in the output store

- Type: true or false
- Default: `false`

#### `processing.params.store_delta_snr` {#processing-params-store_delta_snr}

Store delta SNR (`SNR_canopy` − `SNR_reference`, dB) in the VOD store. Useful for diagnosing canopy attenuation without the angular correction.

- Type: true or false
- Default: `false`

#### `processing.params.store_radial_diff` {#processing-params-store_radial_diff}

Store the radial distance difference (`r_canopy` − `r_reference`, m) in the VOD store. Requires `store_radial_distance`: true when the receivers' files are read, so that r is available in both receiver datasets.

- Type: true or false
- Default: `false`

#### `processing.params.receiver_position_mode` {#processing-params-receiver_position_mode}

`shared`: all receivers use the canopy receiver position for spherical coordinate computation (default, enables 1:1 SNR comparison). `per_receiver`: each receiver uses its own RINEX header position (physically correct geometry but breaks direct SNR comparability between receivers).

- Type: one of `shared`, `per_receiver`
- Default: `shared`

#### `processing.params.file_pairing` {#processing-params-file_pairing}

`complete`: discover files per-receiver independently (all data ingested). `paired`: only process dates where both receivers in an analysis pair have data.

- Type: one of `complete`, `paired`
- Default: `complete`

#### `processing.params.days_per_batch` {#processing-params-days_per_batch}

Days processed together in one batch (1 = one day at a time). A high value may cause connection problems with the server the orbit and clock files come from.

- Type: whole number
- Limits: >= 1, <= 30
- Default: `1`

#### `processing.params.max_memory_gb` {#processing-params-max_memory_gb}

Left over from development; has no effect, canVODpy does not limit memory. Removed with the next major version.

- Type: number, or null
- Limits: > 0
- Default: `null`

#### `processing.params.cpu_affinity` {#processing-params-cpu_affinity}

Pin workers to these CPU core IDs (null = no restriction)

- Type: list of whole number, or null
- Default: `null`

#### `processing.params.nice_priority` {#processing-params-nice_priority}

Priority of the worker processes (-20 = highest, 0 = normal, 19 = lowest). A negative value needs root or `CAP_SYS_NICE` on Linux; without it, the value has no effect.

- Type: whole number
- Limits: >= -20, <= 19
- Default: `-5`

#### `processing.params.threads_per_worker` {#processing-params-threads_per_worker}

Threads per worker process; null lets the scheduler decide. More than 1 helps array computations and reading and writing, but not the parsing of RINEX text.

- Type: whole number, or null
- Limits: >= 1, <= 8
- Default: `null`

#### `processing.params.ephemeris_source` {#processing-params-ephemeris_source}

`final`: compute satellite coordinates from agency final products (SP3/CLK). `broadcast`: use broadcast ephemerides from SBF SatVisibility blocks (SBF `reader_format` only, skips SP3/CLK download). Broadcast is faster but less accurate (~1-2 m orbit).

- Type: one of `final`, `broadcast`
- Default: `final`

#### `processing.params.store_sbf_raw_observables` {#processing-params-store_sbf_raw_observables}

When reading SBF files, also store the observables before the receiver's corrections: `SNR_raw` (before CN0HighRes), `Pseudorange_unsmoothed` (before the Hatch filter), `Pseudorange_raw` (before the Hatch and multipath filters), and `Phase_raw` (before the carrier multipath correction). Set to false to make the stores smaller when you don't need them.

- Type: true or false
- Default: `true`

#### `processing.params.store_sbf_metadata` {#processing-params-store_sbf_metadata}

When reading SBF files, store each file's SBF metadata (SatVisibility geometry and its almanac or ephemeris source, MeasExtra, PVT, DOP, receiver status and quality indicators) under {group}/metadata/`sbf_obs`, in the same commit as the observations. Set to false to save space; broadcast geometry (`ephemeris_source` `broadcast`) still works, since it uses these data in memory.

- Type: true or false
- Default: `true`

### `processing.netcdf_compression` {#processing-netcdf_compression}

Compression settings for NetCDF output from RINEX readers

#### `processing.netcdf_compression.zlib` {#processing-netcdf_compression-zlib}

Compress the NetCDF files with zlib

- Type: true or false
- Default: `true`

#### `processing.netcdf_compression.complevel` {#processing-netcdf_compression-complevel}

Compression level

- Type: whole number
- Limits: >= 0, <= 9
- Default: `5`

### `processing.icechunk` {#processing-icechunk}

How the stores are written on disk: compression and chunks

#### `processing.icechunk.compression_level` {#processing-icechunk-compression_level}

Zstandard compression level, 0 to 22

- Type: whole number
- Limits: >= 0, <= 22
- Default: `3`

#### `processing.icechunk.compression_algorithm` {#processing-icechunk-compression_algorithm}

Compression algorithm; Icechunk 2 offers only `zstd`

- Type: one of `zstd`
- Default: `zstd`

#### `processing.icechunk.inline_chunk_threshold_bytes` {#processing-icechunk-inline_chunk_threshold_bytes}

Chunks up to this size in bytes are stored in the manifest instead of in their own file

- Type: whole number
- Limits: >= 0
- Default: `512`

#### `processing.icechunk.get_partial_values_concurrency` {#processing-icechunk-get_partial_values_concurrency}

Concurrent requests when reading part of a chunk

- Type: whole number
- Limits: >= 1
- Default: `1`

#### `processing.icechunk.max_concurrent_requests` {#processing-icechunk-max_concurrent_requests}

Limit on concurrent storage requests (null = Icechunk's default)

- Type: whole number, or null
- Limits: >= 1
- Default: `null`

#### `processing.icechunk.zarr_async_concurrency` {#processing-icechunk-zarr_async_concurrency}

Limit on Zarr's concurrent chunk reads and writes per array; null keeps Zarr's default of 10. On a network-mounted store (CIFS or NFS) that drops connections during writes, set a lower value, for example 2 to 4; writes get slower.

- Type: whole number, or null
- Limits: >= 1
- Default: `null`

#### `processing.icechunk.cache_num_chunk_refs` {#processing-icechunk-cache_num_chunk_refs}

Number of chunk references Icechunk keeps in memory (null = Icechunk's default)

- Type: whole number, or null
- Limits: >= 0
- Default: `null`

#### `processing.icechunk.cache_num_bytes_chunks` {#processing-icechunk-cache_num_bytes_chunks}

Bytes of chunk data Icechunk keeps in memory (null = Icechunk's default)

- Type: whole number, or null
- Limits: >= 0
- Default: `null`

### `processing.icechunk.chunk_strategies` {#processing-icechunk-chunk_strategies}

Chunk shape of each store: a chunk is the piece of an array that is read, compressed, and written as one

### `processing.icechunk.chunk_strategies.gnss_store` {#processing-icechunk-chunk_strategies-gnss_store}

Chunks of the GNSS store. A day of ceil(86400 s / cadence) epochs is stored in whole chunks, padded with empty epochs where it does not fill the last one: with 180, days at 1 s, 5 s, 15 s, 30 s or 1 min need no padding, a day at 15 min gets 84 empty epochs.

#### `processing.icechunk.chunk_strategies.gnss_store.epoch` {#processing-icechunk-chunk_strategies-gnss_store-epoch}

Epochs per chunk, for groups created from now on: a group keeps the chunk size it was created with

- Type: whole number
- Limits: >= 1
- Default: `180`

#### `processing.icechunk.chunk_strategies.gnss_store.sid` {#processing-icechunk-chunk_strategies-gnss_store-sid}

Signals per chunk, for groups created from now on; -1 puts all signals in one chunk.

- Type: whole number
- Limits: >= -1
- Default: `-1`

### `processing.icechunk.chunk_strategies.vod_store` {#processing-icechunk-chunk_strategies-vod_store}

Chunks of the VOD store. As in the GNSS store, each day is stored in whole chunks, padded with empty epochs where it does not fill the last one.

#### `processing.icechunk.chunk_strategies.vod_store.epoch` {#processing-icechunk-chunk_strategies-vod_store-epoch}

Epochs per chunk, for groups created from now on: a group keeps the chunk size it was created with

- Type: whole number
- Limits: >= 1
- Default: `180`

#### `processing.icechunk.chunk_strategies.vod_store.sid` {#processing-icechunk-chunk_strategies-vod_store-sid}

Signals per chunk, for groups created from now on; -1 puts all signals in one chunk.

- Type: whole number
- Limits: >= -1
- Default: `-1`

#### `processing.icechunk.manifest_preload_enabled` {#processing-icechunk-manifest_preload_enabled}

Read the manifests of matching arrays when a store is opened

- Type: true or false
- Default: `false`

#### `processing.icechunk.manifest_preload_max_refs` {#processing-icechunk-manifest_preload_max_refs}

Limit on the chunk references read in advance

- Type: whole number
- Limits: >= 0
- Default: `10000`

#### `processing.icechunk.manifest_preload_max_arrays_to_scan` {#processing-icechunk-manifest_preload_max_arrays_to_scan}

Limit on the arrays checked for reading in advance

- Type: whole number
- Limits: >= 1
- Default: `500`

#### `processing.icechunk.manifest_preload_pattern` {#processing-icechunk-manifest_preload_pattern}

Regular expression for the names of the arrays to read in advance

- Type: text
- Default: `^(epoch|sid)$`

#### `processing.icechunk.manifest_splitting_enabled` {#processing-icechunk-manifest_splitting_enabled}

Enable manifest splitting for stores with large arrays (recommended)

- Type: true or false
- Default: `true`

#### `processing.icechunk.manifest_splitting_epoch_range` {#processing-icechunk-manifest_splitting_epoch_range}

Epoch chunks per manifest: Icechunk starts a new manifest of an array every N chunks along the epoch dimension (N chunks, not N epochs).

- Type: whole number
- Limits: >= 1
- Default: `17280`

#### `processing.icechunk.num_updates_per_repo_info_file` {#processing-icechunk-num_updates_per_repo_info_file}

Number of updates that share one `repo` file before Icechunk starts a new one (null = Icechunk's default). A low value makes each write smaller but makes reading the history slower.

- Type: whole number, or null
- Limits: >= 1, <= 65535
- Default: `null`

#### `processing.icechunk.repo_update_max_tries` {#processing-icechunk-repo_update_max_tries}

Attempts, the first included, to update the `repo` file, for example when several writers update it (null = Icechunk's default, currently 100)

- Type: whole number, or null
- Limits: >= 1
- Default: `null`

#### `processing.icechunk.repo_update_initial_backoff_ms` {#processing-icechunk-repo_update_initial_backoff_ms}

First wait in milliseconds between attempts to update the `repo` file (null = Icechunk's default, currently 50)

- Type: whole number, or null
- Limits: >= 0
- Default: `null`

#### `processing.icechunk.repo_update_max_backoff_ms` {#processing-icechunk-repo_update_max_backoff_ms}

Longest wait in milliseconds between attempts to update the `repo` file (null = Icechunk's default, currently 30,000)

- Type: whole number, or null
- Limits: >= 0
- Default: `null`

### `processing.storage` {#processing-storage}

Where the stores are, and what a run does with stored files

#### `processing.storage.stores_root_dir` {#processing-storage-stores_root_dir}

Folder of the stores: each site's GNSS store and VOD store are under it. A local folder (must exist and be writable) or s3://bucket/prefix; credentials, region and endpoint of S3 come from the environment.

- Type: path or text
- Default: none, you have to set it

#### `processing.storage.gnss_store_name` {#processing-storage-gnss_store_name}

Name of the GNSS observation Icechunk store directory

- Type: text
- Default: `rinex`

#### `processing.storage.vod_store_name` {#processing-storage-vod_store_name}

Name of the VOD Icechunk store directory

- Type: text
- Default: `vod`

#### `processing.storage.aux_data_dir` {#processing-storage-aux_data_dir}

Directory for downloaded auxiliary files (SP3, CLK) and transient Zarr caches. Raw files persist; caches are rebuilt each run. Defaults to system temp directory if not set.

- Type: path, or null
- Default: `null`

#### `processing.storage.shared_aux_cache_dir` {#processing-storage-shared_aux_cache_dir}

Folder of an orbit and clock cache that several sites share (SP3 and CLK, interpolated). null (default): no shared cache; each site's cache is in `aux_data_dir` and rebuilt every run. Orbit and clock products are the same for every site, so sites that point at the same folder share one cache entry per agency, product and date instead of each building its own.

- Type: path, or null
- Default: `null`

#### `processing.storage.gnss_store_strategy` {#processing-storage-gnss_store_strategy}

What a run does with a file that is already in the GNSS store; new files are always written. `skip` (default): nothing is written. `overwrite`: the run replaces the file's slots. `unsafe_append`: kept from versions before day blocks, where it stored the file's epochs twice; it now does what `overwrite` does.

- Type: one of `skip`, `overwrite`, `unsafe_append`
- Default: `skip`

#### `processing.storage.vod_store_strategy` {#processing-storage-vod_store_strategy}

Deprecated, has no effect. A VOD write skips a result from the same GNSS files as a stored one. Another result replaces the stored VOD of its day. To recompute VOD from the same GNSS files, write to a new VOD store (set another `vod_store_name`).

- Type: one of `skip`, `overwrite`, `unsafe_append`, or null
- Default: `null`

#### `processing.storage.keeper_tags` {#processing-storage-keeper_tags}

Tag every commit of a receiver and day as keep/{receiver}/{yyyydoy}, so a later clean-up can expire everything else. Off by default: the cost of tagging a large store hasn't been measured yet.

- Type: true or false
- Default: `false`

### `processing.storage.maintenance` {#processing-storage-maintenance}

Scheduled clean-up of old snapshots (canvodpy store maintain-due)

#### `processing.storage.maintenance.enabled` {#processing-storage-maintenance-enabled}

Turn on canvodpy store maintain-due. Off by default. Before you turn it on, run `garbage_collect`(`dry_run`=True) against your store and check what it would delete.

- Type: true or false
- Default: `false`

#### `processing.storage.maintenance.dry_run_until_confirmed` {#processing-storage-maintenance-dry_run_until_confirmed}

Make every run of canvodpy store maintain-due a dry run until you set this to false. An unattended job can't answer the question that maintain --execute asks; this setting is that answer.

- Type: true or false
- Default: `true`

#### `processing.storage.maintenance.retention_days` {#processing-storage-maintenance-retention_days}

Days of snapshots the scheduled clean-up keeps; older snapshots are expired and their data collected as garbage. canvodpy store maintain --expire-days, run by hand, doesn't use it.

- Type: whole number
- Limits: >= 7
- Default: `90`

#### `processing.storage.maintenance.expire_interval_days` {#processing-storage-maintenance-expire_interval_days}

Days from one expiration by the scheduled clean-up to the next, counted from the last expiration in the store's operations log.

- Type: whole number
- Limits: >= 1
- Default: `45`

#### `processing.storage.maintenance.gc_delay_days` {#processing-storage-maintenance-gc_delay_days}

Days the scheduled clean-up waits after the last expiration before it collects garbage, so it deletes data only some time after their snapshots expired.

- Type: whole number
- Limits: >= 1
- Default: `20`

#### `processing.storage.maintenance.manifests_enabled` {#processing-storage-maintenance-manifests_enabled}

Let canvodpy store maintain-due rewrite the manifests, whatever `enabled` says. A rewrite is an ordinary commit: it changes no history and deletes nothing.

- Type: true or false
- Default: `false`

#### `processing.storage.maintenance.manifest_count_threshold` {#processing-storage-maintenance-manifest_count_threshold}

Number of manifest files in the store at which canvodpy store maintain-due rewrites the manifests.

- Type: whole number
- Limits: >= 1
- Default: `3000`

### `processing.logging` {#processing-logging}

Where the log files go

#### `processing.logging.log_dir` {#processing-logging-log_dir}

Folder of the log files. Required for a processing run: a run stops if it is not set.

- Type: path, or null
- Default: `null`

#### `processing.logging.worker_log_retention_days` {#processing-logging-worker_log_retention_days}

Days after which the log files of worker processes are deleted, counted from their last change. Each worker process writes its own files, with its process ID in the name.

- Type: whole number
- Limits: >= 1
- Default: `30`

#### `processing.logging.log_file_name` {#processing-logging-log_file_name}

Left over from development; has no effect. Removed with the next major version.

- Type: text, or null
- Default: `null`

#### `processing.logging.log_path_depth` {#processing-logging-log_path_depth}

Number of path components to include in log file references

- Type: whole number
- Limits: >= 1, <= 20
- Default: `6`

### `processing.preprocessing` {#processing-preprocessing}

Operations applied to each receiver's data before it is written to the GNSS store; none unless set

### `processing.preprocessing.temporal_aggregation` {#processing-preprocessing-temporal_aggregation}

Temporal aggregation; not applied unless set

#### `processing.preprocessing.temporal_aggregation.enabled` {#processing-preprocessing-temporal_aggregation-enabled}

Apply the temporal aggregation

- Type: true or false
- Default: `true`

#### `processing.preprocessing.temporal_aggregation.freq` {#processing-preprocessing-temporal_aggregation-freq}

Bin length: a whole number of seconds, minutes or hours (`30s`, `1min`, `1h`) that divides one day

- Type: text
- Default: none, you have to set it

#### `processing.preprocessing.temporal_aggregation.method` {#processing-preprocessing-temporal_aggregation-method}

Statistic of the floating-point observations in each bin

- Type: one of `mean`, `median`
- Default: none, you have to set it

#### `processing.preprocessing.temporal_aggregation.integer_method` {#processing-preprocessing-temporal_aggregation-integer_method}

Value of each bin integer variables (flags and codes such as LLI and SSI) take, in time order; they cannot be combined

- Type: one of `first`, `last`, `middle`
- Default: none, you have to set it

### `processing.preprocessing.grid_assignment` {#processing-preprocessing-grid_assignment}

Grid cell assignment; not applied unless set

#### `processing.preprocessing.grid_assignment.enabled` {#processing-preprocessing-grid_assignment-enabled}

Apply the grid cell assignment

- Type: true or false
- Default: `true`

#### `processing.preprocessing.grid_assignment.grid_type` {#processing-preprocessing-grid_assignment-grid_type}

Grid type, for example `equal_area`

- Type: text
- Default: none, you have to set it

#### `processing.preprocessing.grid_assignment.angular_resolution` {#processing-preprocessing-grid_assignment-angular_resolution}

Angular resolution in degrees

- Type: number
- Limits: > 0, <= 90
- Default: none, you have to set it

### `processing.references` {#processing-references}

Publication and funding references

#### `processing.references.software_repository` {#processing-references-software_repository}

URL of the software repository (for example GitHub)

- Type: text, or null
- Default: `null`

#### `processing.references.documentation` {#processing-references-documentation}

URL of the documentation

- Type: text, or null
- Default: `null`

#### `processing.references.access_url` {#processing-references-access_url}

URL where the store data is actually accessible (FAIR A1)

- Type: text, or null
- Default: `null`

#### `processing.references.related_stores` {#processing-references-related_stores}

Identifiers/paths of related stores

- Type: list of text
- Default: `[]`

### `processing.references.publications` {#processing-references-publications}

Publications about the data, for the store metadata

#### `processing.references.publications[].doi` {#processing-references-publications-doi}

DOI of the publication

- Type: text
- Default: none, you have to set it

#### `processing.references.publications[].citation` {#processing-references-publications-citation}

Citation of the publication

- Type: text, or null
- Default: `null`

### `processing.references.funding` {#processing-references-funding}

Funding of the work, for the store metadata

#### `processing.references.funding[].funder` {#processing-references-funding-funder}

Name of the funding organization

- Type: text
- Default: none, you have to set it

#### `processing.references.funding[].funder_ror` {#processing-references-funding-funder_ror}

ROR identifier of the funding organization

- Type: text, or null
- Default: `null`

#### `processing.references.funding[].grant_number` {#processing-references-funding-grant_number}

Grant number

- Type: text, or null
- Default: `null`

#### `processing.references.funding[].award_title` {#processing-references-funding-award_title}

Title of the grant

- Type: text, or null
- Default: `null`

## `sites` {#sites}

The research sites, their receivers, and VOD analyses

### `sites.<site>` {#sites-site}

A research site, named by its key: its data folder, receivers, and VOD analyses

#### `sites.<site>.gnss_site_data_root` {#sites-site-gnss_site_data_root}

Root directory for site GNSS data

- Type: text
- Default: none, you have to set it

#### `sites.<site>.description` {#sites-site-description}

Site description

- Type: text, or null
- Default: `null`

#### `sites.<site>.store_description` {#sites-site-store_description}

What the site's stores hold (for example `GNSS-T observations below a beech canopy`): written to `StoreIdentity.description`. Required when a store of the site is created.

- Type: text, or null
- Default: `null`

#### `sites.<site>.country` {#sites-site-country}

Country code (ISO 3166-1)

- Type: text, or null
- Default: `null`

#### `sites.<site>.latitude` {#sites-site-latitude}

WGS84 latitude

- Type: number, or null
- Default: `null`

#### `sites.<site>.longitude` {#sites-site-longitude}

WGS84 longitude

- Type: number, or null
- Default: `null`

#### `sites.<site>.altitude_m` {#sites-site-altitude_m}

Altitude in meters

- Type: number, or null
- Default: `null`

### `sites.<site>.receivers` {#sites-site-receivers}

The site's receivers, each named by its key

#### `sites.<site>.receivers.<receiver>.type` {#sites-site-receivers-receiver-type}

Receiver role: `canopy` = placed under the vegetation canopy; `reference` = open-sky baseline above or outside the canopy

- Type: one of `reference`, `canopy`
- Default: none, you have to set it

#### `sites.<site>.receivers.<receiver>.directory` {#sites-site-receivers-receiver-directory}

Subdirectory for receiver data

- Type: text
- Default: none, you have to set it

#### `sites.<site>.receivers.<receiver>.paired_canopies` {#sites-site-receivers-receiver-paired_canopies}

The canopy receivers to pair with this reference: `all` or a list of canopy names. Required for reference receivers; must not be set for canopy receivers.

- Type: text or list of text, or null
- Default: `null`

#### `sites.<site>.receivers.<receiver>.description` {#sites-site-receivers-receiver-description}

Human-readable description

- Type: text, or null
- Default: `null`

#### `sites.<site>.receivers.<receiver>.naming` {#sites-site-receivers-receiver-naming}

Deprecated, not used for file discovery. Set `recipe` for non-canonical filenames instead.

- Type: mapping, or null
- Default: `null`

#### `sites.<site>.receivers.<receiver>.metadata` {#sites-site-receivers-receiver-metadata}

Your own receiver metadata, added to the attributes of every file of the receiver that is written to the GNSS store: the log book keeps them per file, and a new group also takes them from its first file. Attributes a file already has are kept. Example keys: `site_url`, `antenna_height`, species.

- Type: mapping, or null
- Default: `null`

### `sites.<site>.receivers.<receiver>.receiver_hardware` {#sites-site-receivers-receiver-receiver_hardware}

Optional: the receiver's manufacturer, model, serial number and firmware, copied into the GNSS store's metadata.

#### `sites.<site>.receivers.<receiver>.receiver_hardware.manufacturer` {#sites-site-receivers-receiver-receiver_hardware-manufacturer}

Receiver manufacturer

- Type: text, or null
- Default: `null`

#### `sites.<site>.receivers.<receiver>.receiver_hardware.model` {#sites-site-receivers-receiver-receiver_hardware-model}

Receiver model

- Type: text, or null
- Default: `null`

#### `sites.<site>.receivers.<receiver>.receiver_hardware.serial_number` {#sites-site-receivers-receiver-receiver_hardware-serial_number}

Receiver serial number

- Type: text, or null
- Default: `null`

#### `sites.<site>.receivers.<receiver>.receiver_hardware.firmware` {#sites-site-receivers-receiver-receiver_hardware-firmware}

Firmware version

- Type: text, or null
- Default: `null`

### `sites.<site>.receivers.<receiver>.antenna` {#sites-site-receivers-receiver-antenna}

Optional: the antenna's manufacturer, model and radome (IGS names), serial number and height, copied into the GNSS store's metadata.

#### `sites.<site>.receivers.<receiver>.antenna.manufacturer` {#sites-site-receivers-receiver-antenna-manufacturer}

Antenna manufacturer

- Type: text, or null
- Default: `null`

#### `sites.<site>.receivers.<receiver>.antenna.model` {#sites-site-receivers-receiver-antenna-model}

Antenna model, as its IGS name

- Type: text, or null
- Default: `null`

#### `sites.<site>.receivers.<receiver>.antenna.radome` {#sites-site-receivers-receiver-antenna-radome}

Radome, as its IGS name

- Type: text, or null
- Default: `null`

#### `sites.<site>.receivers.<receiver>.antenna.serial_number` {#sites-site-receivers-receiver-antenna-serial_number}

Antenna serial number

- Type: text, or null
- Default: `null`

#### `sites.<site>.receivers.<receiver>.antenna.height_m` {#sites-site-receivers-receiver-antenna-height_m}

Antenna height in meters

- Type: number, or null
- Default: `null`

#### `sites.<site>.receivers.<receiver>.antenna.choke_ring` {#sites-site-receivers-receiver-antenna-choke_ring}

Whether a choke ring is used

- Type: true or false, or null
- Default: `null`

#### `sites.<site>.receivers.<receiver>.antenna.polarization` {#sites-site-receivers-receiver-antenna-polarization}

Polarization the antenna receives: `RHCP` (the standard), `LHCP` or `dual-pol`

- Type: one of `RHCP`, `LHCP`, `dual-pol`, or null
- Default: `null`

#### `sites.<site>.receivers.<receiver>.reader_format` {#sites-site-receivers-receiver-reader_format}

Reader for the receiver's files: `rinex3` (RINEX 3), `rinex3_stripped` (RINEX 3 with signal strengths only, faster), `rinex2` (RINEX 2.11), `sbf` (Septentrio binary), `nmea`, or the name of an installed reader plugin. `auto`: detected per day from the files (SBF and NMEA by file type, RINEX 2 or 3 from the header; never a plugin); a day whose files need different readers is an error.

- Type: text
- Default: `auto`

#### `sites.<site>.receivers.<receiver>.recipe` {#sites-site-receivers-receiver-recipe}

Name of a naming recipe (for example `examplesite_reference`). Read from &lt;config dir&gt;/recipes/&lt;site&gt;/{recipe}.yaml. Without a recipe, only files with canonical canVOD names are processed.

- Type: text, or null
- Default: `null`

### `sites.<site>.vod_analyses` {#sites-site-vod_analyses}

The site's VOD analyses, each named by its key: a canopy receiver and its reference receiver

#### `sites.<site>.vod_analyses.<analysis>.canopy_receiver` {#sites-site-vod_analyses-analysis-canopy_receiver}

Canopy receiver name

- Type: text
- Default: none, you have to set it

#### `sites.<site>.vod_analyses.<analysis>.reference_receiver` {#sites-site-vod_analyses-analysis-reference_receiver}

Reference receiver name, as named under `receivers`

- Type: text
- Default: none, you have to set it

#### `sites.<site>.vod_analyses.<analysis>.description` {#sites-site-vod_analyses-analysis-description}

Analysis description

- Type: text, or null
- Default: `null`

#### `sites.<site>.naming` {#sites-site-naming}

Deprecated, not used for file discovery. Set `recipe` on each receiver with non-canonical filenames instead.

- Type: mapping, or null
- Default: `null`

## `sids` {#sids}

Which signals are kept

#### `sids.mode` {#sids-mode}

SID selection mode

- Type: one of `all`, `preset`, `custom`
- Default: `all`

#### `sids.preset` {#sids-preset}

Preset name when mode=preset

- Type: text, or null
- Default: `null`

#### `sids.custom_sids` {#sids-custom_sids}

Custom SID list when mode=custom

- Type: list of text
- Default: `[]`
