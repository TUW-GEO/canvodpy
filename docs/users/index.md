---
title: Retrieve VOD
description: Install canVODpy, describe your site and data in canvod-settings.yaml, and retrieve GNSS-T VOD from the command line or from Python.
---

# Retrieve VOD from your GNSS data

There are two ways to run canVODpy, and they're equivalent:

- **From the command line**, with `canvodpy run`. This suits processing
  a whole period without supervision, for example on a server.
- **From Python**, with `Site.pipeline()`, in a script or a notebook.
  This suits trying things out and going straight on to analysis.

Both run the same processing, read the same settings file, and write the
same stores. They also need the same setup, which this page goes through
step by step:

0. [Before you start](#before-you-start)
1. [Install canVODpy](#1-install-canvodpy)
2. [Create the settings file](#2-create-the-settings-file)
3. [Point canVODpy to your data](#3-point-canvodpy-to-your-data)
4. [Check the settings and the data](#4-check-the-settings-and-the-data)
5. [Process one day](#5-process-one-day)
6. [Process a period](#6-process-a-period)
7. [Open the VOD](#7-open-the-vod)

Where the two ways differ, the steps show a **Python** and a
**Command line** tab. Choosing a tab switches all tabs on the page.

---

## Before you start

You need:

- **GNSS data from two receivers at one site**: one below the canopy and
  one with an unobstructed view of the sky, recording the same signals at
  the same time. canVODpy derives VOD from the difference in their
  signal-to-noise ratios; [VOD retrieval](../packages/vod/overview.md)
  explains the method.
- **A terminal**: Terminal on macOS, a shell on Linux, or PowerShell on
  Windows. All commands on this page are typed there.
- **uv**, the tool that installs canVODpy and Python for you. Follow the
  [uv installation guide](https://docs.astral.sh/uv/getting-started/installation/).
  canVODpy needs Python 3.14 or later; if you don't have it, uv downloads
  it.
- **An internet connection** during processing, to download the
  satellite orbits and clocks.

---

## 1. Install canVODpy

=== "Python"

    Add canVODpy to the uv project you work in. A uv project is a folder
    with a `pyproject.toml` file that lists the packages your code needs;
    uv keeps them in an environment of their own in that folder. If you
    don't have a project yet, create one (see
    [Working on projects](https://docs.astral.sh/uv/guides/projects/)):

    ```bash
    uv init my-analysis && cd my-analysis
    ```

    Then add canVODpy:

    ```bash
    uv add canvodpy
    ```

    Your scripts and notebooks in the project can now `import canvodpy`.

    This also installs the `canvodpy` command into the environment of the
    project. Run it through uv, from inside the project:

    ```bash
    uv run canvodpy --help
    ```

    This page writes the commands as `canvodpy ...`; in a project, type
    `uv run canvodpy ...`.

=== "Command line"

    Install canVODpy as a uv tool:

    ```bash
    uv tool install canvodpy
    uv tool update-shell   # once: puts the tool folder on your PATH
    ```

    uv installs canVODpy into an environment of its own and puts the
    `canvodpy` command into a folder on your `PATH`, the list of folders
    in which the terminal looks for commands
    (see [Using tools](https://docs.astral.sh/uv/guides/tools/)). Open a
    new terminal, and you can run the command from any folder, without
    `uv run`:

    ```bash
    canvodpy --help
    ```

    To update or remove the tool, run `uv tool upgrade canvodpy` or
    `uv tool uninstall canvodpy`.

??? note "Run the command from a clone of the repository"

    To have `canvodpy` on your `PATH` and follow your local edits, link
    the command from the environment of the clone:

    ```bash
    cd /path/to/canvodpy && uv sync
    ln -s "$(pwd)/.venv/bin/canvodpy" ~/.local/bin/canvodpy
    ```

    After `git pull`, run `uv sync` again; the link stays valid. If you
    move the clone, recreate the environment and the link:

    ```bash
    rm -rf .venv && uv sync
    ln -sf "$(pwd)/.venv/bin/canvodpy" ~/.local/bin/canvodpy
    ```

    To remove the command, delete the link: `rm ~/.local/bin/canvodpy`.

---

## 2. Create the settings file

canVODpy needs to know where your data is, who you are, and which
receivers to compare. It reads all of this from one file,
`canvod-settings.yaml`. The file is in [YAML](https://yaml.org/), a plain
text format in which each line holds a `name: value` pair and the
indentation, with spaces, shows which setting belongs to which section.
The file has three sections:

| Section       | What it sets                                                                       |
| ------------- | ---------------------------------------------------------------------------------- |
| `processing:` | Your name and institution for the metadata, where to write the stores and the log files, ephemeris products, and processing parameters |
| `sites:`      | Your sites, the folder of each receiver, and the receiver pairs to compute VOD for |
| `sids:`       | The signals to keep                                                                |

Only a few settings are required; the
[minimal example](../guides/configuration.md#minimal-working-example)
shows them. All others have defaults.

The settings wizard creates the file for you. It asks for your name, your
email address, your institution, the folder for the stores, the folder
for the log files, your site, and the folders of the two receivers. Then it writes the file and checks
it:

```bash
canvodpy config init --interactive
```

Without `--interactive`, the command copies the template and you fill it
in yourself, with `canvodpy config edit` or any text editor.

### Where the file is

canVODpy looks for the settings file in this order:

1. The folder in the environment variable `CANVOD_CONFIG_DIR`, or the
   folder you give with `--config-dir`.
2. The `config/` folder of a canVODpy clone, if you work in one.
3. `~/.config/canvodpy/` (or `$XDG_CONFIG_HOME/canvodpy/`).

To see which file canVODpy found and whether it's valid, run:

```bash
canvodpy doctor
```

Python finds the file the same way: `Site("ExampleSite")` reads the site
from the file that `canvodpy doctor` names.

The [Configuration guide](../guides/configuration.md) describes every
setting and how to keep machine-specific settings in a separate file.

!!! example "Try it in a notebook"

    Open [Configuration](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/02_configuration.py?mode=edit) in molab, the online notebook service of marimo.

---

## 3. Point canVODpy to your data

Each site has a data folder, `gnss_site_data_root`. Each receiver has a
folder of its own inside it, `directory`:

```yaml
sites:
  ExampleSite:
    gnss_site_data_root: /data/ExampleSite
    receivers:
      reference_01:
        type: reference          # the receiver with an unobstructed view of the sky
        directory: 01_reference
        paired_canopies: all
      canopy_01:
        type: canopy             # the receiver below the canopy
        directory: 02_canopy
    vod_analyses:
      canopy_01_vs_reference_01:
        canopy_receiver: canopy_01
        reference_receiver: reference_01
```

Inside a receiver folder, the layout is up to you: all files in one
folder, one folder per day, or deeper. Keep the files of each receiver
in their own folder.

### File names

canVODpy takes the receiver and the day of each file from its name, so
the files must follow the canVOD file naming convention, for example:

```
ROSR01TUW_R_20250010000_01D_05S_AA.rnx
```

This name says: site `ROS`, reference receiver `01`, data from TU Wien,
starting on day 001 of 2025 at 00:00, one day of data, sampled every
5 seconds, in RINEX. The [file naming convention](../packages/naming/overview.md)
explains each field.

!!! example "Try it in a notebook"

    Open [Naming convention](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/04_naming_convention.py?mode=edit) in molab, the online notebook service of marimo.

If your files have other names, for example the names your receiver
gives them, you don't have to rename them. A naming recipe maps them to
the convention; it needs the optional `canvod-filemap` extension (see
[Optional extensions](../guides/extensions.md)).

canVODpy reads RINEX v2.11, RINEX v3.04, Septentrio SBF, and NMEA files. It
doesn't read compressed files, including Hatanaka-compressed RINEX;
decompress them first. The canopy receiver and the reference receiver
must record the same file format.

### Ephemeris products

To compute where each satellite was, canVODpy downloads precise
satellite orbits (SP3 files) and clocks (CLK files) from the European Space Agency (ESA). This needs
no account and no setup. To add the NASA Crustal Dynamics Data Information System (CDDIS) as a
fallback,
see [Ephemeris data sources](../guides/configuration.md#ephemeris-data-sources).

---

## 4. Check the settings and the data

Before the first run, check one site:

```bash
canvodpy config validate --site ExampleSite
```

The check finds the files of each receiver exactly as a run does. It
lists the days and files a run would process, the files it would skip,
and the problems that would stop the run, for example two files that
cover the same time.

---

## 5. Process one day

canVODpy names a day by its year and day of year, as `YYYYDDD`. For
example, `2025001` is January 1, 2025 and `2025032` is February 1, 2025.

=== "Python"

    ```python
    from canvodpy import Site

    site = Site("ExampleSite")
    with site.pipeline() as pipeline:
        data = pipeline.process_date("2025001")
    vod = site.vod.compute_day_all(data)
    ```

    `process_date` reads the files of each receiver, adds the satellite
    positions from the ephemeris products, and writes the observations to
    the site's Icechunk store. It returns one dataset per receiver.
    `compute_day_all` computes VOD for every receiver pair in
    `vod_analyses` and writes it to the site's VOD store.

=== "Command line"

    ```bash
    canvodpy run --site ExampleSite --start 2025001 --end 2025001
    ```

    The run reads the files of each receiver, adds the satellite positions
    from the ephemeris products, writes the observations to the site's
    Icechunk store, and computes VOD for every receiver pair in
    `vod_analyses` and writes it to the site's VOD store.

    To see what a run would process without running it, add `--dry-run`.

Files that are already in the store are skipped.

!!! example "Try it in a notebook"

    Open [Site pipeline](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/18_site_pipeline.py?mode=edit), [Running the pipeline from the command line](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/01_cli_pipeline.py?mode=edit) in molab, the online notebook service of marimo.

---

## 6. Process a period

=== "Python"

    `process_range` processes several days and returns the datasets of
    one day at a time:

    ```python
    with site.pipeline() as pipeline:
        for date, data in pipeline.process_range("2025001", "2025031"):
            vod = site.vod.compute_day_all(data)
    ```

=== "Command line"

    ```bash
    canvodpy run --site ExampleSite --start 2025001 --end 2025031
    ```

    Leave out `--start` and the run continues from the last day in the
    store. Leave out `--end` and it processes up to today. So this command
    picks up wherever the last run stopped:

    ```bash
    canvodpy run --site ExampleSite
    ```

By default, canVODpy uses all but two of the machine's CPU cores. To set
limits, see [Parallel processing](../guides/parallel-processing.md).

!!! example "Try it in a notebook"

    Open [Batch processing](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/20_workflow_batch_processing.py?mode=edit) in molab, the online notebook service of marimo.

---

## 7. Open the VOD

However you processed the data, the VOD is in the site's VOD store, and
you open it in Python. The store is an [Icechunk](https://icechunk.io/)
repository, which keeps a history of every write, like git:

```python
from canvodpy import Site

site = Site("ExampleSite")
site.vod_store.print_tree()
vod = site.vod_store.read_group("tau_omega/canopy_01_vs_reference_01")
```

Each receiver pair has one group, `<VOD calculator>/<entry in
vod_analyses>`. `print_tree` lists them. `read_group` returns an
[xarray](https://docs.xarray.dev/) Dataset, with VOD per time and signal.

To look at the stores from the command line, without opening Python:

```bash
canvodpy store list                          # every site's stores and their status
canvodpy store info ExampleSite --store vod  # the groups of the VOD store
canvodpy store log ExampleSite --store vod   # the history of its writes
```

!!! example "Try it in a notebook"

    Open [VOD retrieval](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/10_vod_retrieval.py?mode=edit), [Icechunk store](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/11_icechunk_store.py?mode=edit) in molab, the online notebook service of marimo.


---

## Next steps

- [Configuration guide](../guides/configuration.md): every setting.
- [Command line and Python](../guides/api-levels.md): all options of
  `canvodpy run`, and the `Site` and `Pipeline` objects in detail.
- [Command line reference](../api/cli.md): every `canvodpy` command and
  option.
- [Hemispheric grids](../packages/grids/overview.md): assign the VOD to
  cells of the sky.
- [Storage](../packages/store/overview.md): the history of a store, and
  how to read the observations.

To work on canVODpy itself, see
[Contributor setup](../guides/contributor-setup.md).
