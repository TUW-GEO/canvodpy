---
title: Command line
description: Every canvodpy command and option, with the text of its --help.
---

<!-- Written by scripts/cli_docs.py from the canvodpy --help texts.
     Don't edit this page: change the help texts and run `just cli-docs`. -->

# Command line

The `canvodpy` command runs canVODpy from the command line. This page
lists every command and option, and `canvodpy COMMAND --help` prints the same
text in the terminal. For a walk through a first run, see
[Retrieve VOD](../users/index.md).

Process GNSS observations into VOD and inspect the stores.

**Usage**:

```console
$ canvodpy [OPTIONS] COMMAND [ARGS]...
```

**Options**:

* `--version`: Show canvodpy's version and exit.
* `--install-completion`: Install completion for the current shell.
* `--show-completion`: Show completion for the current shell, to copy it or customize the installation.
* `--help`: Show this message and exit.

**Commands**:

* `run`: Process GNSS observations into Icechunk...
* `vod`: Compute VOD for a range of dates from the...
* `vod-reconcile`: List the dates that have observations but...
* `doctor`: Report canvodpy's version, its...
* `dashboard`: Launch the marimo performance dashboard...
* `config`: Create, check, show, and edit...
* `store`: Inspect the Icechunk stores of the sites...
* `stac`: Write the STAC catalog of every store...

## `canvodpy run`

Process GNSS observations into Icechunk stores and compute VOD.

**Usage**:

```console
$ canvodpy run [OPTIONS]
```

**Options**:

* `--site <str>`: Site name, as defined under sites: in canvod-settings.yaml, for example ExampleSite. Repeat the option for several sites, which run one after the other.  [required]
* `--start <str>`: Start date in YYYYDOY format, for example 2025001. If omitted, resumes from the last processed date in the store.
* `--end <str>`: End date in YYYYDOY format, for example 2025007. If omitted, processes up to today.
* `--no-vod / --vod`: Skip the VOD calculation: only write the observations to the GNSS store.  [default: vod]
* `--dry-run / --no-dry-run`: Preview processing plan without executing.  [default: no-dry-run]
* `--workers <int>`: Number of worker processes. Default: from the resource settings in canvod-settings.yaml.
* `--days-per-batch <int>`: Number of days that the workers process together. Default: processing.params.days_per_batch in canvod-settings.yaml.
* `-c, --config-dir <path>`: Configuration directory, holding canvod-settings.yaml and recipes/. Default: $CANVOD_CONFIG_DIR, else config/ of the canvodpy checkout, else ~/.config/canvodpy.
* `--config <str>`: Settings file whose values replace those of canvod-settings.yaml.
* `--ephemeris-source <final|broadcast>`: Where the satellite orbits and clocks come from: final uses the SP3 and CLK products of an analysis center, broadcast uses the SatVisibility blocks of the SBF files. Default: from canvod-settings.yaml.
* `--vod-calculator <tau_omega>`: VOD calculator to use.  [default: tau_omega]
* `--write-catalog`: After the run, write the latest STAC catalog of every store under the data root, as `canvodpy stac write` does.
* `--dashboard`: Start the marimo performance dashboard next to this run, in a process of its own. Its startup messages go to a log file, not to this terminal.
* `--dashboard-host <str>`: Host for --dashboard to bind to.  [default: 127.0.0.1]
* `--dashboard-port <int>`: Port for --dashboard to bind to. Default: a free port that the operating system picks.
* `--help`: Show this message and exit.

## `canvodpy vod`

Compute VOD for a range of dates from the GNSS store of a site.

**Usage**:

```console
$ canvodpy vod [OPTIONS]
```

**Options**:

* `--site <str>`: Site name, as defined under sites: in canvod-settings.yaml  [required]
* `--analysis <str>`: VOD analysis name, as defined in site.vod_analyses  [required]
* `--start <str>`: Start date in YYYYDOY format, for example 2025001.
* `--end <str>`: End date in YYYYDOY format, for example 2025007.
* `--calculator <tau_omega>`: VOD calculator to use.  [default: tau_omega]
* `-c, --config-dir <path>`: Configuration directory, holding canvod-settings.yaml and recipes/. Default: $CANVOD_CONFIG_DIR, else config/ of the canvodpy checkout, else ~/.config/canvodpy.
* `--help`: Show this message and exit.

## `canvodpy vod-reconcile`

List the dates that have observations but no VOD, and compute it with --execute.

**Usage**:

```console
$ canvodpy vod-reconcile [OPTIONS]
```

**Options**:

* `--site <str>`: Site name, as defined under sites: in canvod-settings.yaml  [required]
* `--analysis <str>`: VOD analysis name, as defined in site.vod_analyses  [required]
* `--calculator <tau_omega>`: VOD calculator to use.  [default: tau_omega]
* `--execute`: Compute the VOD of the dates found. Without this flag, the command only reports them.
* `-c, --config-dir <path>`: Configuration directory, holding canvod-settings.yaml and recipes/. Default: $CANVOD_CONFIG_DIR, else config/ of the canvodpy checkout, else ~/.config/canvodpy.
* `--help`: Show this message and exit.

## `canvodpy doctor`

Report canvodpy's version, its environment, and its configuration directory.

**Usage**:

```console
$ canvodpy doctor [OPTIONS]
```

**Options**:

* `-c, --config-dir <path>`: Configuration directory, holding canvod-settings.yaml and recipes/. Default: $CANVOD_CONFIG_DIR, else config/ of the canvodpy checkout, else ~/.config/canvodpy.
* `--help`: Show this message and exit.

## `canvodpy dashboard`

Launch the marimo performance dashboard for the pipeline's logs.

**Usage**:

```console
$ canvodpy dashboard [OPTIONS]
```

**Options**:

* `--logs-dir <str>`: Log folder of the runs to show. Default: processing.logging.log_dir in canvod-settings.yaml.
* `--edit / --run`: Open in marimo's editor instead of the read-only app view.  [default: run]
* `--host <str>`: Host to bind to. Default: the marimo default, 127.0.0.1.
* `-p, --port <int>`: Port to bind to. Default: a port that marimo picks.
* `--help`: Show this message and exit.

## `canvodpy config`

Create, check, show, and edit canvod-settings.yaml.

**Usage**:

```console
$ canvodpy config [OPTIONS] COMMAND [ARGS]...
```

**Options**:

* `--config <path>`: Settings file whose values replace those of canvod-settings.yaml.
* `--help`: Show this message and exit.

**Commands**:

* `init`: Create canvod-settings.yaml from its...
* `validate`: Validate the configuration and the...
* `show`: Show the settings that canvodpy uses.
* `edit`: Open canvod-settings.yaml in $EDITOR.

### `canvodpy config init`

Create canvod-settings.yaml from its template.

The file goes into the configuration directory that --config-dir sets.
Create a naming recipe for each receiver with
just naming-init SITE NAME.

**Usage**:

```console
$ canvodpy config init [OPTIONS]
```

**Options**:

* `-c, --config-dir <path>`: Configuration directory, holding canvod-settings.yaml and recipes/. Default: $CANVOD_CONFIG_DIR, else config/ of the canvodpy checkout, else ~/.config/canvodpy.
* `-f, --force`: Overwrite existing files
* `-i, --interactive`: Walk through setup with a guided Q&A instead of hand-editing YAML
* `--help`: Show this message and exit.

### `canvodpy config validate`

Validate the configuration and the receiver data it points to.

It finds the data files the same way as canvodpy run, so every error
it reports would stop a run or make its results wrong.

**Usage**:

```console
$ canvodpy config validate [OPTIONS]
```

**Options**:

* `-c, --config-dir <path>`: Configuration directory, holding canvod-settings.yaml and recipes/. Default: $CANVOD_CONFIG_DIR, else config/ of the canvodpy checkout, else ~/.config/canvodpy.
* `--site <str>`: Check the data of this site only. Repeat for several sites. Default: all sites.
* `--check-sampling / --no-check-sampling`: Read the first file of the first and the last day of each receiver and compare the sampling interval of its data with the one in its canonical name.  [default: check-sampling]
* `--help`: Show this message and exit.

### `canvodpy config show`

Show the settings that canvodpy uses.

**Usage**:

```console
$ canvodpy config show [OPTIONS]
```

**Options**:

* `-c, --config-dir <path>`: Configuration directory, holding canvod-settings.yaml and recipes/. Default: $CANVOD_CONFIG_DIR, else config/ of the canvodpy checkout, else ~/.config/canvodpy.
* `-s, --section processing|sites|sids`: Show this section only. Default: all sections.
* `--help`: Show this message and exit.

### `canvodpy config edit`

Open canvod-settings.yaml in $EDITOR.

**Usage**:

```console
$ canvodpy config edit [OPTIONS]
```

**Options**:

* `-c, --config-dir <path>`: Configuration directory, holding canvod-settings.yaml and recipes/. Default: $CANVOD_CONFIG_DIR, else config/ of the canvodpy checkout, else ~/.config/canvodpy.
* `--help`: Show this message and exit.

## `canvodpy store`

Inspect the Icechunk stores of the sites and maintain them.

**Usage**:

```console
$ canvodpy store [OPTIONS] COMMAND [ARGS]...
```

**Options**:

* `--help`: Show this message and exit.

**Commands**:

* `list`: List every configured site's GNSS and VOD...
* `info`: Show branches, groups, and stats for one...
* `log`: Show the commit history as a graph, or the...
* `maintain`: Expire old snapshots of one site's store...
* `maintain-due`: Run only the store maintenance that's due,...
* `migrate-metadata`: Move a store written before repository...
* `amend`: Change the description of a site's store,...

### `canvodpy store list`

List every configured site's GNSS and VOD store paths and status.

**Usage**:

```console
$ canvodpy store list [OPTIONS]
```

**Options**:

* `-c, --config-dir <path>`: Configuration directory, holding canvod-settings.yaml and recipes/. Default: $CANVOD_CONFIG_DIR, else config/ of the canvodpy checkout, else ~/.config/canvodpy.
* `--help`: Show this message and exit.

### `canvodpy store info`

Show branches, groups, and stats for one site's store.

**Usage**:

```console
$ canvodpy store info [OPTIONS] {site}
```

**Arguments**:

* `site`: Site name, as defined under sites: in canvod-settings.yaml  [required]

**Options**:

* `--store gnss|vod`: Store to open.  [default: gnss]
* `--branch <str>`: Branch to inspect  [default: main]
* `--group <str>`: Show the full content of one group: its dataset and its metadata table.
* `-c, --config-dir <path>`: Configuration directory, holding canvod-settings.yaml and recipes/. Default: $CANVOD_CONFIG_DIR, else config/ of the canvodpy checkout, else ~/.config/canvodpy.
* `--help`: Show this message and exit.

### `canvodpy store log`

Show the commit history as a graph, or the store operations with --ops.

**Usage**:

```console
$ canvodpy store log [OPTIONS] {site}
```

**Arguments**:

* `site`: Site name, as defined under sites: in canvod-settings.yaml  [required]

**Options**:

* `--store gnss|vod`: Store to open.  [default: gnss]
* `--branch <str>`: Show the history of this branch only. Default: all branches.
* `--ops`: Show the operations on the store instead of the commit graph.
* `--limit <int>`: Number of operations that --ops shows.  [default: 50]
* `-c, --config-dir <path>`: Configuration directory, holding canvod-settings.yaml and recipes/. Default: $CANVOD_CONFIG_DIR, else config/ of the canvodpy checkout, else ~/.config/canvodpy.
* `--help`: Show this message and exit.

### `canvodpy store maintain`

Expire old snapshots of one site's store and collect garbage.

Without --execute, this is a dry run: it reports what garbage
collection would delete and how many snapshots of the main branch are
older than the cutoff, and changes nothing. With --execute, it asks
for confirmation, expires the old snapshots and, unless you pass
--no-gc, collects garbage.

Don't run it while a canvodpy run writes to the same store.

**Usage**:

```console
$ canvodpy store maintain [OPTIONS] {site}
```

**Arguments**:

* `site`: Site name, as defined under sites: in canvod-settings.yaml  [required]

**Options**:

* `--store gnss|vod`: Store to open.  [default: gnss]
* `--expire-days <int>`: Keep the snapshots of this many past days. Use weeks to months, not hours.  [default: 90]
* `--gc / --no-gc`: Run garbage collection  [default: gc]
* `--execute`: Expire snapshots and collect garbage, after you confirm. Without this flag the command only reports and changes nothing.
* `-c, --config-dir <path>`: Configuration directory, holding canvod-settings.yaml and recipes/. Default: $CANVOD_CONFIG_DIR, else config/ of the canvodpy checkout, else ~/.config/canvodpy.
* `--help`: Show this message and exit.

### `canvodpy store maintain-due`

Run only the store maintenance that's due, without prompting.

Use this command, not maintain, in scheduled jobs such as cron: it
never asks for confirmation, and it exits with status 0 when nothing
is due. It reads processing.storage.maintenance in
canvod-settings.yaml and does nothing unless both of these hold:

- maintenance.enabled or maintenance.manifests_enabled is true. Both
  are false by default. Before you set them, run
  canvodpy store maintain SITE, which is a dry run, on your store and
  check its report.
- No canvodpy run is active on this computer.

maintenance.enabled allows snapshot expiry and garbage collection.
Expiry is due when the last one ran more than
maintenance.expire_interval_days ago, or never ran. Garbage
collection is due maintenance.gc_delay_days after an expiry, once per
expiry. maintenance.manifests_enabled allows manifest compaction,
which is due when the store holds at least
maintenance.manifest_count_threshold manifest files.

While maintenance.dry_run_until_confirmed is true, the default, a
store that's due is only reported, not changed. Set it to
false once the reports look right.

**Usage**:

```console
$ canvodpy store maintain-due [OPTIONS] [site]
```

**Arguments**:

* `site`: Site name. Omit when using --all-sites.

**Options**:

* `--all-sites`: Run for every site in canvod-settings.yaml.
* `--store gnss|vod|both`: Store to maintain.  [default: both]
* `-c, --config-dir <path>`: Configuration directory, holding canvod-settings.yaml and recipes/. Default: $CANVOD_CONFIG_DIR, else config/ of the canvodpy checkout, else ~/.config/canvodpy.
* `--help`: Show this message and exit.

### `canvodpy store migrate-metadata`

Move a store written before repository metadata to the current form.

Writes the store's description into its repository metadata, gives it
a new store id, made of the site name in lowercase and the store kind,
and a UUID, and keeps the old id in the migration record. Snapshots
from before stay readable.

The migrated store must pass the standards checks: fields the store
lacks, such as its description, are given with --set, otherwise the
migration is refused and lists them. In a VOD store, the attributes of
VOD are replaced with the current ones: older versions copied the
attributes of SNR and theta to VOD, among them the valid range of theta.
The migration record keeps who migrated the store, the initials set in
processing.metadata.initials.

**Usage**:

```console
$ canvodpy store migrate-metadata [OPTIONS] {site}
```

**Arguments**:

* `site`: Site name, as defined under sites: in canvod-settings.yaml  [required]

**Options**:

* `--store gnss|vod`: Store to migrate.  [default: gnss]
* `--naming-authority <str>`: Your institution's domain in reverse order, for example at.ac.tuwien. Default: the store's own, if it is a reverse DNS name; otherwise processing.metadata.naming_authority in the settings.
* `--set field.path=value`: A field the store lacks, for example identity.description=Beech forest site, Rosalia. Repeat for more fields.
* `--yes`: Migrate without asking.
* `-c, --config-dir <path>`: Configuration directory, holding canvod-settings.yaml and recipes/. Default: $CANVOD_CONFIG_DIR, else config/ of the canvodpy checkout, else ~/.config/canvodpy.
* `--help`: Show this message and exit.

### `canvodpy store amend`

Change the description of a site's store, with a reason.

Fixed fields (the store id, UUID, store type, source format, naming
authority and creation date) never change. Each changed field is
recorded with its old and new value, the reason, who and when, and a
new commit carries the new description. Who is the initials set in
processing.metadata.initials.

**Usage**:

```console
$ canvodpy store amend [OPTIONS] {site}
```

**Arguments**:

* `site`: Site name, as defined under sites: in canvod-settings.yaml  [required]

**Options**:

* `--store gnss|vod`: Store to amend.  [default: gnss]
* `--set field.path=value`: New value of a field, for example identity.title=Rosalia GNSS observations. Repeat for more fields.
* `--add-receiver name`: Add a receiver of the site's settings to the store, so runs may write it.
* `--add-vod-analysis name`: Add a VOD analysis of the site's settings to the VOD store.
* `--from <path>`: YAML file with the keys reason, set (field paths and values), and the lists add_receivers and add_vod_analyses.
* `--reason <str>`: Why the fields change; recorded with each one.
* `--yes`: Amend without asking.
* `-c, --config-dir <path>`: Configuration directory, holding canvod-settings.yaml and recipes/. Default: $CANVOD_CONFIG_DIR, else config/ of the canvodpy checkout, else ~/.config/canvodpy.
* `--help`: Show this message and exit.

## `canvodpy stac`

Write the STAC catalog of every store under the data root, or a release.

**Usage**:

```console
$ canvodpy stac [OPTIONS] COMMAND [ARGS]...
```

**Options**:

* `--help`: Show this message and exit.

**Commands**:

* `write`: Write the latest catalog of every store...
* `release`: Publish a release: tag every store under...

### `canvodpy stac write`

Write the latest catalog of every store under the data root.

If a store cannot be described, nothing is written: the command lists
every such store with its reason and exits with code 1.

**Usage**:

```console
$ canvodpy stac write [OPTIONS]
```

**Options**:

* `--root <path>`: Data root to catalog. Default: storage.stores_root_dir in the settings.
* `-c, --config-dir <path>`: Configuration directory, holding canvod-settings.yaml and recipes/. Default: $CANVOD_CONFIG_DIR, else config/ of the canvodpy checkout, else ~/.config/canvodpy.
* `--help`: Show this message and exit.

### `canvodpy stac release`

Publish a release: tag every store under the data root and write its catalog.

TAG becomes an Icechunk tag on the current main of every store, and
releases/TAG/ gets the catalog of that tag, each asset pinned to the
tag and its snapshot. A release catalog is never changed afterwards.
Nothing is tagged if a store cannot be described or already has the
tag; if every store has the tag but the catalog is missing, only the
catalog is written.

**Usage**:

```console
$ canvodpy stac release [OPTIONS] {tag}
```

**Arguments**:

* `tag`: Release tag, for example v2026.1; no '/'.  [required]

**Options**:

* `--root <path>`: Data root to catalog. Default: storage.stores_root_dir in the settings.
* `-c, --config-dir <path>`: Configuration directory, holding canvod-settings.yaml and recipes/. Default: $CANVOD_CONFIG_DIR, else config/ of the canvodpy checkout, else ~/.config/canvodpy.
* `--help`: Show this message and exit.
