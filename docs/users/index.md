---
title: Retrieve VOD
description: Install canVODpy, describe your site and data in canvod-settings.yaml, and retrieve GNSS-T VOD from the command line or from Python.
---

# Retrieve VOD from your GNSS data

!!! warning "Upgrading from 0.x?"

    Migrate your stores and check your settings first:
    [Upgrading to v1.0.0](../guides/upgrading.md).

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
  canVODpy needs Python 3.14; if you don't have it, uv downloads
  it.
- **An internet connection** during processing, to download the
  satellite orbits and clocks.

??? tip "No data of your own yet? Use the demo data"

    `canvodpy.demo_data()` downloads one day of the Rosalia site from
    Hugging Face: a receiver below the canopy and a reference receiver, on
    2025-01-01. It downloads only the kind of data you ask for, checks each
    archive against its sha256, and keeps the files in your user cache
    folder, so a second call needs no network.

    ```python
    from canvodpy import demo_data

    root = demo_data("rinex")  # RINEX v3.04, the whole day
    root = demo_data("sbf")  # SBF, 00:00 to 02:00
    root = demo_data("aux")  # SP3 orbits, CLK clocks, auxiliary store
    ```

    These three return the same folder. In it, the RINEX files of the two
    receivers are in `rinex_v3_04/01_Rosalia/01_reference` and
    `rinex_v3_04/01_Rosalia/02_canopy`, the SBF files in
    `sbf/01_Rosalia/01_reference` and `sbf/01_Rosalia/02_canopy`. Use
    the site folder as `gnss_site_data_root` and the receiver folders as
    `directory` in [step 3](#3-point-canvodpy-to-your-data). The
    pipeline still downloads the orbits and clocks from the agencies; the
    `"aux"` files are a copy for when that fails.

    `demo_data("stores")` downloads the GNSS store and the VOD store that
    canVODpy writes from the RINEX day, to look at a store without a run
    first. They are in `stores/rosalia_rinex_v3_04/gnss` and
    `stores/rosalia_rinex_v3_04/vod` of the folder it returns. Copy them
    before you write to them: the next call returns the same folder.

---

## 1. Install canVODpy

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

    If your receivers' file names don't follow the canVOD convention, you
    need the extension for naming recipes (see [File names](#file-names)).
    Install it into the tool with `--with`:

    ```bash
    uv tool install canvodpy --with canvod-filemap
    ```

    For reproducible runs, pin the versions:

    ```bash
    uv tool install canvodpy==1.0.0 --with canvod-filemap==1.0.0
    ```

    canVODpy pins only its own packages exactly. The versions of the other
    packages it needs (pandas, netCDF4, ...) and the Python patch version
    depend on the day of the install. To record them with your results:

    ```bash
    uv pip freeze --python "$(uv tool dir)/canvodpy/bin/python"
    ```

    To update or remove the tool, run `uv tool upgrade canvodpy` or
    `uv tool uninstall canvodpy`.

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

To see what a question sets, answer `?`: the wizard prints the setting's
description and asks again.

Without `--interactive`, the command copies the template and you fill it
in yourself, with `canvodpy config edit` or any text editor. Each setting
in the template has a link to its entry in the
[Settings reference](../guides/settings.md), and
`canvodpy config explain SETTING` prints that entry in the terminal.

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

    Open [Configuration](https://molab.marimo.io/github/TUW-GEO/canvodpy-demo/blob/main/02_configuration.py?mode=edit) in molab, the online notebook service of marimo.

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
FANR01INK_R_20250010000_01D_05S_AA.rnx
```

This name says: site `FAN`, reference receiver `01`, data from The
Inklings, starting on day 001 of 2025 at 00:00, one day of data, sampled
every 5 seconds, in RINEX. The [file naming convention](../packages/naming/overview.md)
explains each field.

!!! example "Try it in a notebook"

    Open [Naming convention](https://molab.marimo.io/github/TUW-GEO/canvodpy-demo/blob/main/04_naming_convention.py?mode=edit) in molab, the online notebook service of marimo.

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
        for unit in pipeline.run("2025001", "2025001"):
            print(unit.days, unit.vod.written)
    ```

    `run` reads the files of each receiver, adds the satellite positions
    from the ephemeris products, and writes the observations to the
    site's Icechunk store. Then it computes VOD for every receiver pair in
    `vod_analyses` and writes it to the site's VOD store. To work with the
    observations in Python, `pipeline.process_date("2025001")` returns
    one dataset per receiver, read back from the store.

=== "Command line"

    ```bash
    canvodpy run --site ExampleSite --start 2025001 --end 2025001
    ```

    The run reads the files of each receiver, adds the satellite positions
    from the ephemeris products, writes the observations to the site's
    Icechunk store, and computes VOD for every receiver pair in
    `vod_analyses` and writes it to the site's VOD store.

    Before it reads a file, a run finds the files of every receiver in the
    site. On a network drive this can take minutes. The CLI says, for each
    receiver, which folder it is scanning, and afterwards how many files and
    days it found, so you can see that the run is working. The next run is
    faster: it lists only the folders of the days it processes and takes
    the others from a
    [file index](../packages/naming/overview.md#folders-of-other-days-come-from-the-file-index).

    To see what a run would process without running it, add `--dry-run`.

Files that are already in the store are skipped.

!!! example "Try it in a notebook"

    Open [Site pipeline](https://molab.marimo.io/github/TUW-GEO/canvodpy-demo/blob/main/18_site_pipeline.py?mode=edit), [Running the pipeline from the command line](https://molab.marimo.io/github/TUW-GEO/canvodpy-demo/blob/main/01_cli_pipeline.py?mode=edit) in molab, the online notebook service of marimo.

---

## 6. Process a period

=== "Python"

    `run` processes the days in units of several days and yields what
    it stored and computed for each unit:

    ```python
    with site.pipeline() as pipeline:
        for unit in pipeline.run("2025001", "2025031"):
            print(sorted(unit.days), unit.vod.missing)
    ```

    `process_range("2025001", "2025031")` yields the datasets of one day
    at a time instead, read back from the store.

=== "Command line"

    ```bash
    canvodpy run --site ExampleSite --start 2025001 --end 2025031
    ```

    Leave out `--end` and the run processes up to today. Once the store
    holds data, `--update-to-latest` instead of the dates processes the
    days from the last stored day up to the latest files:

    ```bash
    canvodpy run --site ExampleSite --update-to-latest
    ```

    A run processes one site; for several, run it once per site
    ([Several sites](../guides/api-levels.md#several-sites)).

By default, canVODpy uses all but two of the machine's CPU cores. To set
limits, see [Parallel processing](../guides/parallel-processing.md).

To follow a long run while it's in progress, add `--dashboard`. It opens the
performance dashboard, which shows how long each step took per day and
receiver. The diagnostics guide explains it under
[See where a run spends its time](../guides/diagnostics.md#see-where-a-run-spends-its-time).

!!! example "Try it in a notebook"

    Open [Batch processing](https://molab.marimo.io/github/TUW-GEO/canvodpy-demo/blob/main/20_workflow_batch_processing.py?mode=edit) in molab, the online notebook service of marimo.

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

    Open [VOD retrieval](https://molab.marimo.io/github/TUW-GEO/canvodpy-demo/blob/main/10_vod_retrieval.py?mode=edit), [Icechunk store](https://molab.marimo.io/github/TUW-GEO/canvodpy-demo/blob/main/11_icechunk_store.py?mode=edit) in molab, the online notebook service of marimo.


---

## Next steps

- [Configuration guide](../guides/configuration.md): every setting.
- [Command line and Python](../guides/api-levels.md): all options of
  `canvodpy run`, and the `Site` and `Pipeline` objects in detail.
- [Command line reference](../api/cli.md): every `canvodpy` command and
  option.
- [Diagnostics](../guides/diagnostics.md): the log files, what to do when
  a run fails, and the performance dashboard.
- [Hemispheric grids](../packages/grids/overview.md): assign the VOD to
  cells of the sky.
- [Storage](../packages/store/overview.md): the history of a store, and
  how to read the observations.

To work on canVODpy itself, see
[Contributor setup](../guides/contributor-setup.md).
