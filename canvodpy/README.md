# canvodpy

Umbrella package for the canVODpy GNSS-Transmissometry ecosystem.

Part of the [canVODpy](https://github.com/nfb2021/canvodpy) ecosystem.

## Overview

`canvodpy` is the unified entry point for deriving canopy Vegetation Optical Depth (VOD)
from GNSS Signal-to-Noise Ratio (SNR) observations. It orchestrates the full pipeline
from raw RINEX/SBF files through ephemeris augmentation, hemispheric gridding, and
VOD retrieval via the Tau-Omega radiative transfer model.

Four API levels are available to match your workflow:

| Level | Style | Entry point | Use case |
|---|---|---|---|
| **L1** | Convenience | `process_date()`, `Site` | Quick exploration, notebooks |
| **L2** | Fluent | `FluentWorkflow().read().augment().grid().vod()` | Scripted pipelines |
| **L3** | Low-level | Direct subpackage access | Full control, custom integrations |
| **L4** | Functional | `read_rinex()`, `augment_with_ephemeris()`, ... | Airflow / orchestrators |

## Installation

```bash
# Installs canvodpy + all 11 sub-packages
uv pip install canvodpy
```

## Quick Start

### L1: Convenience (fastest path)

```python
from canvodpy import Site

site = Site("ExampleSite")
result = site.process_date("2025001")
```

### L2: Fluent workflow

```python
import canvodpy

result = (
    canvodpy.workflow("ExampleSite")
    .read("2025001")
    .augment()
    .grid()
    .vod("canopy_01", "reference_01")
    .result()
)
```

### L3: Direct subpackage access

```python
from canvod.readers import Rnxv3Obs
from canvod.auxiliary import AuxDataAugmenter
from canvod.grids import create_hemigrid
from canvod.vod import TauOmegaZerothOrder
from canvod.store import GnssResearchSite
```

### L4: Functional API (Airflow-compatible)

```python
from canvodpy import read_rinex, augment_with_ephemeris, assign_grid_cells

ds = read_rinex("path/to/ROSA01TUW_R_20250010000_01D_01S_AA.rnx")
ds = augment_with_ephemeris(ds, agency="COD")
ds = assign_grid_cells(ds, grid_type="equal_area", resolution=2.0)
```

## Included Packages

Installing `canvodpy` provides access to all 10 sub-packages:

| Package | Namespace | Role |
|---|---|---|
| `canvod-readers` | `canvod.readers` | RINEX v2/v3 and SBF binary readers → `xarray.Dataset` |
| `canvod-auxiliary` | `canvod.auxiliary` | Ephemeris augmentation (SP3/CLK and broadcast) |
| `canvod-grids` | `canvod.grids` | Equal-area hemisphere grid operations |
| `canvod-store` | `canvod.store` | Icechunk/Zarr versioned storage layer |
| `canvod-store-metadata` | `canvod.store_metadata` | FAIR/DataCite/ACDD/STAC metadata lifecycle |
| `canvod-vod` | `canvod.vod` | Tau-Omega VOD retrieval algorithms |
| `canvod-viz` | `canvod.viz` | 2D polar and 3D interactive visualization |
| `canvod-config` | `canvod.config` | Configuration management: YAML loading, Pydantic validation |
| `canvod-utils` | `canvod.utils` | Date/time utilities, processing diagnostics |
| `canvod-ops` | `canvod.ops` | Composable preprocessing operations pipeline |

`canvod-filemap` (virtual renaming for non-canonical receiver filenames) is
an optional extra (`pip install "canvodpy[filemap]"`), published separately
in [canvodpy-extensions](https://github.com/nfb2021/canvodpy-extensions).

## Platform Support

| Platform | Status | Notes |
|---|---|---|
| Linux | Full support | Recommended for production |
| macOS | Full support | Fully tested |
| Windows | WSL only | Native not supported (reserved `aux` name) |

## Configuration

Site and processing configuration lives in YAML files (not committed):

```bash
just config-init      # create config/processing.yaml + sites.yaml + sids.yaml
just config-validate  # validate against Pydantic models
```

Optional NASA CDDIS access (for SP3/CLK ephemeris downloads):

```bash
# config/processing.yaml
credentials:
  nasa_earthdata_acc_mail: your.email@example.com
```

Without credentials, canvodpy uses ESA GSSC (no authentication required).

## Documentation

Full documentation: [canvodpy.eu](https://canvodpy.eu/)

## Development

See the [main repository](https://github.com/nfb2021/canvodpy) for workspace development setup.

```bash
uv sync                    # install all workspace deps
just check                 # lint + format
just test                  # run all tests
```

## License

Apache License 2.0
