---
title: canvod-store-metadata
description: The metadata that describes a whole store, how runs write it, and how to read, check, and catalog it.
---

# canvod-store-metadata

`canvod-store-metadata` keeps the metadata that describes a whole store:
who created it, with which software and settings, for which site and
receivers, and which period it covers. Runs write it to both stores of a
site. You can read it, check it for missing fields, and list the stores of
a directory with it.

!!! info "Store metadata and the log book"
    The log book of a group (`{group}/metadata/table`, in `canvod-store`)
    has one row per stored file. The store metadata describes the store as
    a whole.

## Where it's stored

The metadata is a JSON object in the root attributes of the store, under
the key `canvod_metadata`, on the branch `main`:

```text
store_root/                    # root attributes: {"canvod_metadata": {...}}
├── canopy_01/
│   ├── SNR
│   ├── ...
│   └── metadata/
│       ├── table              # log book (canvod-store)
│       └── sbf_obs            # SBF receivers only (canvod-store)
└── reference_01_canopy_01/
    └── ...
```

## Sections

The `StoreMetadata` model has a `metadata_version` and 11 sections:

| Section | Model | Content |
|---|---|---|
| `identity` | `StoreIdentity` | ID, title, description, store type, source format, keywords, conventions |
| `creator` | `Creator` | Name, email, ORCID, institution and its ROR ID, department |
| `publisher` | `Publisher` | Name, URL, license (SPDX identifier), license URI |
| `temporal` | `TemporalExtent` | Created, updated, first and last stored epoch, duration, resolution |
| `spatial` | `SpatialExtent` | Site name and country, latitude, longitude, altitude (WGS84), bounding box |
| `instruments` | `Instruments` | Platform; per receiver: type, directory, reader format, epochs, signals, variables |
| `processing` | `ProcessingProvenance` | Versions of canvodpy and of the 11 `canvod-*` packages it installs, and of the main libraries (Icechunk, Zarr, xarray, Dask, NumPy, Polars, Pydantic); Python and uv versions; processing level; lineage |
| `environment` | `Environment` | Host name, operating system, architecture, CPUs, memory, free disk space, the hash and text of `uv.lock`, and the text of `pyproject.toml` |
| `config` | `ConfigSnapshot` | The processing, preprocessing, auxiliary data, compression, Icechunk, and signal settings, and their hash |
| `references` | `References` | Repository, documentation, publications, funding |
| `summaries` | `Summaries` | Number of epochs and signals, constellations, variables, number of files, store size, history |

The field names follow three metadata standards: the DataCite Metadata Schema 4.5, the
Attribute Convention for Data Discovery (ACDD) 1.3, and the SpatioTemporal
Asset Catalog (STAC) 1.1.

## How runs write it

Every run (`canvodpy run`, `Site.pipeline()`, or Airflow) writes the
metadata of both stores itself, after each day written to the GNSS store
and after each VOD write:

1. At the first write to a store, `collect_metadata()` collects all 11
   sections from the settings and the environment, `summarize_store()`
   adds the coverage and summaries of the stored data, and
   `write_metadata()` writes them, with the first history line.
1. At every later write, `update_metadata()` sets `temporal.updated` and
   adds a line to `summaries.history`. It computes the coverage and
   summaries again from the stored data and replaces the settings snapshot
   if the settings changed. The history line then names the old and new hash of
   the settings.

A history line names what was written, the canVODpy version, and the
preprocessing of each group written, for example:

```text
2026-10-05T12:00:00+00:00: Ingest 2025003: canopy_01(written=96) (canvodpy 1.0.0); preprocessing: canopy_01: temporal_aggregate(freq=1min, method=mean, integer_method=first)
```

The full record of each file is in the group's log book (see
[The preprocessing record](../ops/overview.md#the-preprocessing-record)).

A failed metadata write stops the run with an error. By then, the data of
that write is committed (the metadata goes in a separate commit), so the
error says that the metadata no longer describes all of the stored data.
The next successful write computes coverage and summaries again from the
stored data.

## Settings

The metadata comes from two parts of `canvod-settings.yaml`.

The creator and publisher come from `processing.metadata`:

```yaml
processing:
  metadata:
    author: "Jane Doe"
    email: "jane.doe@example.org"
    orcid: "0000-0000-0000-0000"         # optional
    institution: "Example University"
    institution_ror: "https://ror.org/..."  # optional
    department: "Department of Geodesy"     # optional
    license: "CC-BY-4.0"                 # optional, SPDX identifier
    publisher: "Example University"      # optional
    naming_authority: "org.example"      # optional
```

The site description and location come from the site:

```yaml
sites:
  ExampleSite:
    description: "Example GNSS-T research site"
    country: "AT"            # ISO 3166-1 code
    latitude: 47.70
    longitude: 16.30
    altitude_m: 575.0
    receivers:
      canopy_01:
        # ...
```

For every setting, see [Configuration](../../guides/configuration.md).

## Read the metadata

```python
from canvod.store_metadata import metadata_exists, read_metadata, show_metadata

if metadata_exists(store_path):
    meta = read_metadata(store_path)
    print(meta.identity.title)
    print(meta.temporal.collected_start)

show_metadata(store_path)  # print all sections
```

`format_metadata(meta)` returns the same text as a string.

To recreate the Python environment that wrote a store, `extract_env()`
writes the stored `pyproject.toml` and `uv.lock` to a directory.

## Check for missing fields

```python
from canvod.store_metadata import validate_all, validate_datacite, validate_fair

issues = validate_all(meta)
# {"fair": [...], "datacite": [...], "acdd": [...], "stac": [...]}

issues = validate_datacite(meta)
```

Each function returns the fields that are missing or empty, as a list of
messages. The functions check the fields of `StoreMetadata`; they don't
validate the metadata against the full schema of each standard.

## Change the metadata

`update_metadata()` changes fields, addressed by dotted keys, and commits
the change:

```python
from canvod.store_metadata import update_metadata

update_metadata(
    store_path,
    {"identity.description": "GNSS-T observations of the Example site, 2025"},
)
```

Runs set the coverage, summaries, and history themselves; change those
only through a run.

## List the stores of a directory

```python
from pathlib import Path

from canvod.store_metadata import scan_stores, write_stac_catalog

df = scan_stores(Path("/data/stores/"))
# Polars DataFrame, one row per store: id, title, store type, source format, site, ...

write_stac_catalog(Path("/data/stores/"), output_path=Path("/data/stac/catalog.json"))
```

`write_stac_catalog()` writes a STAC catalog (by default
`<root_dir>/catalog.json`) and a STAC collection next to each store.
`scan_stores_as_stac()` returns the catalog as a dictionary without writing
it.
