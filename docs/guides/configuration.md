# Configuration Guide

## Why canVODpy needs a configuration file

Most scientific Python packages work immediately after installation. Opposed to that, canVODpy manages a long-running, multi-file, multi-site data pipeline that
produces versioned scientific stores. Some things cannot be inferred from the code:

- **Where your data lives** — file paths differ on every machine, HPC cluster, or deployment.
- **Who you are** — your name, institution, and ORCID are written into the Icechunk store's
  provenance metadata for reproducibility and FAIR compliance.
- **How much compute to use** — a laptop and a 64-core server require different resource
  limits. canVODpy defaults to an automatic mode; you can override this for your hardware.

Everything else, SID filtering, chunk strategies, aggregation parameters, ships with defaults, but can be tuned according to your needs.

Configuration is validated by
[pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/).
Every field is type-checked at load time: a typo in a field name, or a string where a number
belongs, is reported immediately with the exact location.

---

## Configuration commands

```bash
# Setup
just config-init                       # scaffold canvod-settings.yaml from template
just config-edit                       # open canvod-settings.yaml in $EDITOR
just config-delete                     # delete canvod-settings.yaml (requires typed confirmation)

# Verification
just config-validate                   # validate config against Pydantic models
just config-show                       # print the fully resolved config (see note below)
just config-check-data <site>          # validate file names in all receiver directories
```

`just config-show` prints the **fully resolved** configuration. Any value set via environment
variable (see [Environment variable overrides](#environment-variable-overrides) below) is shown
as the effective value — not the YAML value it supersedes. This is the authoritative way to
confirm what canVODpy will actually use at runtime.

---

## Overlay config file

For deployment-specific overrides — different store paths on a cluster, a CI environment,
a shared server — use an overlay file instead of modifying `canvod-settings.yaml`.

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

### Overlays can only add or override — never delete

The overlay is merged **on top of** the base `canvod-settings.yaml`; it can add new keys or
override existing ones, but it cannot remove a key that exists in the base file. If your base
file defines a site (or any other field) that isn't mentioned in the overlay, that entry stays
in the resolved config no matter what the overlay contains.

!!! warning "Common trap: the scaffolded placeholder site"

    `canvod-settings.yaml` (from `just config-init`) ships with a live, uncommented `my_site:`
    placeholder under `sites:` — meant to be **renamed** to your real site, not kept alongside
    it. If you added your real site as a new block instead of renaming the placeholder,
    `my_site` is still there with unreachable paths like `/path/to/your/gnss/data/my_site` —
    and `config validate` / `run` will fail on it, since no overlay can delete it, only the
    base file itself can.

    Fix: edit the base `canvod-settings.yaml` directly and remove the leftover placeholder
    site under `sites:`. If the base file has accumulated enough cruft that starting over is
    easier, `just config-delete` removes it (with a typed confirmation, since this is
    destructive) so you can `just config-init` fresh.

---

## File layout

```
config/
└── canvod-settings.yaml          # unified configuration (processing, sites, sids)
```

**Precedence:** environment variable > overlay file (`--config`) > `canvod-settings.yaml` > package defaults.

Only the fields you want to change need to be written — everything else falls back to package
defaults. Unknown field names are rejected throughout the config tree (`extra="forbid"`),
so typos surface at load time rather than causing silent misconfiguration.

Two environment variables control *where* configuration is read from:

| Variable             | Effect                                                           |
| -------------------- | ---------------------------------------------------------------- |
| `CANVOD_CONFIG_DIR`  | Use a different config directory (default: `{repo_root}/config`) |
| `CANVOD_CONFIG_FILE` | Apply an overlay YAML on top of the main `canvod-settings.yaml`  |

---

## Environment variable overrides

Any configuration value can be overridden without editing the file by setting an environment
variable with the `CANVOD__` prefix, using double underscores (`__`) to separate nesting
levels. This is particularly useful on HPC clusters and shared servers, where resource limits
vary per job but the configuration file is version-controlled:

```bash
CANVOD__PROCESSING__PARAMS__N_MAX_THREADS=4 \
    uv run canvodpy run --site mysite
CANVOD__PROCESSING__PARAMS__DAYS_PER_BATCH=7 \
    uv run canvodpy run --site mysite
```

!!! warning "This must stay one shell command"

    `VAR=value` set on its own line (without `export`) only exists in your *current*
    shell — it is never passed down to `canvodpy`, a separate process. The `\` above
    is a line continuation: it keeps `VAR=value` and the command that follows as a
    single shell statement. Do not press Enter after the `VAR=value` line and then
    run the command separately — that sets a local variable and silently does
    nothing.

    Two ways to avoid the trap:

    ```bash
    # inline, one line, no backslash needed:
    CANVOD__PROCESSING__PARAMS__DAYS_PER_BATCH=7 uv run canvodpy run --site mysite

    # or export it once, then reuse it across multiple commands:
    export CANVOD__PROCESSING__PARAMS__DAYS_PER_BATCH=7
    just config-show   # confirms the override took effect
    uv run canvodpy run --site mysite
    ```

Scalar values (strings, integers, booleans) are passed as-is. List values require JSON
encoding:

```bash
CANVOD__PROCESSING__PARAMS__KEEP_GNSS_OBSERVABLES='["SNR","Pseudorange"]' \
    uv run canvodpy run --site mysite
```

Some examples, but really all configuration fields can be overwritten:

| Variable                                                   | Overrides                                        |
| ---------------------------------------------------------- | ------------------------------------------------ |
| `CANVOD__PROCESSING__STORAGE__STORES_ROOT_DIR`             | `processing.storage.stores_root_dir`             |
| `CANVOD__PROCESSING__CREDENTIALS__NASA_EARTHDATA_ACC_MAIL` | `processing.credentials.nasa_earthdata_acc_mail` |
| `CANVOD__PROCESSING__PARAMS__N_MAX_THREADS`                | `processing.params.n_max_threads`                |

Environment variables take priority over all other sources. To confirm the effective value,
run `just config-show` — if `CANVOD__PROCESSING__PARAMS__N_MAX_THREADS=4` is set in the
environment, the output will show `n_max_threads: 4` regardless of what the YAML file says.

---

## Minimal working example

A complete, valid `canvod-settings.yaml` requires only a handful of fields — everything
else is covered by package defaults:

```yaml
processing:
  metadata:
    author: Jane Scientist
    email: jane.scientist@example.edu
    institution: Example University

  storage:
    stores_root_dir: /data/stores

sites:
  mysite:
    gnss_site_data_root: /data/mysite

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

## processing:

Controls metadata, resource allocation, storage, and auxiliary data retrieval.

```yaml
processing:
  metadata:
    author: Your Name
    email: your.email@example.com
    institution: Your Institution
    # optional: orcid, institution_ror, department, research_group,
    # website, license, publisher, publisher_url, naming_authority

  credentials:
    nasa_earthdata_acc_mail: null  # prefer the env var — see table above

  aux_data:
    agency: COD          # SP3/CLK analysis center code
    product_type: final  # final, rapid, or ultra-rapid
    # fetch_clock: true  # set false to skip CLK download/interpolation — unused by VOD

  params:
    keep_gnss_observables: [SNR]   # observables to keep (SNR, Pseudorange, Phase, Doppler)
    store_radial_distance: false   # store satellite distance (r)
    receiver_position_mode: shared # or per_receiver
    file_pairing: complete         # or paired
    ephemeris_source: final        # or broadcast (SBF only)
    days_per_batch: 1              # calendar days per processing wave (1–30)

    # --- Resource management ---
    resource_mode: auto            # auto or manual
    # n_max_threads: 4             # required if manual
    # max_memory_gb: 16            # soft RAM limit (manual only)
    # cpu_affinity: [0, 1, 2, 3]  # pin to CPU cores (Linux)
    # nice_priority: 10            # 0=normal, 19=lowest priority

  preprocessing:
    temporal_aggregation:
      enabled: true
      freq: "1min"                 # target time resolution
      method: mean                 # mean or median
    grid_assignment:
      enabled: true
      grid_type: equal_area
      angular_resolution: 2.0     # degrees

  netcdf_compression:              # NetCDF output from RINEX readers
    zlib: true
    complevel: 5

  icechunk:
    compression_level: 3
    compression_algorithm: zstd
    inline_chunk_threshold_bytes: 512
    chunk_strategies:
      rinex_store:
        epoch: 17280  # 24h at 5s sampling; override to match your site's rate
        sid: -1
      vod_store:
        epoch: 17280
        sid: -1

  storage:
    stores_root_dir: /path/to/stores  # prefer CANVOD__PROCESSING__STORAGE__STORES_ROOT_DIR
    gnss_store_strategy: skip         # skip, overwrite, or unsafe_append -- see warning below
    vod_store_strategy: overwrite
```

### Key fields

| Field                           | Values                   | Description                                                                                                                                                                              |
| ------------------------------- | ------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `params.keep_gnss_observables`  | list                     | GNSS observables to retain (default `[SNR]`).                                                                                                                                            |
| `params.receiver_position_mode` | `shared`, `per_receiver` | `shared` uses canopy receiver position for all receivers (enables 1:1 SNR comparison). `per_receiver` uses each receiver's own position.                                                 |
| `params.file_pairing`           | `complete`, `paired`     | `complete` ingests all files per receiver independently. `paired` only processes dates where both receivers have data.                                                                   |
| `params.ephemeris_source`       | `final`, `broadcast`     | `final` computes satellite positions from agency SP3/CLK products. `broadcast` uses ephemerides from SBF SatVisibility blocks (SBF only, no SP3/CLK download, faster but less accurate). |
| `aux_data.fetch_clock`          | `true`, `false`          | Whether to download and interpolate CLK clock-correction files alongside SP3 (only applies to `ephemeris_source: final`). Default `true`. VOD doesn't consume clock data — disable to save downloads/parsing/interpolation time. |
| `params.days_per_batch`         | 1–30                     | Calendar days pooled per parallel processing wave.                                                                                                                                       |
| `params.resource_mode`          | `auto`, `manual`         | `auto` detects available CPU cores and leaves two free for the operating system. `manual` enforces explicit limits (`n_max_threads` is then required) — use this on shared servers.      |
| `params.store_radial_distance`  | `true`, `false`          | Whether to store satellite radial distance in the output.                                                                                                                                |
| `storage.gnss_store_strategy`   | `skip`, `overwrite`, `unsafe_append` | What to do when a file already exists in the store. `skip` (default) is the normal case. See warning below before ever using `unsafe_append`.                              |

For a full explanation of how `resource_mode`, `days_per_batch`, and `n_max_threads` interact
with the parallel processing architecture, see
[Parallel Processing](parallel-processing.md).

!!! warning "`gnss_store_strategy: unsafe_append` can corrupt unguarded reads"
    `skip` (the default) is a no-op when a file already exists — the correct behavior for
    the normal workflow of chronologically filling an initially-empty store, where a
    re-run over already-ingested files should change nothing. `overwrite` deletes the old
    epochs for a file's range before writing the replacement — use it after a *pipeline*
    bug fix (reader logic, ephemeris source) when you need to regenerate previously-stored
    results, not because the raw GNSS file itself changed.

    `unsafe_append` writes the file's data again on top of what's already there, with **no
    epoch-level uniqueness check**, producing duplicate `epoch` coordinate values in the
    Zarr array. The two built-in pipeline read paths already guard against this:
    `GnssResearchSite.read_receiver_data()` routes through `read_group_deduplicated()`
    whenever this strategy is set, and `VodComputer.compute_bulk()` unconditionally
    deduplicates every read via `_dedup_sort()` regardless of strategy. But
    `MyIcechunkStore.read_group()` itself — the low-level API used directly by custom
    scripts/notebooks, and by the deprecated L1 `Pipeline.calculate_vod()` — has no such
    guard: `.sel()` on a duplicated label can raise or silently return multiple matches,
    and aligning two datasets that both carry the duplicate (e.g. canopy vs. reference)
    produces a cartesian product at those epochs. The duplication is also physical, not
    just a read-time artifact: Icechunk stores the extra chunks permanently regardless of
    whether the read side protects against it. Avoid `unsafe_append` unless you have a
    specific reason, and be aware any read path outside the two guarded ones above is
    unprotected.

### Ephemeris data sources

Agency SP3/CLK products are downloaded from **ESA GSSC** by default — no account or
credentials are required. Setting `credentials.nasa_earthdata_acc_mail` to a registered
NASA Earthdata email address enables **NASA CDDIS** as a primary source, with ESA GSSC
as fallback.

---

## sites:

Defines research sites, their receivers, and VOD analysis pairs.
Each top-level key under `sites:` is a site name — there is no additional `sites:` nesting.

```yaml
sites:
  my_site:
    gnss_site_data_root: /data/my_site
    description: null        # optional free-text description
    country: null            # ISO 3166-1 alpha-2, e.g. AT
    latitude: null           # WGS84 decimal degrees
    longitude: null
    altitude_m: null         # metres above WGS84 ellipsoid

    receivers:
      reference_01:
        type: reference
        directory: 01_reference
        reader_format: auto           # rinex3, sbf, or auto
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
| `reader_format`   | `auto`  | Force a specific reader: `rinex3`, `sbf`, or `auto` (detect from file).                                                                                                                                                                            |
| `paired_canopies` | --      | Which canopy receivers this reference is paired with: `all` or a list of canopy receiver names. Required for reference receivers, must not be set for canopy receivers. (The old name `scs_from` is deprecated and still accepted with a warning.) |

---

## sids:

Controls which satellite signal IDs (SIDs) are retained during processing.
Three modes are available:

| Mode     | Behaviour                                          |
| -------- | -------------------------------------------------- |
| `all`    | Keep every SID observed in the file — no filtering |
| `preset` | Use a named built-in list (see below)              |
| `custom` | Keep only the SIDs you list explicitly             |

=== "Default preset"

    The package ships one built-in preset: `default` — a curated 277-SID
    multi-GNSS list covering MEO satellites only (GPS + Galileo + BeiDou MEO +
    GLONASS). GEO, IGSO, augmentation signals (SBAS/IRNSS/QZSS), and GPS L2W are
    excluded because they are not useful for canopy transmissometry.

    ```yaml
    sids:
      mode: preset
      preset: default
    ```

    This is the **package default**. Use `mode: all` to opt out and keep every observed SID.

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

The `default` preset is reviewed and updated at every release to reflect satellite launches,
decommissions, and orbit reclassifications. See the [release procedure](../../RELEASING.md)
for details.

---

## Validating configuration and data

Validation runs in two distinct steps — one for the configuration file, one for the data
directories it references.

**Config validation** runs `canvod-settings.yaml` through the Pydantic models and reports
field errors (wrong types, missing required values, unknown keys), then checks that each
receiver directory exists and contains data files:

```bash
just config-validate
```

**Data directory validation** checks the file names inside a receiver directory against
the canVOD naming convention before any data is read:

```bash
canvod-preflight validate /data/examplesite/02_canopy \
    --site ROS --agency TUW --receiver 1 --role canopy
```

For a site already defined in `canvod-settings.yaml`: `just config-check-data <site>`.

---

## Optional: non-canonical filenames

!!! warning "This deviates from the community-agreed GNSS-T file naming convention"
    The standard pipeline expects every GNSS data file to follow the
    [community-agreed  filename convention](../packages/naming/overview.md),
    which is enforced by `canvod-preflight` before any data is read.

    If your receiver outputs files in a proprietary or legacy format —
    Septentrio SBF with firmware-generated names, RINEX v2 short names,
    or a custom directory layout — the optional
    [`canvod-filemap`](https://github.com/nfb2021/canvodpy-extensions) package
    provides a recipe-based mapping layer that translates physical filenames to
    canonical names **without renaming anything on disk**.

    Recipes are an escape hatch for non-conforming data, not the intended workflow.
    Where possible, rename files to the canonical convention using `gfzrnx` as a
    one-time per-site step.

Install separately from the [canvodpy-extensions](https://github.com/nfb2021/canvodpy-extensions)
repository (see [Optional Extensions](extensions.md) for details and alternatives):

```bash
uv add "canvod-filemap @ git+https://github.com/nfb2021/canvodpy-extensions.git@v0.1.0#subdirectory=packages/canvod-filemap"
```

Reference a recipe from `canvod-settings.yaml` on the receiver whose files use non-canonical names:

```yaml
sites:
  my_site:
    receivers:
      reference_01:
        recipe: my_site_reference   # → config/recipes/my_site_reference.yaml
```

`just config-init` copies recipe templates into `config/recipes/` alongside
`canvod-settings.yaml`. The full recipe format and API are documented in the
[canvod-filemap repository](https://github.com/nfb2021/canvodpy-extensions).

---

!!! example "Try it"
    [02 · Configuration](../notebooks/_build/02_configuration.html){target=_blank}
    · [view source on molab](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/02_configuration.py)
