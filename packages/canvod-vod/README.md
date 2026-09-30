# canvod-vod

VOD calculation for GNSS vegetation analysis.

Part of the [canVODpy](https://github.com/nfb2021/canvodpy) ecosystem.

## Overview

This package provides VOD (Vegetation Optical Depth) calculation algorithms based on the Tau-Omega model:
- Zeroth-order approximation (TauOmegaZerothOrder)
- Abstract base class for custom implementations

## Installation

```bash
uv pip install canvod-vod
```

## Quick Start

```python
from canvod.vod import TauOmegaZerothOrder
import xarray as xr

# Load canopy and sky datasets
canopy_ds = xr.open_dataset("canopy.nc")
sky_ds = xr.open_dataset("sky.nc")

# Calculate VOD
vod_ds = TauOmegaZerothOrder.from_datasets(
    canopy_ds=canopy_ds,
    sky_ds=sky_ds,
    align=True
)
```

## Features

- Abstract base class for VOD calculators
- Pydantic validation for input datasets
- Support for both direct dataset and Icechunk store inputs
- Zeroth-order Tau-Omega approximation

## Documentation

[Full documentation](https://canvodpy.eu/packages/vod/overview/)


## License

Apache License 2.0 - see LICENSE file
