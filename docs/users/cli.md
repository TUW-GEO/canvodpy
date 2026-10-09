---
title: CLI Quickstart
description: Install, configure, and run canVODpy entirely from the command line.
---

# CLI Quickstart

## Installation

canVODpy is a terminal-first CLI tool. Pick the install method that matches
what you're doing:

### Persistent CLI, published release

```bash
uv tool install canvodpy
uv tool update-shell   # one-time: adds ~/.local/bin to PATH if it isn't already there
```

`uv tool install` builds an isolated environment and drops a `canvodpy` shim
on your `PATH` — persistent across terminal sessions and reboots, just like
any other installed command (`git`, `just`, etc.). Only goes away via an
explicit uninstall.

**Update to the latest release:**

```bash
uv tool upgrade canvodpy
```

**Uninstall:**

```bash
uv tool uninstall canvodpy
```

### Persistent CLI, local development checkout (live edits)

If you're working from a cloned monorepo and want `canvodpy` on your `PATH`
while it tracks your local edits (not `uv tool install --editable` — that
only makes the one top-level package editable, the ~10 internal workspace
packages would still resolve from PyPI instead of your local changes):

```bash
cd /path/to/canvodpy && uv sync
ln -s "$(pwd)/.venv/bin/canvodpy" ~/.local/bin/canvodpy
```

`uv sync` bakes an absolute path to the checkout's Python into the shim's
shebang, so the symlink works from any directory regardless of your current
working directory.

**Update:** pull and re-sync — the symlink itself doesn't need to change:

```bash
git pull && uv sync
```

**Uninstall:** remove just the shim (the checkout and its `.venv` are untouched):

```bash
rm ~/.local/bin/canvodpy
```

!!! warning "If you move or rename the checkout"

    The symlink's target path is fixed at creation time. If the checkout
    directory is ever moved or renamed, rebuild the venv and recreate the
    symlink:
    ```bash
    rm -rf .venv && uv sync
    ln -sf "$(pwd)/.venv/bin/canvodpy" ~/.local/bin/canvodpy
    ```

### Inside your own uv project

```bash
uv add canvodpy
```

adds it to a project's own environment — only invocable via `uv run canvodpy`
from within that project, not as a bare `canvodpy` command elsewhere.

Then follow the two steps below — configure the project and run your first pipeline day.

---

## 1. Configure the project

canVODpy is configured through a **single YAML file** — `config/canvod-settings.yaml`, located in the project root's `config/` directory — with three sections:

| Section       | Purpose                                                                                                                                                                               |
| ------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `sites:`      | Research sites: data root paths, receiver definitions (name, type, directory), and VOD analysis pairs. Each receiver's `directory` is relative to the site's `gnss_site_data_root`.   |
| `processing:` | Processing parameters: metadata, credentials (NASA Earthdata), auxiliary data settings (agency, product type), time aggregation, compression, Icechunk storage, and store strategies. |
| `sids:`       | Signal ID (SID) filtering: choose `all`, a named `preset` (e.g. `default`), or list `custom` SIDs to keep.                                                                            |

To initialize from the template:

```bash
just config-init          # runs: uv run canvodpy config init
```

Prefer a guided setup over hand-editing YAML? Answer a few questions instead:

```bash
canvodpy config init --interactive   # -i for short
```

This asks for your name, email, institution, where to store processed
results, and your first site's name/data root/receiver directories, writes
them straight into `canvod-settings.yaml`, and validates the result
immediately — no YAML editing required to get a working config. (Only runs
the guided setup on a freshly-created file; if `canvod-settings.yaml`
already exists, use `--force` to start over.)

After editing, validate your configuration:

```bash
just config-validate      # runs: uv run canvodpy config validate
```

To view the resolved configuration:

```bash
just config-show          # runs: uv run canvodpy config show
```

Something not working? `canvodpy doctor` reports canvodpy's version, where
it resolved your config from and why (dev checkout vs. XDG default),
whether bundled templates are reachable, and whether your
`canvod-settings.yaml` currently validates — a single read-only command
instead of checking each of those by hand:

```bash
canvodpy doctor
```

!!! note "Overriding config without editing files"

    Every setting in `canvod-settings.yaml` can also be overridden by an environment
    variable with the `CANVOD__` prefix (note the **double** underscores, which
    separate nesting levels). This is useful on HPC clusters or in CI, where
    editing a config file per job is impractical. For example:

    ```bash
    export CANVOD__PROCESSING__PARAMS__DAYS_PER_BATCH=7
    export CANVOD__PROCESSING__CREDENTIALS__NASA_EARTHDATA_ACC_MAIL="you@example.com"
    ```

    Environment variables take priority over values in the YAML file.
    See the [Configuration Guide](../guides/configuration.md) for the full reference.

---

## 2. Process your first day of data

Once your `canvod-settings.yaml` points to a site with GNSS data, you can run the pipeline.

### Check your data first (pre-flight)

Before processing, check that each receiver's files are found as expected:

```bash
canvodpy config validate --site <site>
```

This finds the files exactly as `canvodpy run` does. Without a naming recipe, only files
that follow the GNSS file naming convention
(`{SIT}{T}{NN}{AGC}_R_{YYYY}{DOY}{HHMM}_{PERIOD}_{SAMPLING}_{CONTENT}.{TYPE}`) are
processed. The check reports the days and files a run would process, the files it would
pass over, and problems that would stop it, **before** the run starts.

### Dates: the `YYYYDDD` format

canVODpy identifies days by **year + Day of Year (DOY)**: a 7-digit string
`YYYYDDD`, where `DDD` counts days from 001. For example, `"2025001"` is
1 January 2025 and `"2025032"` is 1 February 2025. This is the standard
date convention in GNSS data products.

### Run it

```bash
canvodpy run --site ExampleSite --start 2025001 --end 2025001
```

This reads the raw files, augments them with satellite positions (ephemeris),
and writes the results to the site's Icechunk store. Omit `--start` on later
runs and it resumes automatically from the last processed date.

!!! info "Ephemeris downloads"

    Satellite orbit products (SP3, and by default CLK) are downloaded
    automatically from **ESA GSSC** (no account needed). If you configure NASA
    Earthdata (CDDIS) credentials in `canvod-settings.yaml`, NASA is tried
    first with ESA as fallback. CLK isn't used by the VOD formula — set
    `aux_data.fetch_clock: false` to skip it.

---

Want to drive this from Python instead — for scripting, notebooks, or a
custom pipeline? See the [Python Quickstart](python.md).

**Next steps:** [Configuration Guide](../guides/configuration.md) · [API Levels](../guides/api-levels.md)
