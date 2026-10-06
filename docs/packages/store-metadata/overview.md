---
title: canvod-store-metadata
description: Store-level provenance, compliance validation, and inventory for Icechunk stores
---

# canvod-store-metadata

## Why store-level metadata?

GNSS-T VOD retrievals produce versioned Icechunk stores that may be shared,
published, or revisited years later. Without embedded provenance, critical
questions become unanswerable:

- **Reproducibility** — which software version, config, and ephemeris source
  produced this store? The `ProcessingProvenance` and `ConfigSnapshot` sections
  capture the full environment (down to Python version, uv lockfile hash, and
  worker configuration) so any store can be reproduced from scratch.
- **DOI registration** — TU Wien Repositum and Zenodo require DataCite 4.5
  metadata (creator, title, identifier, rights). Rather than filling these
  manually at publication time, canvodpy collects them automatically during
  ingestion.
- **Discovery** — STAC and ACDD metadata enable stores to be found by
  spatiotemporal queries, indexed in geospatial catalogs, and opened by tools
  that understand these conventions (e.g. `pystac`, `intake-stac`).
- **Audit trail** — the `Instruments` section records which receivers, file
  formats, and observation counts went into the store, linking the data product
  back to the physical hardware.

## Overview

`canvod-store-metadata` manages **store-level provenance** — the metadata that
describes an entire Icechunk store rather than individual files within it. It
captures who created the store, what software was used, which site and receivers
contributed data, what time period is covered, and whether the metadata meets
scientific data standards.

!!! info "Not to be confused with the file registry"

    The **file registry** (`{group}/metadata/table`) in `canvod-store` tracks
    individual ingested files (hash, filename, temporal range). Store metadata
    is a separate layer that describes the store as a whole — analogous to the
    difference between a library catalogue entry (store metadata) and the
    individual book records (file registry).

---

## Standards Compliance

Store metadata aligns with four established standards:

| Standard | Version | Purpose |
|----------|---------|---------|
| [DataCite](https://schema.datacite.org/) | 4.5 | Mandatory fields for DOI registration (TU Wien Repositum) |
| [ACDD](https://wiki.esipfed.org/Attribute_Convention_for_Data_Discovery) | 1.3 | Attribute Convention for Data Discovery in NetCDF/Zarr |
| [STAC](https://stacspec.org/) | 1.1 | SpatioTemporal Asset Catalog for geospatial data |
| [W3C PROV](https://www.w3.org/TR/prov-overview/) | — | Provenance model (software, environment, lineage) |

---

## Metadata Schema (11 Sections)

The root `StoreMetadata` model composes 11 section models, each a Pydantic
`BaseModel`, plus a `metadata_version` for the schema:

| Section | Model | Fields | What it captures |
|---------|-------|--------|-----------------|
| 1. Identity & Discovery | `StoreIdentity` | id, title, description, store_type, source_format, keywords, conventions | Unique identification and search |
| 2. Creator | `Creator` | name, email, orcid, institution, institution_ror, department | Who created the store |
| 3. Publisher & Rights | `Publisher` | name, url, license (SPDX), license_uri | Data access rights |
| 4. Temporal Extent | `TemporalExtent` | created, updated, collected_start/end, duration, resolution | Time coverage |
| 5. Spatial Extent & Site | `SpatialExtent` | site name/country, lat/lon/alt (WGS84), bounding box | Geographic coverage |
| 6. Instruments | `Instruments` | platform, per-receiver: type, directory, format, epochs, SIDs | Hardware provenance |
| 7. Software Provenance | `ProcessingProvenance` | software versions, Python, uv, processing level, lineage | Software environment |
| 8. Environment | `Environment` | hostname, OS, arch, CPU count, memory, disk, worker config | Compute environment |
| 9. Config Snapshot | `ConfigSnapshot` | processing params, preprocessing, compression, config hash | Reproducibility |
| 10. References | `References` | repository, documentation, publications, funding | Related resources |
| 11. Summaries | `Summaries` | total_epochs, total_sids, constellations, variables, history | Aggregate statistics |

---

## API

### Collecting and writing metadata

```python
from canvod.store_metadata import collect_metadata, write_metadata

# Collect metadata from the current environment and config
metadata = collect_metadata(
    config=config,
    site_name="ExampleSite",
    site_config=site_config,
    store_type="gnss_store",
    source_format="rinex3",
    store_path=store_path,
)

# Write to the Icechunk store root attributes
write_metadata(store_path, metadata)
```

### Reading and checking metadata

```python
from canvod.store_metadata import read_metadata, metadata_exists

if metadata_exists(store_path):
    meta = read_metadata(store_path)
    print(meta.identity.title)
    print(meta.creator.name)
    print(meta.temporal.collected_start)
```

### Updating metadata (incremental)

```python
from canvod.store_metadata import update_metadata

# After ingesting new data, update timestamps and summaries
update_metadata(store_path, {
    "temporal.updated": "2026-03-09T12:00:00Z",
    "temporal.collected_end": "2025-01-31T23:59:55",
})
```

### Validation

```python
from canvod.store_metadata import validate_all, validate_datacite, validate_fair

# Check compliance against all standards
results = validate_all(metadata)
# → {"datacite": [...issues...], "acdd": [...], "stac": [...], "fair": [...]}

# Check DataCite mandatory fields only
issues = validate_datacite(metadata)

# Check FAIR principles
issues = validate_fair(metadata)
```

### Inventory: scanning multiple stores

```python
from canvod.store_metadata import scan_stores

# Walk a directory tree, find all Icechunk stores, read their metadata
df = scan_stores(root_dir=Path("/data/stores/"))
# → Polars DataFrame with one row per store:
#   id, title, store_type, source_format, site, creator, time_start, time_end, ...
```

### STAC catalog export

```python
from canvod.store_metadata import scan_stores_as_stac, write_stac_catalog

# Generate a STAC Catalog JSON
stac = scan_stores_as_stac(root_dir=Path("/data/stores/"))

# Write catalog.json (default: root_dir / "catalog.json") and a
# collection.json next to each store
write_stac_catalog(Path("/data/stores/"), output_path=Path("/data/stac/catalog.json"))
```

### Display

```python
from canvod.store_metadata import show_metadata, format_metadata

# Pretty-print metadata to the terminal
show_metadata(store_path)

# Get formatted string for embedding in reports
text = format_metadata(metadata)
```

---

## Storage Location

Metadata is stored as a JSON-serializable dictionary in the Zarr store's **root
attributes** under the key `canvod_metadata`, on branch `main`:

```
store_root/                    ← root attributes: {"canvod_metadata": {...}}
├── canopy_01/
│   ├── SNR
│   ├── metadata/
│   │   ├── table/             ← file registry (canvod-store)
│   │   └── sbf_obs/           ← SBF receivers only (canvod-store)
│   └── ...
└── reference_01_canopy_01/    ← a reference, stored once per paired canopy
    └── ...
```

---

## Orchestrator Integration

Runs write the metadata of both stores themselves, after each day written
to the GNSS store and after each VOD write:

1. **First write** to a store: `collect_metadata()` gathers all 11 sections,
   `summarize_store()` adds the coverage and summaries of the stored data,
   `write_metadata()` persists them, with the first history line of the write.
2. **Every later write**: `update_metadata()` sets `temporal.updated`, adds a
   line to `summaries.history`, recomputes coverage and summaries from the
   stored data, and replaces the config snapshot if the settings changed
   (noted in the history with the old and new config hash).

Each history line of a write names what was written, the canVODpy version and
the preprocessing of every group written, e.g.
`2026-10-05T12:00:00+00:00: Ingest 2025003: canopy_01(written=96) (canvodpy 1.0.0); preprocessing: canopy_01: temporal_aggregate(freq=1min, method=mean, integer_method=first)`.
The full record of each file is in the group's log book (see
[the preprocessing record](../ops/overview.md#the-preprocessing-record)).

No user action is required: every run (`canvodpy run`, `Site.pipeline()`,
Airflow) goes through this code. A failed metadata write does not stop the
run and is logged as a warning. The data of that write is committed
anyway (the metadata goes in a separate commit), so after such a warning
the metadata no longer describes all of the stored data.

---

## Configuration

Store metadata draws from two config sections:

### `canvod-settings.yaml` — Creator and publisher (`processing.metadata:`)

```yaml
processing:
  metadata:
    author: "Nicolas Bader"
    email: "support@canvodpy.eu"
    orcid: "0000-0002-1234-5678"          # optional
    institution: "TU Wien"
    institution_ror: "https://ror.org/04d836q62"  # optional
    department: "Geodesy and Geoinformation"
    license: "Apache-2.0"                 # SPDX identifier
    publisher: "TU Wien"
    naming_authority: "at.ac.tuwien.geo"
```

### `canvod-settings.yaml` — Spatial extent (`sites.<name>:`)

```yaml
sites:
  ExampleSite:
    description: "ExampleSite GNSS-T research site"
    country: "Austria"
    latitude: 47.702
    longitude: 16.299
    altitude_m: 575.0
    receivers:
      canopy_01:
        # ...
```

---

!!! example "Try it"
    [09 — Store Metadata](../../notebooks/_build/09_store_metadata.html){target=_blank}
    · [view source on molab](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/09_store_metadata.py)
