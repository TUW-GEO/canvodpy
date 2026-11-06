---
title: What's new
description: The changes canVODpy v1.1.0 and v1.0.0 bring, by area
---

# What's new

## v1.1.0

The release notebook shows each change, on the demo data where it can.

[Open the release notebook](https://molab.marimo.io/github/TUW-GEO/canvodpy/blob/main/release-notes/v1.1.0.py){ .md-button .md-button--primary }
[View it on GitHub](https://github.com/TUW-GEO/canvodpy/blob/main/release-notes/v1.1.0.py){ .md-button }

!!! warning "A store created with v1.0.0"

    The orbits are now interpolated with a polynomial of degree 10 by
    default. A store created with v1.0.0 records the cubic Hermite spline
    and refuses runs with the new method: set
    `processing.aux_data.sp3_interpolation: hermite` to keep writing to it,
    or write to a new store
    ([Interpolation methods](packages/auxiliary/interpolation.md)).

<div class="grid cards" markdown>

-   :fontawesome-solid-satellite: &nbsp; **Broadcast ephemeris for RINEX**

    ---

    - `ephemeris_source: broadcast` takes the satellite positions from the
      receiver's RINEX 3.04/3.05 navigation files (`nav_directory`)
    - The ephemeris source `final` is now called `precise`; `final` warns
      until v2.0.0
    - Every run names the satellites it observed without a position

    [:octicons-arrow-right-24: Ephemeris sources](packages/readers/ephemeris-sources.md)

-   :fontawesome-solid-terminal: &nbsp; **Command line**

    ---

    - `canvodpy store log --path` shows the history of any store; `--svg` and
      `--plain` draw it as an image or as plain text
    - `canvodpy logs collect` copies the logs and the run history to send on
    - `canvodpy config validate` checks chosen days and names the days
      without files
    - Colors that follow the terminal, `--help-all`, a dashboard button
      that shuts the dashboard down

    [:octicons-arrow-right-24: Command line](api/cli.md)

-   :fontawesome-solid-play: &nbsp; **Runs**

    ---

    - The days of a unit are prepared in the worker processes, several at
      a time
    - The memory budget counts preparing a day and computing its VOD per
      worker
    - SBAS satellites of SBF files keep their signals; RINEX 2.11 epochs
      that end early are left out

    [:octicons-arrow-right-24: Parallel processing](guides/parallel-processing.md)

</div>

The full list is in the
[changelog](https://github.com/TUW-GEO/canvodpy/blob/main/CHANGELOG.md).

## v1.0.0

!!! warning "Upgrading from 0.x?"

    Stores written with canVODpy 0.x must be migrated before a v1.0.0 run
    writes to them. [Upgrading to v1.0.0](guides/upgrading.md) has the
    commands, the changed settings and what is deprecated.

<div class="grid cards" markdown>

-   :fontawesome-solid-terminal: &nbsp; **A complete command line**

    ---

    - `canvodpy run`, `vod` and `vod-reconcile` process data and compute VOD
    - `canvodpy config` creates, checks, shows and explains the settings
    - `canvodpy store` lists, inspects, maintains, migrates and amends stores
    - `canvodpy stac`, `doctor` and `dashboard`

    [:octicons-arrow-right-24: Command line](api/cli.md)

-   :fontawesome-solid-play: &nbsp; **Runs**

    ---

    - One site per run; `--update-to-latest` for scheduled runs
    - A memory budget sizes the workers and the units of days a run
      commits at once; the next unit is read while VOD is computed
    - Each file's day comes from its name, in any folder layout
    - Warnings about files a run doesn't process and incomplete
      receiver-days
    - Airflow tasks run the same code as `canvodpy run`

    [:octicons-arrow-right-24: Command line and Python](guides/api-levels.md)

-   :fontawesome-solid-database: &nbsp; **Stores**

    ---

    - Day blocks: processing a day again writes only into that day's
      slots; no other day is touched
    - Content settings fixed when a store is created; runs with other
      settings are refused
    - Compare two stores within fixed tolerances
    - Migrate the stores of a 0.x site with one command
    - Stores on S3 (experimental)

    [:octicons-arrow-right-24: Storage](packages/store/overview.md)

-   :fontawesome-solid-fingerprint: &nbsp; **Metadata and catalogs**

    ---

    - Store metadata after DataCite and ACDD, checked against the
      standards
    - A STAC catalog of all stores; releases tag every store
    - Amend a store's description, with a reason
    - `record_machine: false` keeps the computer out of published stores

    [:octicons-arrow-right-24: Store metadata](packages/store-metadata/overview.md)

-   :fontawesome-solid-sliders: &nbsp; **Settings**

    ---

    - Settings and naming recipes from a GitHub link
    - `canvodpy config init --from-store` writes the settings of a store
    - `canvodpy config validate` also checks the receiver data
    - `canvodpy config explain` says what a setting means
    - Preprocessing is applied when set, and recorded in the store

    [:octicons-arrow-right-24: Configuration](guides/configuration.md)

-   :fontawesome-solid-chart-line: &nbsp; **Run history and dashboard**

    ---

    - Every run records itself, its stage timings and its resource use
    - A dashboard shows each run, the sites, and compares runs

    [:octicons-arrow-right-24: Diagnostics](guides/diagnostics.md#the-run-history)

-   :fontawesome-solid-plug: &nbsp; **Extending canVODpy**

    ---

    - Your own readers and VOD calculators, from installed packages
    - Interactive hemisphere selectors for notebooks
    - A public mapping between RINEX observation codes and signal IDs

    [:octicons-arrow-right-24: Plugins](guides/plugins.md)

-   :fontawesome-solid-download: &nbsp; **Demo data**

    ---

    - `canvodpy.demo_data()` downloads the demo day, or its stores, checked
      by sha256
    - Notebooks that run in the browser

    [:octicons-arrow-right-24: Notebooks](https://canvodpy.eu/notebooks/)

</div>

The full list is in [Upgrading to v1.0.0](guides/upgrading.md#new-in-v100)
and the [changelog](https://github.com/TUW-GEO/canvodpy/blob/main/CHANGELOG.md).
