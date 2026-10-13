# canvod-store-metadata

Rich metadata lifecycle for canvod Icechunk stores. Defines, collects, writes, reads
and validates metadata aligned with **DataCite 4.5**, **ACDD 1.3**, and
**STAC 1.1**, and writes the STAC catalog and the releases of all stores
under a data root.

## Installation

```bash
uv add canvod-store-metadata
```

## Configuration (optional)

`collect_metadata()` uses `canvod-config`'s `find_monorepo_root()` (wrapped
in a fallback — a missing/unresolvable config doesn't block metadata
collection) to help identify the environment a store was written in. In a
standalone install outside a canvodpy monorepo checkout, point it at a
settings file with:

- `CANVOD_CONFIG_DIR` — directory containing `canvod-settings.yaml`
- `CANVOD_CONFIG_FILE` — an overlay YAML file merged on top

## Naming: "store metadata" vs "file registry"

canvod has two distinct concepts that both involve "metadata":

| Concept | Package | Location in store | What it tracks |
| --- | --- | --- | --- |
| **Store metadata** | `canvod-store-metadata` (this package) | Icechunk's repository metadata, a copy in the root attributes of every snapshot | *Who/what/when/how* — identity, creator, provenance, environment, compliance |
| **File registry** | `canvod-store` (`MyIcechunkStore`) | `{group}/metadata/table` Zarr arrays | *Which files* went in — per-file hash, temporal range, filename, path |

In short: **store metadata** describes the store as a whole (for catalogs, reproducibility,
and compliance), while the **file registry** is an internal ingest ledger that tracks
individual source files for deduplication and auditing.

## Quick start

```python
from pathlib import Path
from canvod.store_metadata import (
    write_metadata,
    read_metadata,
    format_metadata,
    validate_all,
    extract_env,
    write_catalog,
    scan_stores,
)

# Write a new store's metadata (build it with collect_metadata)
write_metadata(store_path, metadata)

# Read it back
meta = read_metadata(store_path)

# Human-readable report
print(format_metadata(meta))

# Query a single section
print(format_metadata(meta, section="env"))

# Validate against the zarr conventions, ACDD, DataCite, STAC, FAIR
issues = validate_all(meta, store_path=store_path)

# Write the STAC catalog of every store under the data root
write_catalog(data_root)

# Reproduce the exact Python environment
extract_env(store_path, Path("repro_env/"))
# then: cd repro_env && uv sync --frozen
```

## CLI

```bash
python -m canvod.store_metadata.show /path/to/store              # full report
python -m canvod.store_metadata.show /path/to/store identity     # one section
python -m canvod.store_metadata.show /path/to/store reproduce    # env reproduction
python -m canvod.store_metadata.show /path/to/store uv           # raw uv.lock
python -m canvod.store_metadata.show /path/to/store toml         # raw pyproject.toml
```

---

## What we track (14 sections)

The metadata has three parts (ADR 0014). The **repository metadata**, in
Icechunk's repository metadata, describes the store as a whole: identity,
creator, publisher, site, receivers, references. Its fixed fields never
change; the others change only by amendment (`canvodpy store amend`, or
`amend_metadata`), with a reason. Every commit writes the **snapshot
summary** (coverage, counts, per-receiver position) into the root
attributes, with a copy of the repository metadata in standard form, and
records the **commit metadata** (software, environment, settings).
`read_metadata()` combines the three for one snapshot. Stores written
before keep their metadata in the root attribute `canvod_metadata`;
`canvodpy store migrate-metadata` moves them. Each section is described
below.

### 1. Identity & Discovery

Identifies the store and enables discovery in catalogs.

| Field | Type | Description | Standard |
|---|---|---|---|
| `id` | str | Store id `{site}-{gnss\|vod}` from the lowercase site name, e.g. `examplesite-gnss`; fixed | DataCite, STAC |
| `uuid` | str | Random UUID generated when the store is created; fixed | DataCite |
| `title` | str | Human-readable title | DataCite, ACDD, STAC |
| `description` | str? | Free-text description | ACDD, STAC |
| `store_type` | str | `gnss_store`, `vod_store`, etc. | DataCite (resourceType) |
| `source_format` | str | `rinex3`, `rinex2`, `sbf` | — |
| `keywords` | list[str] | Discovery keywords | ACDD, STAC |
| `conventions` | str | Metadata conventions followed (default `ACDD-1.3`) | ACDD |
| `naming_authority` | str | Your domain in reverse order, e.g. `at.ac.tuwien`; required when the store is created; fixed | ACDD |
| `stac_link` | str | Link from the store to its item in the STAC catalog, relative; fixed | STAC |
| `persistent_identifier` | str? | DOI or other persistent identifier | FAIR F1, DataCite |
| `standard_name_vocabulary` | str? | Vocabulary for standard_name attributes | ACDD |

### 2. Creator

The person or team who produced the data.

| Field | Type | Description | Standard |
|---|---|---|---|
| `name` | str | Full name | DataCite, ACDD |
| `email` | str | Contact email | ACDD |
| `orcid` | str? | ORCID identifier | DataCite |
| `type` | str | `Personal` or `Organizational` | DataCite |
| `institution` | str | Institution name | DataCite, ACDD |
| `institution_ror` | str? | ROR identifier | DataCite |
| `department` | str? | Department or faculty | — |
| `research_group` | str? | Research group name | — |
| `website` | str? | Lab/group URL | — |

### 3. Publisher & Rights

Licensing and publication info for repository deposits.

| Field | Type | Description | Standard |
|---|---|---|---|
| `name` | str? | Publisher name | DataCite |
| `type` | str | Publisher type (default `Institutional`) | DataCite |
| `url` | str? | Publisher URL | — |
| `license` | str? | SPDX license identifier, e.g. `CC-BY-4.0` | STAC |
| `license_uri` | str? | Full license URL | DataCite |

### 4. Temporal Extent

When the store was created and what time period the data covers.

| Field | Type | Description | Standard |
|---|---|---|---|
| `created` | str | Store creation timestamp (ISO 8601) | DataCite |
| `updated` | str | Last update timestamp (ISO 8601) | — |
| `collected_start` | str? | Earliest data epoch | ACDD |
| `collected_end` | str? | Latest data epoch | ACDD |
| `time_coverage_start` | str? | ACDD time_coverage_start | ACDD |
| `time_coverage_end` | str? | ACDD time_coverage_end | ACDD |
| `time_coverage_duration` | str? | ISO 8601 duration, e.g. `P1D` | ACDD |
| `time_coverage_resolution` | str? | ISO 8601 duration, e.g. `PT5S` | ACDD |

### 5. Spatial Extent & Site

Geographic location of the GNSS site.

| Field | Type | Description | Standard |
|---|---|---|---|
| `site.name` | str | Site name, e.g. `ExampleSite` | — |
| `site.description` | str? | Site description | — |
| `site.country` | str? | ISO 3166-1 alpha-2, e.g. `AT` | — |
| `geospatial_lat` | float? | WGS84 latitude (degrees) | ACDD |
| `geospatial_lon` | float? | WGS84 longitude (degrees) | ACDD |
| `geospatial_alt_m` | float? | Altitude in meters | — |
| `geospatial_lat_min/max` | float? | Latitude bounds | ACDD |
| `geospatial_lon_min/max` | float? | Longitude bounds | ACDD |
| `geospatial_vertical_crs` | str | Vertical CRS (default `EPSG:4979`) | — |
| `bbox` | list[float]? | STAC bounding box `[W, S, E, N]` | STAC |
| `extent_temporal_interval` | list? | STAC temporal interval | STAC |

### 6. Instruments & Receivers

GNSS equipment and per-receiver ingestion stats.

| Field | Type | Description | Standard |
|---|---|---|---|
| `platform` | str | Platform type (default `ground-based GNSS`) | ACDD |
| `instruments` | list[str] | Instrument names | ACDD |
| `receivers` | dict | Per-receiver info (see below) | — |

**Per receiver:**

| Field | Type | Description |
|---|---|---|
| `type` | str | `reference` or `canopy` |
| `directory` | str | Data subdirectory |
| `reader_format` | str | Reader format (default `auto`) |
| `description` | str? | Receiver description |
| `recipe` | str? | Naming recipe used |
| `epochs` | int? | Number of epochs ingested |
| `sids` | int? | Number of satellite IDs observed |
| `variables` | list[str]? | Variable names in the store group |
| `temporal_range` | list[str]? | `[start, end]` ISO timestamps |
| `cadences` | list[dict]? | Time ranges at one cadence, in time order: `start`, `end` (ISO), `cadence_s` |
| `metadata` | dict? | Freeform receiver metadata |

### 7. Software Provenance

Exact software stack used to create the store.

| Field | Type | Description | Standard |
|---|---|---|---|
| `software` | dict[str, str] | Package name → version | W3C PROV |
| `python` | str? | Python version + implementation | W3C PROV |
| `uv_version` | str? | `uv` package manager version | — |
| `level` | str | Processing level: `L1` (GNSS store) or `L2` (VOD store) | — |
| `lineage` | str? | Processing lineage description | W3C PROV |
| `facility` | str? | Hostname of the processing machine | W3C PROV |
| `datetime` | str? | Processing timestamp | W3C PROV |

Tracked packages: `canvodpy`, `canvod-readers`, `canvod-store`, `canvod-store-metadata`,
`canvod-utils`, `icechunk`, `zarr`, `xarray`, `dask`, `numpy`, `polars`, `pydantic`.

### 8. Environment

Hardware and runtime environment for reproducibility.

| Field | Type | Description |
|---|---|---|
| `hostname` | str? | Machine hostname |
| `os` | str? | OS platform string (e.g. `macOS-15.4-arm64-arm-64bit`) |
| `arch` | str? | CPU architecture (e.g. `arm64`) |
| `cpu_count` | int? | Number of CPU cores |
| `memory_gb` | float? | Total system RAM in GB |
| `disk_free_gb` | float? | Free disk at store path in GB |
| `dask_workers` | int? | Dask worker count used |
| `dask_threads_per_worker` | int? | Threads per Dask worker |
| `uv_lock_hash` | str? | SHA-256 of `uv.lock` for quick comparison |
| `pyproject_toml_text` | str? | **Raw monorepo `pyproject.toml`** (full text) |
| `uv_lock_text` | str? | **Raw monorepo `uv.lock`** (full text) |

The raw `pyproject.toml` and `uv.lock` are captured from the **monorepo root** (not
the individual package). This means you can recreate the exact virtual environment
that produced the store:

```bash
# Extract and recreate
from canvod.store_metadata.show import extract_env
extract_env(Path("/path/to/store"), Path("repro_env/"))

cd repro_env
uv sync --frozen  # exact same environment
```

### 9. Config Snapshot

Serialized processing configuration + integrity hash.

| Field | Type | Description |
|---|---|---|
| `processing` | dict? | Processing config section |
| `preprocessing` | dict? | Preprocessing config |
| `aux_data` | dict? | Auxiliary data config |
| `compression` | dict? | Compression settings |
| `icechunk` | dict? | Icechunk store config |
| `sids` | dict? | SID filtering/selection config |
| `config_hash` | str? | SHA-256 of serialized config (for quick comparison) |

### 10. References

Citations, funding, and related resources.

| Field | Type | Description | Standard |
|---|---|---|---|
| `software_repository` | str? | Source code URL | — |
| `documentation` | str? | Documentation URL | — |
| `access_url` | str? | URL where data is accessible (FAIR A1) | FAIR |
| `related_stores` | list[str] | IDs of related stores | DataCite |
| `publications` | list | DOI + citation pairs | DataCite |
| `funding` | list | Funder, ROR, grant number, award title | DataCite |

### 11. Summaries

Aggregate statistics about the store contents.

| Field | Type | Description |
|---|---|---|
| `total_epochs` | int? | Total number of time epochs |
| `total_sids` | int? | Total satellite IDs across all constellations |
| `constellations` | list[str]? | GNSS constellations present (G, R, E, C, ...) |
| `variables` | list[str]? | Data variable names |
| `temporal_resolution_s` | float? | The finest cadence of any day, in seconds |
| `file_count` | int? | Number of source files ingested |
| `store_size_mb` | float? | Store size on disk in MB |
| `history` | list[str] | Deprecated: only in snapshots from before the migration; the history of a store is its commit log |

### 12. VOD Analyses

The VOD analyses of a VOD store, by name; empty for a GNSS store.

| Field | Type | Description |
|---|---|---|
| `canopy_receiver` | str | Canopy receiver of the analysis |
| `reference_receiver` | str | Reference receiver of the analysis |

### 13. Amendments

One entry per changed amendable field.

| Field | Type | Description |
|---|---|---|
| `field` | str | The changed field, e.g. `creator.email` |
| `old` | any | Value before the amendment |
| `new` | any | Value after the amendment |
| `reason` | str | Why the field changed |
| `who` | str | Who changed it |
| `when` | str | When it changed (ISO 8601) |

### 14. Migration

Set only for a store written before the repository metadata and moved
with `canvodpy store migrate-metadata`.

| Field | Type | Description |
|---|---|---|
| `old_id` | str | The store id before the migration |
| `old_metadata_version` | str | Schema version of the old metadata |
| `who` | str | Who migrated the store |
| `when` | str | When it was migrated (ISO 8601) |
| `fields_given` | list[str] | Fields given at migration time |
| `variables_replaced` | list[str] | Arrays whose attributes the migration replaced |

---

## FAIR data principles

The schema is designed around the [FAIR principles](https://doi.org/10.1038/sdata.2016.18)
(Findable, Accessible, Interoperable, Reusable). The table below maps each
sub-principle to the fields and features that satisfy it:

| Principle | Requirement | How we satisfy it |
|---|---|---|
| **F1** | Globally unique persistent identifier | `identity.id` (local) + `identity.persistent_identifier` (DOI) |
| **F2** | Rich metadata | 14 sections |
| **F3** | Metadata includes data identifier | `identity.id` and `identity.uuid` are in the repository metadata and in the root copy of every snapshot |
| **F4** | Registered in searchable resource | `scan_stores()`, the STAC catalog (`write_catalog()`) |
| **A1** | Retrievable by standard protocol | Zarr/Icechunk (local, S3, HTTP); `references.access_url` |
| **A1.1** | Protocol is open and free | Zarr v3 + Icechunk — open specifications |
| **A1.2** | Protocol allows authentication | Icechunk supports S3/GCS credentials |
| **A2** | Metadata accessible if data gone | Repository metadata outlives every snapshot; the STAC catalog is plain JSON beside the stores |
| **I1** | Formal knowledge representation | JSON with Pydantic v2 schema |
| **I2** | FAIR-compliant vocabularies | ACDD conventions, SPDX licenses |
| **I3** | Qualified cross-references | `references.related_stores`, `references.publications` |
| **R1.1** | Clear data usage license | `publisher.license` (SPDX identifier) |
| **R1.2** | Detailed provenance | `processing` (software), `environment` (hardware), `config` (settings) |
| **R1.3** | Domain-relevant community standards | DataCite 4.5, ACDD 1.3, STAC 1.1 |

## Standards compliance

`validate_all(meta)` checks the metadata against these standards:

| Standard | What it checks |
|---|---|
| **zarr conventions** | The `proj`, `license` and `stac` attributes of the root group, with `zarr-cm` |
| **ACDD 1.3** | The global attributes of the root group: highly recommended ones are failures, recommended ones are listed as `[recommended]` |
| **DataCite** | Identifier, title, creator name and institution, creation date, store type, publisher |
| **STAC 1.1** | Collection fields: id, title, bbox, temporal interval, license; description is recommended |
| **FAIR** | Advice only: persistent ID, rich metadata, license, provenance, access URL, cross-references |

```python
failures = validate_all(meta, recommended=False)  # a new store has none
for standard, issues in validate_all(meta).items():
    print(f"{standard}: {'PASS' if not issues else f'{len(issues)} issues'}")
```

## STAC catalog

One STAC catalog at the data root describes every store under it (ADR
0015): one collection per product, one item per store.

```python
from canvod.store_metadata import build_catalog, store_item, write_catalog

item = store_item(store_path)  # one store's item (pystac.Item), in memory
catalog = build_catalog(data_root)  # the whole catalog (pystac.Catalog)
write_catalog(data_root)  # writes data_root/catalog.json and the rest
```

From the command line: `canvodpy stac write`. A store that can't be
described stops the write, and one error lists every such store. A new
store's catalog link has no item file until the first catalog write;
`validate_all(meta, store_path=store_path)` shows that as a warning, not a
failure.

A release is a named, fixed state of all stores: `create_release(data_root,
tag)` (or `canvodpy stac release TAG`) tags every store and writes the
catalog of that tag under `releases/<tag>/`, each store pinned to its
snapshot. A release catalog is never changed afterwards.

## Store inventory

Scan a directory tree for all Icechunk stores and list them in a Polars DataFrame:

```python
from pathlib import Path

from canvod.store_metadata import scan_stores

df = scan_stores(Path("/data/stores/"))
print(df)
# ┌────────────────────────┬────────────┬─────────────┬──────────────┐
# │ id                     ┆ store_type ┆ site        ┆ total_epochs │
# ╞════════════════════════╪════════════╪═════════════╪══════════════╡
# │ examplesite-gnss       ┆ gnss_store ┆ ExampleSite ┆ 86400        │
# │ examplesite-vod        ┆ vod_store  ┆ ExampleSite ┆ 86400        │
# └────────────────────────┴────────────┴─────────────┴──────────────┘
```

## Modules

| Module | Purpose |
|---|---|
| `schema.py` | Pydantic v2 models for all 14 sections |
| `collectors.py` | Pure functions that gather runtime info |
| `io.py` | Write a new store's metadata, read a snapshot's; `commit_with_rebase`, the one commit function |
| `snapshot.py` | What every commit writes: root copy, snapshot summary, commit metadata |
| `amend.py` | Amendments of amendable fields |
| `migration.py` | Moving stores from before ADR 0014 |
| `validate.py` | Compliance checking (DataCite, ACDD, STAC) |
| `inventory.py` | Directory scanning (`scan_stores`) |
| `catalog.py` | The STAC catalog at the data root |
| `show.py` | Human-readable formatting, env extraction, CLI |
