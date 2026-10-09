---
title: canVODpy
description: An Open Python Ecosystem for GNSS-Transmissometry Canopy VOD Retrievals
hide:
  - navigation
  - toc
---

<div class="hero" markdown>

# canVODpy

**An Open Python Ecosystem for GNSS-Transmissometry Canopy VOD Retrievals**

canVODpy aims to be the central community-driven software suite for deriving
and analyzing canopy Vegetation Optical Depth (VOD) from [GNSS](https://gssc.esa.int/navipedia/index.php/GNSS){:target="_blank"}
signal-to-noise ratio observations.

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.19445061.svg)](https://doi.org/10.5281/zenodo.19445061)
[![PyPI](https://img.shields.io/pypi/v/canvodpy)](https://pypi.org/project/canvodpy/)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![fair-software.eu](https://img.shields.io/badge/fair--software.eu-%E2%97%8F%20%20%E2%97%8F%20%20%E2%97%8F%20%20%E2%97%8F%20%20%E2%97%8F-green)](https://fair-software.eu)
[![OpenSSF Best Practices](https://bestpractices.coreinfrastructure.org/projects/12329/badge)](https://bestpractices.coreinfrastructure.org/projects/12329)
[![OpenSSF Scorecard](https://api.securityscorecards.dev/projects/github.com/nfb2021/canvodpy/badge)](https://securityscorecards.dev/viewer/?uri=github.com/nfb2021/canvodpy)
[![VODnet](https://img.shields.io/badge/-VODnet-2d6a4f?labelColor=555555&logo=data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAA4AAAAOCAYAAAAfSC3RAAAAAXNSR0IArs4c6QAAAHhlWElmTU0AKgAAAAgABAEaAAUAAAABAAAAPgEbAAUAAAABAAAARgEoAAMAAAABAAIAAIdpAAQAAAABAAAATgAAAAAAAABIAAAAAQAAAEgAAAABAAOgAQADAAAAAQABAACgAgAEAAAAAQAAAA6gAwAEAAAAAQAAAA4AAAAAjn8NzQAAAAlwSFlzAAALEwAACxMBAJqcGAAAAflJREFUKBWtUEtoE1EUPe+9SczHiam/aixtqi1E7aai4kK0CAVBDFZwrQs3xp2KIriYtiKuav3QRVxYKIjFVihWrCBIaaWioKidQBsxi3SwYmMmkxidYWaemYEEKUgRPHDhXu4575x3gf+NKfVD3UQ2u/Zv7wrLF8mPfV2ZH1ZCNIM7xUCAHHjyfN6wQ8mZo3vvE4Av57tzOjfd/WZpivfJSW5wkzvomnzFe2SFTyyU+iFJtCpk1eaRfOIw84TuRsN7kEkVMDzyEjPvUtga2YiDTRFM5+m+F8XYHMZuzDqaWlQf8yVMpmJ0/DUu9g6hVNQAy8au3W04NHAV85oFRulZS+LDkIjtWmcyHT6vQHYoXwrouTWKkv4LLOAHE4N4K6dxZ2AISl4DpawVDVrYcXSFZtTPGSV8IatjUVErJ+Cwbdstx3Vw8CG+pmQIHg+HUVlWo7aSp/qz9Kn3W5p5S/x4DJ8/lfGt4kAow7bmBpQ9fuQ3RUFtM4Uz61Qk/vijbpLbgtc61n05zjQ1hCvXHmB9fT3OnT8NOWfi+uxP0IJxE4S4jrXzxrffm1xlb75Aud/cEFmD9vYW6KaNUoUmCpS3BblUPNk45sR0UBM6Qzx2qd9LVnfqujGS+64puaX8olEuj4uMHHnc2dTrcFZGtCOMxv11KxP/kfEbTTzNcyb5ar0AAAAASUVORK5CYII=&logoColor=white)](https://www.gfz.de/en/section/remote-sensing-and-geoinformatics/projects/vodnet)

[Retrieve VOD from your GNSS data :fontawesome-solid-arrow-right:](users/index.md){ .md-button .md-button--primary }
[Contribute to canVODpy :fontawesome-solid-arrow-right:](CONTRIBUTING.md){ .md-button }

</div>

---

## What makes canVODpy different

<div class="grid cards" markdown>

-   :fontawesome-solid-stamp: &nbsp; **Multi-reader support with unified, validated output**

    ---

    Supports RINEX v2.11, RINEX v3.04, Stripped RINEX v3.05, NMEA v4 and Septentrio SBF. Every supported GNSS reader produces a structurally identical, run-time-validated xarray Dataset. Downstream code is reader-agnostic.

    [:octicons-arrow-right-24: Reader Architecture](packages/readers/architecture.md)

-   :fontawesome-solid-database: &nbsp; **Versioned, performant storage, ready for the cloud**

    ---

    Icechunk let's you manage xarray Datasets of your entire network like a database and gives every write a git-like commit snapshot. Scroll through your commit history, branch off into development branches and create immutable tags for releases. Local filesystem storage today, with cloud object-store support on the roadmap.

    [:octicons-arrow-right-24: Storage Engine](packages/store/overview.md)

-   :fontawesome-solid-globe: &nbsp; **Hemispheric grid system**

    ---

    Hemispheric tessellations (equal-area and equal-angle verified; others experimental) defined in 3D, enabling full spatial analyses. Each observation is assigned to the cell that contains it; interactive data exploration.

    [:octicons-arrow-right-24: canvod-grids](packages/grids/overview.md)

-   :fontawesome-solid-rotate: &nbsp; **Fully parallel processing**

    ---

    By default, all file reading and processing is natively parallelized.

    [:octicons-arrow-right-24: Architecture](architecture.md)

-   :fontawesome-solid-shield-halved: &nbsp; **Reliable by design**

    ---

    Field data gets corrupted — power outages, partial writes, stray files. The store actively guards against it: hash- and time-overlap checks block corrupting appends before they happen, and it's the authoritative last line of defense for ingest, not just a passive write target.

    [:octicons-arrow-right-24: Storage Engine](packages/store/overview.md)

-   :fontawesome-solid-fingerprint: &nbsp; **Traceability, top to bottom**

    ---

    FAIR-compliant, OpenSSF-vetted, DOI-versioned releases at the software layer. SHA-256 file hashing and DataCite/ACDD/STAC-aligned provenance metadata at the data layer. Every citable release and every stored dataset is independently traceable.

    [:octicons-arrow-right-24: Store Metadata](packages/store-metadata/overview.md)

</div>

---

## Supported receiver formats

<div class="grid" markdown>

!!! success "RINEX v3.04"

    Text-based standard format from all manufacturers.
    Satellite geometry computed from precise [SP3](https://igs.org/formats-and-standards/){:target="_blank"} [ephemerides](https://gssc.esa.int/navipedia/index.php/Precise_GNSS_Satellite_Coordinates_Computation){:target="_blank"} (CLK clock corrections fetched too, by default — optional).

    **Reader:** `Rnxv3Obs` — all GNSS constellations, all bands

!!! success "Septentrio Binary Format (SBF)"

    Binary format from [Septentrio](https://www.septentrio.com){:target="_blank"} receivers. Includes satellite azimuth and elevation that the receiver computes from
    [broadcast ephemerides](https://gssc.esa.int/navipedia/index.php/GNSS_Broadcast_Orbits){:target="_blank"}
    (SatVisibility block; almanac-based angles are not used) for standalone
    satellite geometry — no SP3/CLK download required.

    **Reader:** `SbfReader` — all GNSS constellations, PVT + DOP metadata

</div>

---

## Quick Start

```bash
uv add canvodpy
```

=== "CLI — running the pipeline"

    Recommended for production runs; resumes automatically:

    ```bash
    canvodpy run --site ExampleSite --start 2025001 --end 2025007
    ```

=== "Site.pipeline() — Python-native"

    Same thing, scripted from Python:

    ```python
    from canvodpy import Site

    site = Site("ExampleSite")
    with site.pipeline() as pipeline:
        data = pipeline.process_date("2025001")
    vod = site.vod.compute_day_all(data)  # every configured analysis
    ```

---

## Processing Pipeline

```mermaid
flowchart TD
    RINEX["RINEX 3.04"] --> PARSE["Parse + SP3 interpolation"]
    SBF["Septentrio SBF"] --> PARSE2["Parse (geometry embedded)"]
    SP3["SP3 (+ CLK, optional)"] --> PARSE
    PARSE --> STORE["Icechunk store"]
    PARSE2 --> STORE
    STORE --> VOD["Tau-Omega VOD retrieval"]
    VOD --> GRID["Hemispheric grid assignment"]
    GRID --> VIZ["Visualisation"]
```

---

## Packages

<div class="grid cards" markdown>

-   :fontawesome-solid-book-open: &nbsp; **canvod-readers**

    ---

    RINEX v3.04 parsing with signal ID mapping.
    Unified `(epoch × sid)` output with full validation.

-   :fontawesome-solid-cloud-arrow-down: &nbsp; **canvod-auxiliary**

    ---

    SP3 ephemeris (and optional CLK clock) retrieval.
    Hermite spline interpolation, FTP fallback chain.

-   :fontawesome-solid-border-all: &nbsp; **canvod-grids**

    ---

    7 hemispheric grid types — equal-area, geodesic, HTM and more.
    Assignment of each observation to the cell that contains it.

-   :fontawesome-solid-leaf: &nbsp; **canvod-vod**

    ---

    VOD estimation via zeroth-order tau-omega model.
    Extensible `VODCalculator` ABC.

-   :fontawesome-solid-database: &nbsp; **canvod-store**

    ---

    Icechunk versioned storage with per-file hash deduplication.
    S3-compatible backends, ACID commits.

-   :fontawesome-solid-chart-line: &nbsp; **canvod-viz**

    ---

    2D polar hemisphere plots and 3D interactive Plotly surfaces.

-   :fontawesome-solid-sliders: &nbsp; **canvod-config**

    ---

    YAML configuration loading with Pydantic validation, XDG-aware
    defaults, and bundled templates.

-   :fontawesome-solid-gear: &nbsp; **canvod-utils**

    ---

    YYYYDOY date utilities, processing diagnostics, shared tooling.

-   :fontawesome-solid-circle-check: &nbsp; **canvod-preflight**

    ---

    The canVOD file name convention: parses and builds canonical
    names, finds files whose time spans overlap.

-   :fontawesome-solid-wand-magic-sparkles: &nbsp; **canvod-ops**

    ---

    Configurable preprocessing pipeline: temporal aggregation,
    grid assignment, extensible Op chain.

-   :fontawesome-solid-stamp: &nbsp; **canvod-store-metadata**

    ---

    Store-level provenance (DataCite, ACDD, STAC), compliance validation,
    inventory builder, STAC catalog export.

-   :fontawesome-solid-circle-nodes: &nbsp; **canvodpy**

    ---

    Umbrella package — CLI, `Site.pipeline()`, the factories for readers,
    grids and VOD calculators.

</div>

---

## Technology

<div class="grid" markdown>

!!! abstract "Scientific stack"

    `xarray` · `NumPy` · `SciPy` · `Polars`

!!! abstract "Storage"

    `Icechunk` · `Zarr` · S3-compatible

!!! abstract "Code quality"

    `ruff` · `ty` · `pytest` · `uv`

!!! abstract "Documentation"

    `Zensical` · `beautiful-mermaid`

!!! abstract "AI-assisted development"

    [`Claude Code`](guides/ai-development.md) · 15+ domain skills · persistent memory · `CLAUDE.md`

</div>

---

## Affiliation

**Climate and Environmental Remote Sensing Research Unit (CLIMERS)**
Department of Geodesy and Geoinformation, TU Wien

[tuwien.at/en/mg/geo/climers](https://www.tuwien.at/en/mg/geo/climers){ .md-button }
