---
title: Retrieve VOD
description: Install and configure canVODpy, then retrieve GNSS-T VOD from the command line or from Python.
---

# Retrieve VOD from your GNSS data

You can run canVODpy from the command line or from Python. Both run the
same processing, read the same `canvod-settings.yaml`, and give the same
results. This page covers the setup they share.

## 1. Install canVODpy

To run canVODpy from the command line, install it as a uv tool:

```bash
uv tool install canvodpy
uv tool update-shell   # once: puts the tool folder on your PATH
```

To use canVODpy from Python, add it to your uv project:

```bash
uv add canvodpy
```

In a project, run the command line interface with `uv run canvodpy`.

To update or remove the tool, run `uv tool upgrade canvodpy` or
`uv tool uninstall canvodpy`.

??? note "Run the command line interface from a clone of the repository"

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

## 2. Configure your site

canVODpy reads its settings from one file, `canvod-settings.yaml`, with
three sections:

| Section       | What it sets                                                                             |
| ------------- | ---------------------------------------------------------------------------------------- |
| `sites:`      | Your sites, the folder of each receiver, and the receiver pairs to compute VOD for |
| `processing:` | Metadata, credentials, ephemeris products, storage, and processing parameters            |
| `sids:`       | The signals to keep                                                                      |

Create the file from the template. With `--interactive`, canVODpy asks for
your name, your site, and the folders of your receivers, and writes the
answers into the file:

```bash
canvodpy config init --interactive
```

canVODpy looks for the file in `$CANVOD_CONFIG_DIR`, then in `config/` of a
canVODpy clone, then in `~/.config/canvodpy`. To see which file it uses and
whether it is valid, run:

```bash
canvodpy doctor
```

Before the first run, check that canVODpy finds the files of each
receiver:

```bash
canvodpy config validate --site <site>
```

The check lists the days and files a run would process, the files it
would skip, and the problems that would stop the run.

The [Configuration guide](../guides/configuration.md) describes every
setting, how to override settings with environment variables, and where
canVODpy downloads ephemeris products from.

## Dates

canVODpy names a day by its year and day of year, as a 7-digit string
`YYYYDDD`. For example, `2025001` is January 1, 2025 and `2025032` is
February 1, 2025. GNSS file names use the same format.

## 3. Run

<div class="grid cards" markdown>

-   :fontawesome-solid-terminal: &nbsp; **From the command line**

    ---

    Run whole periods, resume where the last run stopped, and schedule
    runs on a server.

    [:octicons-arrow-right-24: Command line](cli.md){ .md-button .md-button--primary }

-   :fontawesome-brands-python: &nbsp; **From Python**

    ---

    Run `Site.pipeline()` in a script or notebook and work with the
    results directly.

    [:octicons-arrow-right-24: Python](python.md){ .md-button .md-button--primary }

</div>

To work on canVODpy itself, see
[Contributor setup](../guides/contributor-setup.md).
