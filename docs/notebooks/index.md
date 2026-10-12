# Notebooks

Interactive [marimo](https://marimo.io) notebooks covering the full canVODpy pipeline — from raw GNSS file reading to vegetation optical depth retrieval, versioned storage, and visualisation.

---

## Rendered notebooks

Each notebook below is executed for real against real test data at doc-build
time (`marimo export html`) and frozen into a static page — source code
included, exactly as it appears in the editor. This is deliberate rather
than a fallback: marimo's WASM export (`html-wasm`) can run notebooks live
in the browser, but its default "app" mode hides code entirely, and the
alternatives (forcing code visibility, or duplicating code into markdown
text) either don't fit the run mode or make the notebooks harder to
maintain for their primary purpose — being read and adapted as reference
code. WASM is also a non-starter here regardless: these notebooks depend
on Icechunk, which has a Rust-compiled backend, and marimo's WASM runtime
(Pyodide) can only execute pure-Python or WASM-compiled dependencies in
the browser. Every notebook also links to its source on
[molab](https://molab.marimo.io/) for forking
and live editing.

### Run canvodpy

| # | Notebook | Topic | Try it |
|---|---|---|---|
| 01 | Running the Pipeline (CLI) | `canvodpy run`: date ranges, auto-resume, several sites, dry runs | [Notebook](_build/01_cli_pipeline.html){target=_blank} · [source](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/01_cli_pipeline.py) |
| 02 | Configuration & Diagnostics | The settings models, two-track logging, `stage_timer` diagnostics | [Notebook](_build/02_configuration.html){target=_blank} · [source](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/02_configuration.py) |
| 03 | Speedrun: Full Pipeline | Raw GNSS files to VOD in a few cells, in Python | [Notebook](_build/03_convenience_speedrun.html){target=_blank} · [source](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/03_convenience_speedrun.py) |

### The processing chain

| # | Notebook | Topic | Try it |
|---|---|---|---|
| 04 | Naming Convention & Validation | File name parsing and validation | [Notebook](_build/04_naming_convention.html){target=_blank} · [source](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/04_naming_convention.py) |
| 05 | RINEX v3 Observation Reading | RINEX v3.04 to `xarray.Dataset` | [Notebook](_build/05_rinex_reading.html){target=_blank} · [source](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/05_rinex_reading.py) |
| 06 | SBF Binary Reading | Septentrio binary file reading | [Notebook](_build/06_sbf_reading.html){target=_blank} · [source](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/06_sbf_reading.py) |
| 07 | Satellite Catalog | IGS satellite metadata by PRN | [Notebook](_build/07_satellite_catalog.html){target=_blank} · [source](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/07_satellite_catalog.py) |
| 08 | Ephemeris & Coordinate Augmentation | SP3/CLK augmentation, ECEF to polar angle and azimuth | [Notebook](_build/08_ephemeris_coordinates.html){target=_blank} · [source](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/08_ephemeris_coordinates.py) |
| 09 | Hemispheric Grids | Equal-area, equal-angle, geodesic, Fibonacci | [Notebook](_build/09_hemispheric_grids.html){target=_blank} · [source](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/09_hemispheric_grids.py) |
| 10 | VOD Retrieval | The tau-omega model | [Notebook](_build/10_vod_retrieval.html){target=_blank} · [source](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/10_vod_retrieval.py) |

### Stores

| # | Notebook | Topic | Try it |
|---|---|---|---|
| 11 | Icechunk Store | Versioned Icechunk/Zarr storage | [source](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/11_icechunk_store.py) only |
| 12 | Store Metadata & FAIR Compliance | DataCite/ACDD/STAC provenance | [source](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/12_store_metadata.py) only |
| 13 | Store Operations | Branches, writes, history, time travel, store metadata | [source](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/13_workflow_store_operations.py) only |

### Results

| # | Notebook | Topic | Try it |
|---|---|---|---|
| 14 | Visualization | 2D/3D hemisphere plots | [Notebook](_build/14_visualization.html){target=_blank} · [source](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/14_visualization.py) |
| 15 | Grid Exploration | Interactive hemisphere grid explorer | [Notebook](_build/15_grid_exploration.html){target=_blank} · [source](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/15_grid_exploration.py) |
| 16 | 3D Grid Gallery | All hemisphere grid types side by side in 3D | [Notebook](_build/16_grid_3d_gallery.html){target=_blank} · [source](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/16_grid_3d_gallery.py) |

### From Python

| # | Notebook | Topic | Try it |
|---|---|---|---|
| 17 | API Overview | The CLI and `Site.pipeline()` side by side | [Notebook](_build/17_api_overview.html){target=_blank} · [source](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/17_api_overview.py) |
| 18 | Site Pipeline | `Site().pipeline().process_range()`, the path the CLI wraps | [Notebook](_build/18_site_pipeline.html){target=_blank} · [source](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/18_site_pipeline.py) |
| 19 | Single-Day Workflow | One day end to end: read, augment, grid, VOD | [Notebook](_build/19_workflow_single_day.html){target=_blank} · [source](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/19_workflow_single_day.py) |
| 20 | Batch Processing | Many days at once | [Notebook](_build/20_workflow_batch_processing.html){target=_blank} · [source](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/20_workflow_batch_processing.py) |

### Extending canvodpy

| # | Notebook | Topic | Try it |
|---|---|---|---|
| 21 | Your Own VOD Calculator | Register it, compare it, make it a plugin | [source](https://molab.marimo.io/github/nfb2021/canvodpy-demo/blob/main/21_plugins.py) only |

17 of 21 notebooks render here. 11, 12, 13 and 21 use canvodpy code that is
not released yet, so they link to their source only for now.

`scripts/export_demo_notebooks.sh` (`just docs-export-notebooks`) rebuilds them.

---

## Run locally

To run the notebooks interactively, clone (or fork)
[canvodpy-demo](https://github.com/nfb2021/canvodpy-demo) and install
[`uv`](https://docs.astral.sh/uv/getting-started/installation/).

### 1. Clone

```bash
git clone https://github.com/nfb2021/canvodpy-demo.git
cd canvodpy-demo
```

### 2. Run a notebook

Each notebook declares its own dependencies via a [PEP 723](https://peps.python.org/pep-0723/)
header. `uv` resolves and installs them automatically on first run — no `uv sync`
or manual setup required.

```bash
# Interactive editing
uv run marimo edit 10_vod_retrieval.py

# Read-only app mode
uv run marimo run 10_vod_retrieval.py
```

### 3. Test data

Notebooks that read GNSS data download the test dataset (~1.7 GB) automatically
from [Zenodo](https://zenodo.org/records/19708760) on first run and cache it at
`~/.cache/canvodpy/`. Subsequent runs are instant.

To use a local copy instead, clone the test data into `test_data/`:

```bash
git clone https://github.com/nfb2021/canvodpy-test-data.git test_data
```

`_paths.py` detects this directory automatically and skips the Zenodo download.
