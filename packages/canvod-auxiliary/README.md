<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/TUW-GEO/canvodpy/main/docs/assets/logo/canvodpy_logo_dark_mode.svg">
    <img alt="canVODpy" src="https://raw.githubusercontent.com/TUW-GEO/canvodpy/main/docs/assets/logo/canvodpy_logo_bright_mode.svg" width="260">
  </picture>
</p>

# canvod-auxiliary

[![PyPI](https://img.shields.io/pypi/v/canvod-auxiliary.svg)](https://pypi.org/project/canvod-auxiliary/)
[![Python](https://img.shields.io/badge/python-3.14-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://github.com/TUW-GEO/canvodpy/blob/main/LICENSE)
[![DOI](https://img.shields.io/badge/DOI-10.5281%2Fzenodo.18496233-blue)](https://doi.org/10.5281/zenodo.18496233)

**Satellite orbits and clocks, and the satellite angles of each GNSS observation.** `canvod-auxiliary` is a package of
[canVODpy](https://canvodpy.eu/), an open Python ecosystem for
GNSS-Transmissometry canopy VOD retrievals.

## What it does

- Downloads final orbit and clock products (SP3, CLK) from the analysis centers, or reads the broadcast ephemerides from SBF files.
- Interpolates the satellite positions to the epochs of the observations.
- Computes the polar and azimuth angle of every satellite as seen from the receiver.

## Install

```bash
uv add canvod-auxiliary
```

Most users install [canvodpy](https://pypi.org/project/canvodpy/), which
includes this package, the command line, and the processing pipeline.
canVODpy requires Python 3.14.

## Example

```python
from canvod.auxiliary import Sp3File

sp3 = Sp3File.from_file("COD0MGXFIN_20250010000_01D_05M_ORB.SP3")
print(sp3.data)  # satellite positions and velocities per epoch
```

The product (here CODE final) comes from the prefix of the file name; a
file of a product the registry doesn't list is refused.

## Documentation

- [canvod-auxiliary in the canVODpy documentation](https://canvodpy.eu/packages/auxiliary/overview/)
- [Start here](https://canvodpy.eu/users/): from installation to the first VOD

## How to cite

If you use canVODpy, please cite it with its DOI,
[`10.5281/zenodo.18496233`](https://doi.org/10.5281/zenodo.18496233), which always leads to the newest
version. [CITATION.cff](https://github.com/TUW-GEO/canvodpy/blob/main/CITATION.cff) has the full
citation.

## License

[Apache License 2.0](https://github.com/TUW-GEO/canvodpy/blob/main/LICENSE)
