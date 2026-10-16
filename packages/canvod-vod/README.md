<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/nfb2021/canvodpy/main/docs/assets/logo/canvodpy_logo_dark_mode.svg">
    <img alt="canVODpy" src="https://raw.githubusercontent.com/nfb2021/canvodpy/main/docs/assets/logo/canvodpy_logo_bright_mode.svg" width="260">
  </picture>
</p>

# canvod-vod

[![PyPI](https://img.shields.io/pypi/v/canvod-vod.svg)](https://pypi.org/project/canvod-vod/)
[![Python](https://img.shields.io/badge/python-3.14-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://github.com/nfb2021/canvodpy/blob/main/LICENSE)
[![DOI](https://img.shields.io/badge/DOI-10.5281%2Fzenodo.18496233-blue)](https://doi.org/10.5281/zenodo.18496233)

**VOD retrieval from a canopy and a reference GNSS receiver.** `canvod-vod` is a package of
[canVODpy](https://canvodpy.eu/), an open Python ecosystem for
GNSS-Transmissometry canopy VOD retrievals.

## What it does

- Computes vegetation optical depth (VOD) from the signal-to-noise ratios of a canopy receiver and a reference receiver, with the zeroth-order tau-omega model.
- Aligns both datasets on their shared epochs and signals.
- Your own VOD calculators can be added as plugins, based on `VODCalculator`.

## Install

```bash
uv add canvod-vod
```

Most users install [canvodpy](https://pypi.org/project/canvodpy/), which
includes this package, the command line, and the processing pipeline.
canVODpy requires Python 3.14.

## Example

```python
from canvod.vod import TauOmegaZerothOrder

# canopy_ds and reference_ds: observations with satellite angles,
# as canvodpy writes them to the GNSS store
vod_ds = TauOmegaZerothOrder.from_datasets(canopy_ds=canopy_ds, sky_ds=reference_ds)
```

## Documentation

- [canvod-vod in the canVODpy documentation](https://canvodpy.eu/packages/vod/overview/)
- [Start here](https://canvodpy.eu/users/): from installation to the first VOD

## How to cite

If you use canVODpy, please cite it with its DOI,
[`10.5281/zenodo.18496233`](https://doi.org/10.5281/zenodo.18496233), which always leads to the newest
version. [CITATION.cff](https://github.com/nfb2021/canvodpy/blob/main/CITATION.cff) has the full
citation.

## License

[Apache License 2.0](https://github.com/nfb2021/canvodpy/blob/main/LICENSE)
