---
title: Architecture
description: Architecture of the canVODpy monorepo — package organization and end-to-end data flow
---

# Architecture

## Overview

canVODpy is organized as a monorepo of eleven Python packages plus the umbrella package `canvodpy`, for GNSS vegetation optical depth analysis. All packages reside in a single repository while maintaining technical independence: each can be developed, tested, and published separately.

!!! info "Core technologies, in plain language"

    canVODpy is built on three open-source foundations. If you are new to them:

    - **xarray** — labeled N-dimensional arrays. Think of a NumPy array where every
      dimension has a name and coordinates: instead of `data[3812, 47]` you write
      `data.sel(epoch="2025-01-01T12:00", sid="G01|L1|C")`. All canVODpy datasets
      carry two dimensions: `epoch` (observation timestamps) and `sid` (signal
      identifier, `SV|Band|Code`, e.g. `G01|L1|C` — satellite G01, band L1, tracking code C).
    - **Zarr** — chunked, compressed array storage for datasets too large for memory.
      Conceptually similar to HDF5/NetCDF, but designed for cloud object storage and
      parallel access.
    - **Icechunk** — a transactional, versioned layer on top of Zarr. Every write ends
      with a **commit**: an immutable snapshot of the entire store, exactly like a git
      commit. You can list the history, check out any past snapshot, and branch —
      so a processing mistake never destroys data, and every published result can
      cite the precise store version it was computed from. canVODpy uses the
      Icechunk v2 API (`repo.writable_session()` → write → `session.commit()`).

---

## Package Layers

```mermaid
graph TD
    subgraph ORCHESTRATION["Orchestration"]
        CANVODPY["canvodpy"]
    end

    subgraph COMPUTE["Computation"]
        VOD["canvod-vod"]
        GRIDS["canvod-grids"]
        OPS["canvod-ops"]
    end

    subgraph STORE_LAYER["Persistence"]
        STORE["canvod-store"]
        STOREMETA["canvod-store-metadata"]
    end

    subgraph DATAIO["Data I/O"]
        READERS["canvod-readers"]
        AUX["canvod-auxiliary"]
    end

    subgraph PRESENT["Presentation"]
        VIZ["canvod-viz"]
    end

    subgraph QA["Quality Assurance"]
        PREFLIGHT["canvod-preflight"]
    end

    subgraph FOUNDATION["Foundation"]
        CONFIG["canvod-config"]
        UTILS["canvod-utils"]
    end

    CANVODPY --> READERS & AUX
    CANVODPY --> STORE & STOREMETA
    CANVODPY --> VOD & GRIDS & OPS & VIZ
    CANVODPY --> CONFIG & PREFLIGHT & UTILS

    READERS -.-> CONFIG & UTILS
    AUX -.-> CONFIG & READERS & UTILS
    STORE -.-> AUX & CONFIG & GRIDS & READERS & UTILS & VOD
    GRIDS -.-> STORE & UTILS
    OPS -.-> CONFIG & GRIDS
    VIZ -.-> GRIDS
    STOREMETA -.-> CONFIG
    VOD -.-> UTILS
    PREFLIGHT -.-> UTILS
    CONFIG -.-> UTILS
```

| Layer | Packages | Role |
|-------|----------|------|
| **Orchestration** | canvodpy | CLI (`canvodpy run`), `Site`/`Pipeline`, the orchestrator, Airflow tasks, VOD computation (`VodComputer`) |
| **Computation** | canvod-vod, canvod-grids, canvod-ops | VOD retrieval (tau-omega model), hemispheric grids, optional preprocessing |
| **Persistence** | canvod-store, canvod-store-metadata | Icechunk versioned storage, three-layer deduplication, provenance metadata (DataCite/ACDD/STAC) |
| **Data I/O** | canvod-readers, canvod-auxiliary | RINEX 2/3, SBF and NMEA readers and the dataset contracts; orbits and clocks (SP3/CLK or broadcast), θ/φ |
| **Presentation** | canvod-viz | 2D polar projections, 3D interactive surfaces, store viewer |
| **Quality Assurance** | canvod-preflight | The canonical file name convention: parsing, building, overlap detection |
| **Foundation** | canvod-config, canvod-utils | Settings models and loading; dates, file hashes, the deprecation decorator, logging context |

Three more packages are optional and live in
[canvodpy-extensions](https://github.com/nfb2021/canvodpy-extensions), installed
from GitHub: `canvod-filemap` (naming recipes for other file names),
`canvod-airflow` (Airflow DAGs) and `canvod-adapters` (data exchange with other
GNSS-T programs). See [Extensions](guides/extensions.md).

---

## Key Design Decisions

<div class="grid cards" markdown>

-   :fontawesome-solid-cubes: &nbsp; **Namespace Packages**

    ---

    All packages share the `canvod.*` namespace — a coherent import API
    backed by separate installable packages:

    ```python
    from canvod.readers import Rnxv3Obs
    from canvod.readers.sbf import SbfReader
    from canvod.grids import EqualAreaBuilder
    from canvod.vod import TauOmegaZerothOrder
    ```

    [:octicons-arrow-right-24: Namespace details](namespace-packages.md)

-   :fontawesome-solid-lock: &nbsp; **Workspace Architecture**

    ---

    One `uv sync` installs all packages in editable mode with a shared lockfile.
    Dependencies are resolved together — no version conflicts possible.

    Each package keeps its own `pyproject.toml` for independent PyPI publishing.

-   :fontawesome-solid-plug: &nbsp; **Independent Install**

    ---

    Install only what you need:

    ```bash
    pip install canvod-readers          # Readers only
    pip install canvod-grids canvod-vod # Grid + VOD
    pip install canvodpy                # Everything
    ```

-   :fontawesome-solid-sitemap: &nbsp; **Layered Dependency Graph**

    ---

    `canvod-utils` has no inter-package dependency; `canvod-config`,
    `canvod-vod` and `canvod-preflight` depend on it only. The remaining
    packages build on them in shallow layers; only the umbrella package
    depends on everything. No package imports the umbrella package.

</div>

---

## Directory Structure

```
canvodpy/                           # Repository root
  packages/                         # Independent packages
    canvod-readers/
      src/
        canvod/                     # Namespace root (no __init__.py)
          readers/                  # Package code
            __init__.py

      tests/
      pyproject.toml
    canvod-auxiliary/               # Same structure
    canvod-grids/
    canvod-vod/
    canvod-store/
    canvod-store-metadata/
    canvod-viz/
    canvod-config/
    canvod-utils/
    canvod-ops/
    canvod-preflight/
  canvodpy/                         # Umbrella package
    src/
      canvodpy/
        __init__.py                 # Re-exports all subpackages
  docs/                             # Centralized documentation
  pyproject.toml                    # uv workspace config
  uv.lock                           # Shared lockfile
  Justfile                          # Task runner
```

---

## Dependency Graph

Inter-package dependencies as declared in each package's `pyproject.toml`:

```
canvod-utils            ──── no inter-package deps
canvod-config           ──── depends on canvod-utils
canvod-preflight        ──── depends on canvod-utils
canvod-vod              ──── depends on canvod-utils
canvod-readers          ──── depends on canvod-config, canvod-utils
canvod-auxiliary        ──── depends on canvod-config, canvod-readers, canvod-utils
canvod-grids            ──── depends on canvod-store, canvod-utils (and canvod-store on
                              canvod-grids: a cycle, to be removed)
canvod-store            ──── depends on canvod-auxiliary, canvod-config, canvod-grids,
                              canvod-readers, canvod-utils, canvod-vod
canvod-store-metadata   ──── depends on canvod-config
canvod-viz              ──── depends on canvod-grids
canvod-ops              ──── depends on canvod-config, canvod-grids
canvodpy                ──── depends on all core packages
```

---

## Complete Processing Flow

The pipeline turns raw GNSS receiver files into gridded vegetation optical
depth. Each stage exists for a scientific reason, summarized below the diagram.

```mermaid
flowchart TD
    subgraph CFG["Configuration"]
        YAML["`**canvod-settings.yaml**
        unified config file`"]
        PYDANTIC["`**Pydantic Validation**
        CanvodConfig (BaseSettings)
        CANVOD__ env overrides`"]
    end

    subgraph INIT["Site Initialization"]
        SITE["Site(name)"]
        GNSS_STORE["GNSS Icechunk Store"]
        VOD_STORE["VOD Icechunk Store"]
    end

    subgraph DISCOVERY["Data Discovery"]
        MAPPER["`**File discovery**
        canonical names or recipe`"]
        VALIDATOR["`**Receiver checks**
        no duplicates or overlaps`"]
        SCHEDULE["Processing Schedule"]
    end

    subgraph AUX["Auxiliary Pipeline (agency ephemeris)"]
        FTP["`**FTP Download**
        ESA primary / NASA CDDIS fallback`"]
        HERMITE["`**Hermite Interpolation**
        SP3 orbits`"]
        LINEAR["`**Piecewise Linear**
        CLK corrections`"]
        AUX_ZARR["Auxiliary Zarr Cache"]
    end

    subgraph PARALLEL["Parallel Processing"]
        READ_R["`**Read GNSS files**
        one task per file, process pool`"]
        SPHERICAL["`**Spherical Coords**
        ECEF to r, theta, phi
        or SBF embedded geometry`"]
    end

    subgraph WRITE["Icechunk Storage (sequential)"]
        DEDUP["`**Three-Layer Dedup**
        hash / temporal / intra-batch`"]
        APPEND["`**Append + Commit**
        one writer, commits per day`"]
    end

    subgraph PREP["Optional preprocessing (only if set)"]
        AGG["`**Temporal aggregation**
        time bins from 00:00`"]
        KDTREE["`**Grid assignment**
        cell containing each observation`"]
    end

    subgraph VOD["VOD Retrieval (VodComputer)"]
        DELTA["delta SNR canopy - ref"]
        TAU["VOD = -ln(T) cos(theta)"]
    end

    YAML --> PYDANTIC --> SITE
    SITE --> GNSS_STORE & VOD_STORE

    PYDANTIC --> MAPPER --> VALIDATOR --> SCHEDULE

    SCHEDULE --> FTP --> HERMITE & LINEAR --> AUX_ZARR

    SCHEDULE --> READ_R --> SPHERICAL
    AUX_ZARR --> SPHERICAL

    SPHERICAL -.-> AGG -.-> KDTREE -.-> DEDUP
    SPHERICAL --> DEDUP --> APPEND --> GNSS_STORE

    GNSS_STORE --> DELTA --> TAU
    TAU --> VOD_STORE
```

### Why each stage exists

| Stage | What it does | Why it matters scientifically |
|-------|--------------|-------------------------------|
| **Configuration** | A single `canvod-settings.yaml` is validated by `CanvodConfig`, a Pydantic `BaseSettings` model; unknown keys are errors; any field can be overridden via `CANVOD__`-prefixed environment variables | Every run is fully described by one validated document — a prerequisite for reproducible processing |
| **Data discovery** | Each receiver directory is scanned in any folder layout; files are selected by their canonical names or mapped to them by a naming recipe; the reader comes from `reader_format` or is detected per day; runs with duplicate or temporally overlapping files, or with files of two receivers in one directory, are stopped; files a run does not process are reported | Overlapping input files would double-count observations and bias SNR statistics; the gate makes this impossible |
| **Auxiliary pipeline** | Downloads agency orbit (SP3) and, by default, clock (CLK) products from public data centers (ESA; NASA CDDIS as fallback once a free NASA Earthdata account is configured), then interpolates them once per day onto the epoch grid (00:00 plus multiples of the sampling interval): Hermite splines for orbits, piecewise linear for clocks | Satellite positions are needed to compute where each signal pierced the canopy (θ, φ); receivers only record *what* they saw, not *where from*. Alternatively, SBF files carry broadcast ephemeris, avoiding the download. Clock is orbit-independent and unused by the VOD formula — disable with `aux_data.fetch_clock: false` to skip its download/interpolation entirely |
| **Reading & transform** | RINEX 2/3, SBF or NMEA files are parsed into `xarray.Dataset(epoch, sid)`; satellite ECEF positions become receiver-relative spherical coordinates (r, θ, φ), relative to the receiver position read from the data | The polar angle θ enters the VOD formula directly; azimuth φ locates the observation on the hemisphere for gridding |
| **Optional preprocessing** | Only if `processing.preprocessing` is set: temporal aggregation and grid assignment before the store write, in every run | Off by default; each write records the preprocessing in the stores' log books, and a store group never mixes data preprocessed differently |
| **Storage** | Datasets are appended to an Icechunk store; three deduplication layers (file-hash match, temporal overlap vs. store metadata, intra-batch overlap) guard every write; with the default write strategy one commit holds all receivers of a day | Duplicate epochs would corrupt the canopy/reference alignment. Each commit is an immutable, citable snapshot of the archive |
| **Grid assignment** | For analysis (or as optional preprocessing), a hemispheric grid is built and each observation is assigned to the cell that contains it (`canvod.grids.add_cell_ids_to_ds_fast`) | Canopy structure varies with direction; gridding lets VOD be resolved per sky sector rather than smeared over the hemisphere |
| **VOD retrieval** | `VodComputer` reads canopy and reference from the GNSS store and aligns them by (epoch, sid); transmittance T follows from their SNR difference, and VOD = −ln(T)·cos(θ) (zeroth-order tau-omega model); results go to the VOD store, which checks the VOD dataset contract | This is the core measurement: canopy attenuation of L-band signals, a proxy for biomass and vegetation water content |

### Parallelism model

- **Reading is parallel.** The files of a batch of days (`days_per_batch`) are
  read in a pool of worker processes ([loky](https://github.com/joblib/loky),
  reused across batches), one task per file, so parsing uses all cores.
  `--workers` or the settings set the pool size.
- **Writing is serial.** Results are written as soon as all files of a
  receiver-day are read, by one process. On a local or network file system
  Icechunk cannot detect two commits at once, so there is exactly one writer:
  with the default write strategy (`skip`) the receivers of a day are written
  into forks of one session, merged and committed once; with `overwrite`,
  one commit per receiver. The deduplication checks therefore always see a
  consistent store.

### Hemispheric grids

`canvod-grids` provides several grid tessellations for hemispheric VOD
analysis. **Equal-area** (ring-based, equal solid angle; the default) and
**equal-angle** (regular θ/φ spacing) are verified correct and safe to use
for analysis. The remaining tessellations (geodesic, HTM, Fibonacci,
equirectangular, HEALPix) are implemented but not yet verified against a
reference and should be treated as experimental pending that check.
HEALPix needs the optional `healpy` package. Equal-area cells
matter because a fixed solid angle per cell means each cell receives a
comparable observation density, avoiding polar oversampling artifacts in
VOD maps.

### API levels

One supported surface, plus the CLI on top of it:

| Surface | Entry point | Use case |
|-------|-------------|----------|
| CLI | `canvodpy run --site ...` | Running the pipeline — recommended |
| `Site.pipeline()` (L3) | `Site(name).pipeline()` | Python-native configured pipeline runs — what the CLI wraps |
| Airflow tasks | `canvodpy.workflows.tasks.check_day`, `process_day` | Scheduled daily runs (canvod-airflow); the same code as the CLI |

`FluentWorkflow` (L2), the flat `process_date()`/`calculate_vod()`/`preview_processing()`
functions (L1), `VODWorkflow`, and the single-step functions of `canvodpy.functional` (L4)
are deprecated — see [API Levels](guides/api-levels.md)
for details and migration notes.

---

## Trade-offs

!!! success "Advantages"

    - Clear separation of concerns between packages
    - Users install only the components they need
    - Independent testing and development per package
    - Smaller dependency trees for individual packages

!!! warning "Costs"

    - Additional `pyproject.toml` per package
    - Developers must understand the namespace package mechanism
    - Coordinated releases required for consistent versioning

---

**Next in the trail:** [Design Principles](principles.md) · [API Levels](guides/api-levels.md) · [Contributor Setup](guides/contributor-setup.md) · [Developing with coding agents](guides/ai-development.md)
