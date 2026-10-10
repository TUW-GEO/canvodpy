---
title: Command line
description: Every canvodpy command and option, with the text of its --help.
---

<!-- Written by scripts/cli_docs.py from the canvodpy --help texts.
     Don't edit this page: change the help texts and run `just cli-docs`. -->

# Command line

The `canvodpy` command runs canVODpy from the command line. This page
lists every command and option; `canvodpy COMMAND --help` prints the same
text in the terminal. For a walk through a first run, see
[Retrieve VOD](../users/index.md).

canvodpy CLI tools

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
* `vod`: Compute VOD in bulk from an existing GNSS...
* `vod-reconcile`: Find (and optionally backfill)...
* `doctor`: Report canvodpy's version, environment,...
* `dashboard`: Launch the marimo performance dashboard...
* `config`: Configuration management
* `store`: Inspect Icechunk stores: list sites, show...

## `canvodpy run`

Process GNSS observations into Icechunk stores and compute VOD.

**Usage**:

```console
$ canvodpy run [OPTIONS]
```

**Options**:

* `--site <str>`: Site name, as defined under sites: in canvod-settings.yaml, for example ExampleSite. Repeat the option for several sites; they are processed one after the other.  [required]
* `--start <str>`: Start date in YYYYDOY format, for example 2025001. If omitted, resumes from the last processed date in the store.
* `--end <str>`: End date in YYYYDOY format, for example 2025007. If omitted, processes up to today.
* `--no-vod / --vod`: Skip VOD calculation (only ingest observations).  [default: vod]
* `--dry-run / --no-dry-run`: Preview processing plan without executing.  [default: no-dry-run]
* `--workers <int>`: Number of loky worker processes (default: from config).
* `--days-per-batch <int>`: Number of DOYs per loky wave (default: from config).
* `-c, --config-dir <path>`: Configuration directory, holding canvod-settings.yaml and recipes/. Default: $CANVOD_CONFIG_DIR, else config/ of the canvodpy checkout, else ~/.config/canvodpy.
* `--config <str>`: Overlay config YAML applied on top of the main canvod-settings.yaml.
* `--ephemeris-source <final|broadcast>`: Override the configured ephemeris source ('final' = agency SP3/CLK, 'broadcast' = SBF SatVisibility). Default: from canvod-settings.yaml.
* `--vod-calculator <tau_omega>`: VOD calculator to use.  [default: tau_omega]
* `--dashboard`: Launch the marimo performance dashboard alongside this run, as a detached subprocess (its startup banner is redirected to a log file, not printed here).
* `--dashboard-host <str>`: Host for --dashboard to bind to.  [default: 127.0.0.1]
* `--dashboard-port <int>`: Port for --dashboard to bind to (default: an OS-assigned free port).
* `--help`: Show this message and exit.

## `canvodpy vod`

Compute VOD in bulk from an existing GNSS store (backfill/reprocessing).

**Usage**:

```console
$ canvodpy vod [OPTIONS]
```

**Options**:

* `--site <str>`: Site name, as defined under sites: in canvod-settings.yaml  [required]
* `--analysis <str>`: VOD analysis name, as defined in site.vod_analyses  [required]
* `--start <str>`: Start date in YYYYDOY format, for example 2025001.
* `--end <str>`: End date in YYYYDOY format, for example 2025007.
* `--calculator <str>`: VOD calculator to use.  [default: tau_omega]
* `-c, --config-dir <path>`: Configuration directory, holding canvod-settings.yaml and recipes/. Default: $CANVOD_CONFIG_DIR, else config/ of the canvodpy checkout, else ~/.config/canvodpy.
* `--help`: Show this message and exit.

## `canvodpy vod-reconcile`

Find (and optionally backfill) RINEX-ingested-but-VOD-missing dates.

**Usage**:

```console
$ canvodpy vod-reconcile [OPTIONS]
```

**Options**:

* `--site <str>`: Site name, as defined under sites: in canvod-settings.yaml  [required]
* `--analysis <str>`: VOD analysis name, as defined in site.vod_analyses  [required]
* `--calculator <str>`: VOD calculator to use.  [default: tau_omega]
* `--execute`: Backfill the gaps found. Default is a dry-run report only.
* `-c, --config-dir <path>`: Configuration directory, holding canvod-settings.yaml and recipes/. Default: $CANVOD_CONFIG_DIR, else config/ of the canvodpy checkout, else ~/.config/canvodpy.
* `--help`: Show this message and exit.

## `canvodpy doctor`

Report canvodpy's version, environment, and config resolution.

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

* `--logs-dir <str>`: Directory containing the machine/performance*.json files (default: processing.logging.log_dir of canvod-settings.yaml).
* `--edit / --run`: Open in marimo's editor instead of the read-only app view.  [default: run]
* `--host <str>`: Host to attach to (default: marimo's 127.0.0.1).
* `-p, --port <int>`: Port to attach to (default: marimo picks one).
* `--help`: Show this message and exit.

## `canvodpy config`

Configuration management

**Usage**:

```console
$ canvodpy config [OPTIONS] COMMAND [ARGS]...
```

**Options**:

* `--config <path>`: Overlay config file applied on top of the main canvod-settings.yaml
* `--help`: Show this message and exit.

**Commands**:

* `init`: Create canvod-settings.yaml from its...
* `validate`: Validate the configuration and the...
* `show`: Display current configuration.
* `edit`: Open canvod-settings.yaml in $EDITOR.

### `canvodpy config init`

Create canvod-settings.yaml from its template.

The file goes into the configuration directory (see --config-dir).
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

The data are checked with the same file discovery as ``canvodpy run``:
every error reported here would stop a run or make its results wrong.

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

Display current configuration.

**Usage**:

```console
$ canvodpy config show [OPTIONS]
```

**Options**:

* `-c, --config-dir <path>`: Configuration directory, holding canvod-settings.yaml and recipes/. Default: $CANVOD_CONFIG_DIR, else config/ of the canvodpy checkout, else ~/.config/canvodpy.
* `-s, --section <str>`: Show specific section (processing, sites, sids)
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

Inspect Icechunk stores: list sites, show tree/stats, view commit history.

**Usage**:

```console
$ canvodpy store [OPTIONS] COMMAND [ARGS]...
```

**Options**:

* `--help`: Show this message and exit.

**Commands**:

* `list`: List every configured site's GNSS and VOD...
* `info`: Show branches, groups, and stats for one...
* `log`: Show commit history as a graph (or the ops...
* `maintain`: Expire old snapshots of one site's store...
* `maintain-due`: Run only the store maintenance that is...

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

* `--store <str>`: Which store: gnss or vod  [default: gnss]
* `--branch <str>`: Branch to inspect  [default: main]
* `--group <str>`: Drill into one group's full content (dataset + metadata table)
* `-c, --config-dir <path>`: Configuration directory, holding canvod-settings.yaml and recipes/. Default: $CANVOD_CONFIG_DIR, else config/ of the canvodpy checkout, else ~/.config/canvodpy.
* `--help`: Show this message and exit.

### `canvodpy store log`

Show commit history as a graph (or the ops audit trail with --ops).

**Usage**:

```console
$ canvodpy store log [OPTIONS] {site}
```

**Arguments**:

* `site`: Site name, as defined under sites: in canvod-settings.yaml  [required]

**Options**:

* `--store <str>`: Which store: gnss or vod  [default: gnss]
* `--branch <str>`: Restrict to one branch's linear history (default: all)
* `--ops`: Show the operations audit trail instead of the commit graph
* `--limit <int>`: Max entries for --ops  [default: 50]
* `-c, --config-dir <path>`: Configuration directory, holding canvod-settings.yaml and recipes/. Default: $CANVOD_CONFIG_DIR, else config/ of the canvodpy checkout, else ~/.config/canvodpy.
* `--help`: Show this message and exit.

### `canvodpy store maintain`

Expire old snapshots of one site's store and collect garbage.

Without --execute, this is a dry run: it reports what garbage
collection would delete and how many snapshots of the main branch are
older than the cutoff, and changes nothing. With --execute, it asks
for confirmation, expires the old snapshots and, unless --no-gc is
given, collects garbage.

Don't run it while a canvodpy run writes to the same store.

**Usage**:

```console
$ canvodpy store maintain [OPTIONS] {site}
```

**Arguments**:

* `site`: Site name, as defined under sites: in canvod-settings.yaml  [required]

**Options**:

* `--store <str>`: Which store: gnss or vod  [default: gnss]
* `--expire-days <int>`: Keep the snapshots of this many past days. Use weeks to months, not hours.  [default: 90]
* `--gc / --no-gc`: Run garbage collection  [default: gc]
* `--execute`: Expire snapshots and collect garbage, after you confirm. Without this flag, only a dry-run report is shown and nothing is deleted or expired.
* `-c, --config-dir <path>`: Configuration directory, holding canvod-settings.yaml and recipes/. Default: $CANVOD_CONFIG_DIR, else config/ of the canvodpy checkout, else ~/.config/canvodpy.
* `--help`: Show this message and exit.

### `canvodpy store maintain-due`

Run only the store maintenance that is due, without prompting.

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

While maintenance.dry_run_until_confirmed is true, which is the
default, a store that is due is only reported, not changed. Set it to
false once the reports look right.

**Usage**:

```console
$ canvodpy store maintain-due [OPTIONS] [site]
```

**Arguments**:

* `site`: Site name. Omit when using --all-sites.

**Options**:

* `--all-sites`: Run for every site in canvod-settings.yaml
* `--store <str>`: Which store(s): gnss, vod, or both  [default: both]
* `-c, --config-dir <path>`: Configuration directory, holding canvod-settings.yaml and recipes/. Default: $CANVOD_CONFIG_DIR, else config/ of the canvodpy checkout, else ~/.config/canvodpy.
* `--help`: Show this message and exit.
