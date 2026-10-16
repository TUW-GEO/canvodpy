<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/nfb2021/canvodpy/main/docs/assets/logo/canvodpy_logo_dark_mode.svg">
    <img alt="canVODpy" src="https://raw.githubusercontent.com/nfb2021/canvodpy/main/docs/assets/logo/canvodpy_logo_bright_mode.svg" width="260">
  </picture>
</p>

# canvod-preflight

[![PyPI](https://img.shields.io/pypi/v/canvod-preflight.svg)](https://pypi.org/project/canvod-preflight/)
[![Python](https://img.shields.io/badge/python-3.14-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://github.com/nfb2021/canvodpy/blob/main/LICENSE)
[![DOI](https://img.shields.io/badge/DOI-10.5281%2Fzenodo.18496233-blue)](https://doi.org/10.5281/zenodo.18496233)

**The canVOD file name convention for GNSS-T receiver files.** `canvod-preflight` is a package of
[canVODpy](https://canvodpy.eu/), an open Python ecosystem for
GNSS-Transmissometry canopy VOD retrievals.

## What it does

- Defines the canVOD file name, which names site, receiver, start time, period, sampling interval, and file type.
- `CanVODFilename` parses and builds these names.
- `find_overlaps` finds files whose time spans overlap.

## Install

```bash
uv add canvod-preflight
```

Most users install [canvodpy](https://pypi.org/project/canvodpy/), which
includes this package, the command line, and the processing pipeline.
canVODpy requires Python 3.14.

## Example

```python
from canvod.preflight import CanVODFilename

name = CanVODFilename.from_filename("ROSA01TUW_R_20250011330_15M_05S_AA.rnx")
print(name.site, name.receiver_type, name.year, name.doy)  # ROS A 2025 1
```

## Documentation

- [canvod-preflight in the canVODpy documentation](https://canvodpy.eu/packages/naming/overview/)
- [Start here](https://canvodpy.eu/users/): from installation to the first VOD

## How to cite

If you use canVODpy, please cite it with its DOI,
[`10.5281/zenodo.18496233`](https://doi.org/10.5281/zenodo.18496233), which always leads to the newest
version. [CITATION.cff](https://github.com/nfb2021/canvodpy/blob/main/CITATION.cff) has the full
citation.

## License

[Apache License 2.0](https://github.com/nfb2021/canvodpy/blob/main/LICENSE)
