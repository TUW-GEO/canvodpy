# canvod-grids

Equal-area hemisphere grid operations for GNSS-Transmissometry.

Part of the [canVODpy](https://github.com/nfb2021/canvodpy) ecosystem.

## Overview

`canvod-grids` provides the spatial discretization layer for GNSS-T. Satellite
signal paths are assigned to equal-area grid cells on the hemisphere above the
receiver based on their polar angle (θ) and azimuth (φ). The primary grid type
for GNSS-T is the **equal-area** grid, where each 2° band is divided into cells
of equal solid angle.

Seven grid types are available: `equal_area`, `equal_angle`, `equirectangular`,
`htm`, `geodesic`, `fibonacci`, and `healpix`. All seven pass a dedicated
correctness test suite (solid-angle sum, no below-horizon cells, no seam
artifacts, structural invariants) — but `equal_area` remains the only type
recommended for production VOD analysis; `equal_angle`/`equirectangular` are
zenith-biased by design, and the others trade strict equal-area for other
properties (see the [package docs](https://canvodpy.eu/packages/grids/overview/)
for the per-type tradeoffs).

## Installation

```bash
uv pip install canvod-grids
```

`healpix` additionally requires [`healpy`](https://healpy.readthedocs.io/),
which is **not** installed by the above (no Windows wheels on PyPI, so it
isn't a hard dependency of this package): `pip install healpy` /
`uv pip install healpy` separately. `create_hemigrid("healpix", ...)` raises
`ImportError` with the same instructions if it's missing.

## Quick Start

```python
from canvod.grids import create_hemigrid, GridType

# Create a 2° equal-area hemisphere grid
grid = create_hemigrid(grid_type=GridType.EQUAL_AREA, resolution=2.0)
print(grid.ncells)  # number of grid cells

# Assign satellite observations to cells
from canvod.grids import CellAggregator
agg = CellAggregator(grid)
per_cell = agg.aggregate(ds, variable="vod", method="median")
```

## Documentation

[Full documentation](https://canvodpy.eu/packages/grids/overview/)

## Development

See the [main repository](https://github.com/nfb2021/canvodpy) for workspace development setup.

## License

Apache License 2.0

## Author & Affiliation

**Nicolas François Bader**
Climate and Environmental Remote Sensing Research Unit (CLIMERS)
Department of Geodesy and Geoinformation
TU Wien (Vienna University of Technology)
Email: support@canvodpy.eu
[https://www.tuwien.at/en/mg/geo/climers](https://www.tuwien.at/en/mg/geo/climers)
