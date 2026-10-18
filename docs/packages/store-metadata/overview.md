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
`canvod`. A run with a lockfile the store doesn't hold yet stores it in a
commit of its own ("Store the lockfile in use") before its first data
commit, so the data commits of two runs never both write it. Two runs
that start with the same new lockfile store it once:

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
| `publisher` | `Publisher` | Name, URL, license (SPDX identifier or `other`), license URI | Repository metadata |
| `temporal` | `TemporalExtent` | Created; updated, first and last stored epoch, duration, resolution (the finest cadence of any day) | Created: repository metadata; the rest: snapshot summary |
| `spatial` | `SpatialExtent` | Site name, description and country, latitude, longitude, altitude (WGS84); bounding box | Site and position: repository metadata; bounding box: snapshot summary |
| `instruments` | `Instruments` | Platform; per receiver: type, directory, reader format, hardware, antenna; epochs, signals, variables, time range, cadence per time range, position | Receiver description: repository metadata; counts, time range, cadences, position: snapshot summary |
| `vod_analyses` | `VodAnalysisInfo` | Per VOD analysis of a VOD store: its canopy and reference receiver | Repository metadata |
| `references` | `References` | Repository, documentation, publications, funding | Repository metadata |
| `summaries` | `Summaries` | Number of epochs and signals, constellations, variables, number of files | Snapshot summary |
| `processing` | `ProcessingProvenance` | Versions of canvodpy and of the 11 `canvod-*` packages it installs, and of the main libraries (Icechunk, Zarr, xarray, Dask, NumPy, Polars, Pydantic); Python and uv versions; processing level; facility: the institution that processed the data (`processing.metadata.institution`) | Commit metadata |
| `environment` | `Environment` | Operating system, architecture, CPUs, memory, free disk space, the hash and text of `uv.lock`, and the text of `pyproject.toml` | Commit metadata |
| `config` | `ConfigSnapshot` | The processing, preprocessing, auxiliary data, compression, Icechunk, and signal settings, and their hash, without the settings of one computer (below) | Commit metadata |
| `amendments` | `Amendment` | Each amendment: field, old and new value, reason, who, when | Repository metadata |
| `migration` | `MigrationRecord` | For a migrated store: old id, who migrated it and when, fields given | Repository metadata |

Stores are shared, so they record nothing that belongs to one computer
or its user account. The recorded settings leave out the folders of the
computer that ran: `gnss_site_data_root`, `aux_data_dir`,
`shared_aux_cache_dir`, `log_dir`, and `stores_root_dir` when it is a
local folder (an `s3://` URL is kept). The same settings on two computers
therefore give the same hash. The content settings record who set them by
`processing.metadata.initials` (the author when no initials are set),
and no host name is recorded. Credentials are never recorded. Stores
written by canVODpy before 1.0.0 keep the folders, host name and
`user@host` they recorded: their snapshots can't be changed.

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
   disagree with the data it describes. A process rebuilds the summary
   from the whole store at its first commit to a store's branch; from
   then on it updates the summary from the log-book rows each commit
   adds, including rows another run committed in between, so a commit
   costs the same however many days the store holds (ADR 0021). It
   rebuilds the summary from the whole store again after a failed
   commit, when a group's log book was written anew (its columns
   changed, it shrank, or its last known row differs), and for a store
   with a group written by appending or a log book without row numbers.
   `summarize_store()` always reads the whole store. A commit that only gives days
   their block and writes no data keeps the summary of the snapshot
   before, with its time updated; it refuses any other change, compared
   with the snapshot it started from.
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
    orcid: "0000-0002-1825-0097"         # optional, ORCID's test person
    institution: "Example University"
    # institution_ror: "https://ror.org/<id>"  # optional
    department: "Department of Geodesy"     # optional
    license: "CC-BY-4.0"                 # required to create a store, SPDX identifier
    license_uri: null                    # the license text; required when license is "other"
    publisher: "Example University"      # required to create a store
    naming_authority: "org.example"      # required to create a store
    initials: "JD"                       # required to amend or migrate
```

DataCite requires the publisher and STAC requires the license, so a
store isn't created without them.

A first run, and `config validate`, refuse to start when a setting the
new store needs is missing (the site's store description, the publisher,
the license or the naming authority).

The license is an identifier from the [SPDX license list](https://spdx.org/licenses/)
(a copy of version 3.27.0 comes with the package), as STAC 1.1 asks. A
license outside SPDX is `other`, with `license_uri` naming its text.
Any other value is refused when a store is created or the license is
amended; the error names the field and points to the SPDX list.

The license is one of the metadata rules: rules that a standard sets for
a field. The models of the package check them when metadata is made,
so a store isn't created, and a field isn't amended, with a value that
breaks one. The error names the field, the value, and the rule.

| Field | Rule | Standard |
|---|---|---|
| `publisher.license` | SPDX identifier, or `other` with `license_uri` | SPDX, STAC 1.1 |
| `creator.orcid` | `0000-0000-0000-000X`, alone or after `https://orcid.org/`, with a valid check digit | ORCID |
| `creator.institution_ror` | Nine characters starting with `0`, alone or after `https://ror.org/` | ROR |
| `identity.persistent_identifier` | A DOI (`10.<registrant>/<suffix>`), when given as one: starting with `10.`, `doi:` or `https://doi.org/`; other identifiers aren't checked | DataCite |
| `creator.type`, `publisher.type` | `Personal`, `Organizational`, `Institutional`, or an ACDD type (`person`, `group`, `institution`, `position`) | DataCite, ACDD 1.3 |
| `identity.store_type` | `gnss_store`, `vod_store` or `geodesy_store` | canVODpy |
| `spatial.geospatial_lat`, `_lat_min`, `_lat_max` | -90 to 90 | WGS84 |
| `spatial.geospatial_lon`, `_lon_min`, `_lon_max` | -180 to 180 | WGS84 |
| `spatial.bbox` | Four values, W, S, E, N (STAC 1.1), with W <= E and S <= N (a site never spans the 180° meridian) | STAC 1.1, canvodpy |
| `temporal.time_coverage_duration`, `time_coverage_resolution` | ISO 8601 duration, such as `PT5S` | ACDD 1.3 |
| `publisher.license_uri`, `publisher.url`, `creator.website` | A URL starting with `http://` or `https://`, kept as written | |

The source format, the timestamps and the email address have no rule.
The source format of a GNSS store is the `source_format` of the reader that
read its files (`rinex3`, `rinex3_stripped`, `rinex2`, `sbf` or `nmea`), the
same value as the store's `source_format` root attribute.

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

[Stores on S3](../../guides/s3.md) covers choosing a provider,
credentials, access policies and the bucket settings to avoid. The
functions that read or write the metadata take a store location:
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
- `AWS_REGION`, and `AWS_ENDPOINT_URL` for storage that isn't AWS;
- `CANVOD_S3_PATH_STYLE=1` for a self-hosted S3 service, such as Ceph,
  that expects the bucket in the request path
  (`https://endpoint/bucket/...`) rather than in the host name
  (`https://bucket.endpoint/...`). Unset or `0` keeps the host name, as
  AWS expects.

Without a credential, opening fails with an error that names the
location and these sources.

Every function opens a store with `open_repository()`. Opening never
creates a store, so a mistyped location fails instead of leaving an
empty store behind. `store_exists()` says whether a location holds a
store, without opening it. With `expected_uuid=`, a store with another UUID is
refused, so a store replaced at the same location is never taken for
the old one.

`open_repository(location, create=True)` creates a store. Without a
`config=`, the new store gets the defaults of the `processing.icechunk`
settings, the same as a store a run creates, not Icechunk's own
defaults. Opening a store without a `config=` uses the configuration
Icechunk keeps with the store.

On a local directory, commits hold a lock file in the store's directory,
because Icechunk on a local file system can lose one of two concurrent
commits without an error. On S3 there is no lock: Icechunk's
conditional writes keep two commits from overwriting each other. The
S3 service must support them
([Conditional writes](../../guides/s3.md#conditional-writes)).

Two runs may also create one store at the same time. Only one of them
creates it: the commit that creates a store does not rebase, so the
second one fails. That run then waits up to a minute for the first
run's repository metadata and goes on with that store, as if it had
found it; its settings are checked against the store's content settings
like those of any later run.

Creating, opening, reading the metadata, and refusing a conflicting
commit are tested in CI against an S3 emulator.

Runs write stores on S3 when `processing.storage.stores_root_dir` is an
`s3://bucket/prefix` URL ([configuration guide](../../guides/configuration.md)).
The run history and the file index stay in the log folder of the machine
that runs. When the storage can't be reached, a run stops with an error
that names the location and the credential sources listed earlier, never the credentials.
The STAC catalog is written only for a local folder of stores so far.

## Check against the standards

```python
from canvod.store_metadata import validate_all

failures = validate_all(meta, recommended=False)
# {"rules": [], "zarr_conventions": [], "acdd": [], "datacite": [], "stac": [], "fair": []}

issues = validate_all(meta)  # also recommendations and FAIR advice
```

`validate_all()` returns a list of messages per standard.

A store written before a rule existed may hold a value that breaks it.
The store still opens: reading its metadata gives a
`MetadataRuleWarning` that names the field, `rules` lists it, and an
amendment of that field fixes it. An amendment of another field keeps
the old value and warns again. The durations, the bounding box, and the
latitude and longitude ranges are computed from the data; the next
commit to the store computes them again. With
`recommended=False` it lists only failures: what a standard requires, or
for ACDD 1.3 what it highly recommends. A store created by canVODpy has
none. Without it, the lists also hold the ACDD recommendations, marked
`[recommended]`, and the FAIR advice.

| Key | What is checked |
|---|---|
| `rules` | Fields that break a rule of their standard, such as a license outside SPDX |
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
like a new one. Fields it lacks are taken from the settings, as a new
store takes them: the site's `store_description`, the publisher and
license, the site's latitude and longitude. The command marks each one
`(from the settings)`. A field neither the store nor the settings hold is
given with `--set`; otherwise the migration is refused and lists it. A
value given with `--set` wins over the settings, and `--set FIELD=` with
no value is refused. A license
outside SPDX, or another value that breaks a metadata rule, is refused
too, naming the field to give, for example
`--set publisher.license=Apache-2.0`. A computed value that breaks a
rule, such as a duration, only warns: the migration computes it again. In a VOD
store, the attributes of `VOD` are replaced with the current ones, and
each VOD analysis the store holds a group of (`tau_omega/<analysis>`) is
listed, with its receivers from the settings (canVODpy 0.x listed none).
Snapshots from before the migration stay readable.

canVODpy 0.x stored epochs without recording their time scale. Every
stored epoch is GPS time now, and a write refuses a group whose epochs
don't record it (`epoch.attrs["time_system"]`). The migration records it
where it can tell:

- A GNSS group read from RINEX files (it holds the attribute
  `RINEX Version`) holds the epochs as the files give them, GPS time.
- A VOD group holds the epochs of the site's GNSS store: it's GPS time
  when every group of that store is.
- A GNSS group read from SBF or NMEA files holds UTC epochs, 18 s behind
  GPS time. The migration stops before it writes anything. The epochs
  aren't shifted, because the epoch grid and the satellite positions were
  computed for the old epochs: rebuild the store from the raw files.

Only the attribute changes; the epochs stay as stored. In Python,
`label_epoch_time_system()` from `canvod.store_metadata.migration` does
the same.

A GNSS store also gets its
[content settings](../../guides/configuration.md#content-settings-fixed-for-each-store)
(ADR 0019), the settings that shape its data, also when it was migrated
before: runs refuse a GNSS store without them. The command takes them
from the settings recorded in the store's first commit, and each
receiver's type and reader format from the repository metadata. A
setting that commit doesn't record is not guessed: the command stops and
lists it.

A setting the data show is read from the data instead, because canVODpy
0.x recorded settings its runs didn't follow:

- `processing.preprocessing` is none (`null`) when no group shows a
  preprocessing step. canVODpy 0.x recorded its preprocessing settings
  with every run, but `canvodpy run` never applied them.
- `store_radial_distance` is whether the GNSS groups hold `r`;
  `store_delta_snr` and `store_radial_diff` are whether the site's VOD
  groups hold `delta_snr` and `radial_diff` (canVODpy 0.x always wrote
  `delta_snr`). Groups that disagree make the command list the setting,
  to give with `--set`.

The `paired_canopies` of a reference receiver is never
recorded, so give it with the value the data was written with, by its
key in `canvod-settings.yaml`:

```bash
canvodpy store migrate-metadata ExampleSite --store gnss \
  --set sites.ExampleSite.receivers.reference_01.paired_canopies=[canopy_01]
```

In Python, `migrate_content_settings(store_path, who=..., values=...)`
from `canvod.store_metadata.migration` does the same.

A VOD store also gets its content settings (ADR 0019): the settings that
shape the VOD output (its chunks and compression, `store_delta_snr` and
`store_radial_diff`), plus `gnss_content_hash`, the content-settings hash
of the GNSS store it was computed from. The migration takes the D1 keys
from the store's first commit and `gnss_content_hash` from the site's
GNSS store where the settings put it now, or else where the settings
of the first commit name it, once the GNSS store has content settings. So
migrate the GNSS store first; otherwise the command lists
`gnss_content_hash` as missing, to give with
`--set gnss_content_hash=...`. The
calculator and its parameters of each group are recorded in the group's
attributes (ADR 0019 D2), not in the content settings.

## List the stores of a directory

```python
from pathlib import Path

from canvod.store_metadata import scan_stores

df = scan_stores(Path("/data/stores/"))
# Polars DataFrame, one row per store: id, title, store type, source format, site, ...
```

A store written before stores kept repository metadata gets
`needs_migration` in its row of `scan_stores()`, and `migrate_command`
gives the command that migrates it.

## Write the STAC catalog

The catalog describes every store under the data root
(`storage.stores_root_dir`) in [STAC](https://stacspec.org) 1.1, so that
STAC Browser, pystac and other STAC tools can find the data (ADR 0015).
It is written only when you ask for it:

```bash
canvodpy stac write              # the data root of the settings
canvodpy stac write --root /data/stores/
just stac-write
canvodpy run --site ExampleSite --write-catalog   # after the run's last commit
```

`canvodpy run --write-catalog` writes the catalog of the settings' data
root once every site of the run is processed. If the catalog is refused
(see below), the run's data stays committed and the run exits with code 1;
fix the stores it names, then run `canvodpy stac write`. A run without
the option, a dry run and a failed run write no catalog.

```python
from pathlib import Path

from canvod.store_metadata import write_catalog

write_catalog(Path("/data/stores/"))  # returns /data/stores/catalog.json
```

The catalog sits beside the stores, never inside one:

```text
/data/stores/
├── catalog.json
├── gnss-observations/
│   ├── collection.json
│   └── at.ac.tuwien.rosalia-gnss/at.ac.tuwien.rosalia-gnss.json
├── vod/
│   ├── collection.json
│   └── at.ac.tuwien.rosalia-vod/at.ac.tuwien.rosalia-vod.json
├── gnss-geodesy/                only with geodesy stores
└── Rosalia/
    ├── rinex/                   the GNSS store
    └── vod/                     the VOD store
```

There is one collection per product (`gnss-observations`, `vod`,
`gnss-geodesy`) and one item per store. The item id is the naming
authority and the store id, for example `at.ac.tuwien.rosalia-gnss`. The
items of one site (its GNSS, VOD and geodesy stores, same naming authority
and site name) link each other (`related`). A collection's extent covers
all its items: their points and their time ranges. If its items have
different licenses, the collection's license is `other`, with a link to
the text of each.
Every link is relative, so the whole data root can be copied or moved and
the catalog still works. The store's catalog link (`identity.stac_link`)
points at its item. A new store has the link before its item exists:
until the first catalog write, `validate_all(meta, store_path=...)` and
`just metadata-validate` show a warning for it, not a failure.

Each write replaces the catalog fully. It describes the stores under the
root at that moment: the item of a store that is gone is removed, and so
is the collection of a product with no store left. Only files the
previous write made are removed; any other file stays, and `releases/`
(see [Publish a release](#publish-a-release)) is never touched. Each file is replaced in one step, so nobody reads half
a file. If two writes run at once, the last one wins.

No store is left out silently. Every store under the root is read first.
If any of them can't be described, nothing is written, and one error
lists each such store with its reason:

```text
❌ No catalog was written: 2 store(s) under /data/stores cannot be described.
  Moria/rinex: needs migration to the current metadata form (ADR 0014): canvodpy store migrate-metadata Moria --store gnss
  Mordor/rinex: `publisher.license` 'Apache 2' is not an SPDX license identifier (see https://spdx.org/licenses/); a license outside SPDX is 'other' with license_uri; fix it with canvodpy store amend Mordor --store gnss
```

The reasons: the store can't be opened, has no metadata, needs
migration, has no site position, has no usable license (none, not
SPDX, or `other` without `license_uri`), or holds no data yet (no time
coverage: a run created the store and stopped before writing). `canvodpy stac write` then
exits with code 1.

An item has the site as a point (longitude, latitude, ellipsoidal height),
the time range of the data, the store's license, its UUID
(`canvod:uuid`), the site name (`canvod:site`) and the receivers with
their type and position (`canvod:receivers`). A license outside SPDX is
`other`, with a `license` link to its text (`license_uri`).

Each stored dataset is one asset. Asset keys join the parts of the group
path with a dot, because some tools read a `/` in a key as a path:

| Asset key | What it holds | Role |
|---|---|---|
| `canopy_01` | a receiver's observations (group `canopy_01`) | `data` |
| `canopy_01.sbf_obs` | its SBF metadata, if any (`canopy_01/metadata/sbf_obs`) | `metadata` |
| `canopy_01.log_book` | its log book (`canopy_01/metadata/table`) | `metadata` |
| `tau_omega_zeroth_order.canopy_01_vs_reference_01` | a VOD analysis | `data` |
| `tau_omega_zeroth_order.canopy_01_vs_reference_01.log_book` | its log book | `metadata` |

The group `canvod` (environments, kept by canvodpy) is no asset. A
receiver's asset carries the receiver's position as stored: the median of
its files' header positions, ECEF X, Y, Z in meters
(`canvod:position_ecef_m`). The assets of observations, of VOD analyses,
and of SBF metadata list their dimensions and variables (the STAC
`datacube` extension: `cube:dimensions`, `cube:variables`). A coordinate
that is no dimension, such as the satellite of each SID, is an
`auxiliary` variable.

An asset names everything needed to open it: the store (`href`), the
group (`xarray:open_kwargs`) and the snapshot it describes
(`canvod:snapshot_id`):

```python
import icechunk
import pystac
import xarray as xr

item = pystac.Item.from_file(
    "/data/stores/gnss-observations/at.ac.tuwien.rosalia-gnss/at.ac.tuwien.rosalia-gnss.json"
)
asset = item.assets["canopy_01"]
repo = icechunk.Repository.open(
    icechunk.local_filesystem_storage(asset.get_absolute_href())
)
session = repo.readonly_session(snapshot_id=asset.extra_fields["canvod:snapshot_id"])
ds = xr.open_dataset(session.store, **asset.extra_fields["xarray:open_kwargs"])
```

The media type of an asset is `application/vnd.zarr; version=3`, as the
STAC best practices for Zarr recommend. xpystac can't open these assets:
it opens Icechunk only from S3, and only the root group.

## Publish a release

A release is a version of the data that never changes. A paper or a
data publication can cite it. It tags `main` in every store under the data root with
the same Icechunk tag and writes the catalog of that tag under
`releases/<tag>/`:

```bash
canvodpy stac release v2026.1    # the data root of the settings
canvodpy stac release v2026.1 --root /data/stores/
just stac-release v2026.1
```

```python
from pathlib import Path

from canvod.store_metadata import create_release

create_release(Path("/data/stores/"), "v2026.1")
# returns /data/stores/releases/v2026.1/catalog.json
```

The release catalog has the same tree as the latest catalog, one folder
deeper:

```text
/data/stores/
├── catalog.json                 the latest catalog
└── releases/
    └── v2026.1/
        ├── catalog.json
        ├── gnss-observations/
        └── vod/
```

Each asset of a release names the tag (`canvod:tag`) and the snapshot the
tag points at (`canvod:snapshot_id`), and has no `latest-version` role:
that role tells the latest catalog's assets apart. Opening an asset by its
tag gives the released data, whatever was written to `main` since:

```python
session = repo.readonly_session(tag=asset.extra_fields["canvod:tag"])
```

A release refuses, before it tags anything:

- a tag with a `/`: those are canvod-store's own tags
  (`keep/<receiver>/<yyyydoy>`), and `releases/<tag>/` stays one folder
  deep;
- a store that can't be described, with the same error as
  `canvodpy stac write`;
- a tag that exists in some of the stores already, naming them;
- a tag whose release catalog exists: a release catalog is never changed.

If every store has the tag but `releases/<tag>/` is missing (the catalog
write failed after tagging), running the release again writes only the
catalog. Later catalog writes and later releases leave
`releases/` as it is. Release tags are written by this command only; don't create
or delete them by hand.
