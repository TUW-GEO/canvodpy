---
title: Python Quickstart
description: Drive canVODpy from Python with Site.pipeline() for scripted runs.
---

# Python Quickstart

!!! tip "Just want to run the pipeline as-is?"

    Most users should start with the [CLI](cli.md) instead — it's the
    recommended, complete entrypoint, especially for unattended/HPC runs.
    Come here if you're scripting around canVODpy in Python.

## Installation

```bash
uv add canvodpy
```

This adds canVODpy to your project's own environment.

---

## 1. Configure the project

canVODpy is configured through a **single YAML file** — `config/canvod-settings.yaml`, located in the project root's `config/` directory — with three sections:

| Section       | Purpose                                                                                                                                                                               |
| ------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `sites:`      | Research sites: data root paths, receiver definitions (name, type, directory), and VOD analysis pairs. Each receiver's `directory` is relative to the site's `gnss_site_data_root`.   |
| `processing:` | Processing parameters: metadata, credentials (NASA Earthdata), auxiliary data settings (agency, product type), time aggregation, compression, Icechunk storage, and store strategies. |
| `sids:`       | Signal ID (SID) filtering: choose `all`, a named `preset` (e.g. `default`), or list `custom` SIDs to keep.                                                                            |

Scaffold and validate it the same way regardless of which Python surface
you end up using — see the [CLI Quickstart's configuration
step](cli.md#1-configure-the-project) (`canvodpy config init`,
`canvodpy config init --interactive`, `canvodpy config validate`,
`canvodpy doctor`). Configuration is shared infrastructure, not
CLI-specific.

!!! note "Overriding config without editing files"

    Every setting in `canvod-settings.yaml` can also be overridden by an
    environment variable with the `CANVOD__` prefix (double underscores
    separate nesting levels) — useful on HPC clusters or in CI. See the
    [Configuration Guide](../guides/configuration.md) for the full reference.

---

## 2. Process your first day of data

### `Site.pipeline()` — scripted, stateful runs

The Python-native equivalent of the CLI — same underlying machinery, driven
from a script or notebook instead of the terminal. Good when you're looping
over sites, embedding processing in a larger script, or want interactive
control over a run:

```python
from canvodpy import Site

site = Site("ExampleSite")
with site.pipeline() as pipeline:
    data = pipeline.process_date("2025001")
vod = site.vod.compute_day_all(data)  # every configured analysis
```

`pipeline.process_range(start, end)` and options like `n_workers` on
`.pipeline()` are also available — see the [API Levels guide](../guides/api-levels.md).

!!! warning "Deprecated: `canvodpy.functional`"

    The single-step functions of `canvodpy.functional` (`read_rinex()`,
    `augment_with_ephemeris()`, ...) are left over from development and will
    be removed with the next major version. They are no longer maintained and
    give different results than `canvodpy run`; see the
    [API Levels guide](../guides/api-levels.md#deprecated-canvodpyfunctional).

### Dates: the `YYYYDDD` format

canVODpy identifies days by **year + Day of Year (DOY)**: a 7-digit string
`YYYYDDD`, where `DDD` counts days from 001. For example, `"2025001"` is
1 January 2025 and `"2025032"` is 1 February 2025 — the standard date
convention in GNSS data products.

!!! info "Ephemeris downloads"

    Satellite orbit products (SP3, and by default CLK) are downloaded
    automatically from **ESA GSSC** (no account needed). If you configure
    NASA Earthdata (CDDIS) credentials in `canvod-settings.yaml`, NASA is
    tried first with ESA as fallback. CLK isn't used by the VOD formula —
    set `aux_data.fetch_clock: false` to skip it.

---

Just need to run the pipeline, not script around it? The [CLI
Quickstart](cli.md) is simpler for that.

**Next steps:** [Configuration Guide](../guides/configuration.md) · [API Levels](../guides/api-levels.md)
