<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/TUW-GEO/canvodpy/main/docs/assets/logo/canvodpy_logo_dark_mode.svg">
    <img alt="canVODpy" src="https://raw.githubusercontent.com/TUW-GEO/canvodpy/main/docs/assets/logo/canvodpy_logo_bright_mode.svg" width="260">
  </picture>
</p>

# canvod-viz

[![PyPI](https://img.shields.io/pypi/v/canvod-viz.svg)](https://pypi.org/project/canvod-viz/)
[![Python](https://img.shields.io/badge/python-3.14-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://github.com/TUW-GEO/canvodpy/blob/main/LICENSE)
[![DOI](https://img.shields.io/badge/DOI-10.5281%2Fzenodo.18496233-blue)](https://doi.org/10.5281/zenodo.18496233)

**2D and 3D hemispheric plots of GNSS-T observations and VOD.** `canvod-viz` is a package of
[canVODpy](https://canvodpy.eu/), an open Python ecosystem for
GNSS-Transmissometry canopy VOD retrievals.

## What it does

- Plots grids, observations and VOD on the hemisphere: 2D polar plots with Matplotlib, interactive 3D plots with Plotly.
- Shared color scales and plot styles for both.
- Interactive hemisphere selectors for marimo notebooks with the `widgets` extra.

## Install

```bash
uv add canvod-viz
```

Most users install [canvodpy](https://pypi.org/project/canvodpy/), which
includes this package, the command line, and the processing pipeline.
canVODpy requires Python 3.14.

## Example

```python
from canvod.grids import create_hemigrid
from canvod.viz import HemisphereVisualizer2D

grid = create_hemigrid("equal_area", angular_resolution=5.0)
fig, ax = HemisphereVisualizer2D(grid).plot_grid_patches()
```

## Documentation

- [canvod-viz in the canVODpy documentation](https://canvodpy.eu/packages/viz/overview/)
- [Start here](https://canvodpy.eu/users/): from installation to the first VOD

## How to cite

If you use canVODpy, please cite it with its DOI,
[`10.5281/zenodo.18496233`](https://doi.org/10.5281/zenodo.18496233), which always leads to the newest
version. [CITATION.cff](https://github.com/TUW-GEO/canvodpy/blob/main/CITATION.cff) has the full
citation.

## License

[Apache License 2.0](https://github.com/TUW-GEO/canvodpy/blob/main/LICENSE)
