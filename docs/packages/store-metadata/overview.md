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

A store's metadata has three parts (ADR 0014), each kept where Icechunk
keeps that kind of information:

| Part | Where | What it holds | Changes |
|---|---|---|---|
| **Repository metadata** | Icechunk's repository metadata: on no branch, in no snapshot | What describes the store as a whole: identity, creator, publisher and license, site and position, receivers or VOD analyses, references | Fixed fields never; amendable fields only by amendment |
| **Snapshot summary** | Root attributes of each snapshot | What the snapshot holds: time coverage, per-receiver epochs, signals, variables, time range and position, constellations | Written by every commit, from the data of that commit |
| **Commit metadata** | Icechunk's metadata of each commit | How the commit was made: software versions, environment, settings and their hash, hash of `uv.lock` | Written by every commit |

Every commit also writes a copy of the repository metadata into the root
attributes, in standard form: flat CF and ACDD global attributes, the
Zarr conventions for `proj`, `license` and `stac`, and the lossless copy
under `canvod:repository_metadata`. So each snapshot shows its store as
it was when it was committed, and tools that read only the root group,
such as xarray, see it too. The `uv.lock` and `pyproject.toml` are those
of the project the run starts in: the nearest directory, from the working
directory up, that holds both. A run outside such a project records
neither. Their text is stored once per hash, in the reserved group
`canvod`:

```text
store_root/                    # root attributes: root copy and snapshot summary
├── canvod/
│   └── environments/
│       └── <uv.lock hash>/    # uv_lock, pyproject_toml (text as bytes)
├── canopy_01/
│   ├── SNR
│   ├── ...
│   └── metadata/
│       ├── table              # log book (canvod-store)
│       └── sbf_obs            # SBF receivers only (canvod-store)
└── reference_01_canopy_01/
    └── ...
```

The **fixed fields** say which store this is: the store id, UUID, store
type, source format, naming authority, catalog link, and creation date.
The store id is `{site}-{gnss|vod}`, from the site name in lowercase.
Every other field of the repository metadata is **amendable**.

## Sections

`read_metadata()` combines the three parts of one snapshot into one
`StoreMetadata`, with a `metadata_version` and these sections:

| Section | Model | Content | Part |
|---|---|---|---|
| `identity` | `StoreIdentity` | ID, UUID, naming authority, catalog link, title, description, store type, source format, keywords | Repository metadata |
| `creator` | `Creator` | Name, email, ORCID, institution and its ROR ID, department, research group, website | Repository metadata |
| `publisher` | `Publisher` | Name, URL, license (SPDX identifier), license URI | Repository metadata |
| `temporal` | `TemporalExtent` | Created; updated, first and last stored epoch, duration, resolution | Created: repository metadata; the rest: snapshot summary |
| `spatial` | `SpatialExtent` | Site name, description and country, latitude, longitude, altitude (WGS84); bounding box | Site and position: repository metadata; bounding box: snapshot summary |
| `instruments` | `Instruments` | Platform; per receiver: type, directory, reader format, hardware, antenna; epochs, signals, variables, time range, position | Receiver description: repository metadata; counts, time range, position: snapshot summary |
| `vod_analyses` | `VodAnalysisInfo` | Per VOD analysis of a VOD store: its canopy and reference receiver | Repository metadata |
| `references` | `References` | Repository, documentation, publications, funding | Repository metadata |
| `summaries` | `Summaries` | Number of epochs and signals, constellations, variables, number of files | Snapshot summary |
| `processing` | `ProcessingProvenance` | Versions of canvodpy and of the 11 `canvod-*` packages it installs, and of the main libraries (Icechunk, Zarr, xarray, Dask, NumPy, Polars, Pydantic); Python and uv versions; processing level | Commit metadata |
| `environment` | `Environment` | Host name, operating system, architecture, CPUs, memory, free disk space, the hash and text of `uv.lock`, and the text of `pyproject.toml` | Commit metadata |
| `config` | `ConfigSnapshot` | The processing, preprocessing, auxiliary data, compression, Icechunk, and signal settings, and their hash | Commit metadata |
| `amendments` | `Amendment` | Each amendment: field, old and new value, reason, who, when | Repository metadata |
| `migration` | `MigrationRecord` | For a migrated store: old id, who migrated it and when, fields given | Repository metadata |

The field names follow three metadata standards: the DataCite Metadata Schema 4.5, the
Attribute Convention for Data Discovery (ACDD) 1.3, and the SpatioTemporal
Asset Catalog (STAC) 1.1.

## How runs write it

Every run writes the metadata itself, whether it starts from the command
line (`canvodpy run`), from Python (`Site.pipeline()`, `site.vod`,
`FluentWorkflow.to_store()`, the write methods of `GnssResearchSite`) or
from Airflow. All of them take the same step, `ensure_store_metadata()`,
before they write data:

1. Before the first write to a store, `collect_metadata()` builds the
   repository metadata from the settings, and `write_metadata()` writes
   it. A store never holds data without its metadata: a commit to a
   store without repository metadata is refused, and nothing is
   committed. Code that writes to a store directly, without a run, gives
   it its metadata first.
1. Every commit, of a run or of any other canVODpy command, writes the
   root copy and the snapshot summary in the same commit as the data,
   and records the commit metadata. The snapshot summary therefore can't
   disagree with the data it describes.
1. A run that writes a receiver (GNSS store) or a VOD analysis (VOD
   store) that the repository metadata doesn't list is refused. The
   error names the `canvodpy store amend` command that adds it.
   `FluentWorkflow.to_store()` writes VOD to the VOD analysis of the
   settings that pairs the receivers of its `.vod()` step, and refuses a
   pair without one.

A failed metadata write fails the commit, and the run stops with an
error. A commit whose root group differs from the repository metadata,
for example after an edit by hand, is refused.

The history of a store is its commit log. `show_metadata()` lists it,
and `canvodpy store log SITE` draws it as a graph. Each commit records
its settings, so the preprocessing of a write can be read from its
commit. The full record of each file is in the group's log book (see
[The preprocessing record](../ops/overview.md#the-preprocessing-record)).

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
    license: "CC-BY-4.0"                 # required to create a store, SPDX identifier
    publisher: "Example University"      # required to create a store
    naming_authority: "org.example"      # required to create a store
    initials: "JD"                       # required to amend or migrate
```

DataCite requires the publisher and STAC requires the license, so a
store isn't created without them.

The description of the site's stores, the site description, and the
location come from the site:

```yaml
sites:
  ExampleSite:
    store_description: "GNSS-T observations below a beech canopy"  # required to create a store
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

`read_metadata()` reads the tip of `main`; `branch=` reads another
branch, and `snapshot_id=` reads one snapshot as it was when it was
committed. `format_metadata(meta)` returns the text of `show_metadata()`
as a string.

To recreate the Python environment that wrote a store, `extract_env()`
writes the stored `pyproject.toml` and `uv.lock` to a directory.

## Stores on S3

The functions that read or write the metadata take a store location:
a local directory, or an `s3://bucket/prefix` URL. A URL without a
bucket or a prefix is refused, and so are other schemes such as `gs://`.

```python
from canvod.store_metadata import read_metadata, show_metadata

meta = read_metadata("s3://example-bucket/stores/ExampleSite/gnss")
show_metadata("s3://example-bucket/stores/ExampleSite/gnss")
```

Credentials, region and endpoint come only from the environment or the
shared AWS files, never from the settings or the store metadata:

- `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`, or `AWS_PROFILE`;
- `~/.aws/credentials` and `~/.aws/config`;
- `AWS_REGION`, and `AWS_ENDPOINT_URL` for storage that isn't AWS.

Without a credential, opening fails with an error that names the
location and these sources.

Every function opens a store with `open_repository()`. Opening never
creates a store, so a mistyped location fails instead of leaving an
empty store behind. With `expected_uuid=`, a store with another UUID is
refused, so a store replaced at the same location is never taken for
the old one.

On a local directory, commits hold a lock file in the store's directory,
because Icechunk on a local file system can lose one of two concurrent
commits without an error. On S3 there is no lock: Icechunk's
conditional writes keep two commits from overwriting each other.

Processing still writes stores to local directories only.

## Check against the standards

```python
from canvod.store_metadata import validate_all

failures = validate_all(meta, recommended=False)
# {"zarr_conventions": [], "acdd": [], "datacite": [], "stac": [], "fair": []}

issues = validate_all(meta)  # also recommendations and FAIR advice
```

`validate_all()` returns a list of messages per standard. With
`recommended=False` it lists only failures: what a standard requires, or
for ACDD 1.3 what it highly recommends. A store created by canVODpy has
none. Without it, the lists also hold the ACDD recommendations, marked
`[recommended]`, and the FAIR advice.

| Key | What is checked |
|---|---|
| `zarr_conventions` | The `proj`, `license` and `stac` attributes of the root group, with `zarr-cm` |
| `acdd` | The ACDD 1.3 global attributes of the root group |
| `datacite` | Identifier, title, creator, creation date, store type, publisher |
| `stac` | Identifier, title, bounding box, time range, license |
| `fair` | Advice only: persistent identifier, access URL, cross-references, provenance |

The tests also check a day of data exported to netCDF with IOOS
compliance-checker, for CF 1.11 and ACDD 1.3. Three of its findings are
known and accepted. CF has no standard names for GNSS observables,
UDUNITS has no unit for dB or dB-Hz, and the grid cell ids
(`cell_id_*`) have no units because they are indices.

## Change the description: amendments

Amendable fields change only by amendment, with a reason:

```bash
canvodpy store amend ExampleSite --store gnss \
  --set identity.title="Example site GNSS-T observations" \
  --reason "Clearer title"
```

The command shows the changes and asks before it writes them. Each
changed field is recorded with its old and new value, the reason, who
(the initials in `processing.metadata.initials`), and when. A new commit
carries the new description. Snapshots from before keep the description
they were written with; `show_metadata()` lists the amendments made
since. A fixed field is refused: a different id or creation date means a
different store.

`--add-receiver NAME` adds a receiver of the site's settings to a GNSS
store, and `--add-vod-analysis NAME` adds a VOD analysis to a VOD store,
so runs may write them. `--from FILE` reads the changes from a YAML
file. In Python, `amend_metadata()` does the same.

Runs set the snapshot summary and the commit metadata themselves; they
are never amended.

## Move an older store to the current form

A store written before the repository metadata keeps its metadata in one
root attribute. Runs refuse such a store, and the error names the
command that moves it:

```bash
canvodpy store migrate-metadata ExampleSite --store gnss \
  --set identity.description="GNSS-T observations below a beech canopy"
```

The migration writes the repository metadata, gives the store its new id
and a UUID, and keeps the old id in the migration record, with who
migrated it and when. A migrated store must pass the standards checks
like a new one. Fields it lacks, such as its description, are given with
`--set`; otherwise the migration is refused and lists them. In a VOD
store, the attributes of `VOD` are replaced with the current ones.
Snapshots from before the migration stay readable.

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

A store written before stores kept repository metadata gets
`needs_migration` in its row of `scan_stores()`, and `migrate_command`
gives the command that migrates it. The catalog functions refuse a
directory with such a store, or with a store that has no metadata at all,
and name each one: a catalog lists every store or none.
