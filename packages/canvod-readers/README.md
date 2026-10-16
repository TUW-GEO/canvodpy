<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/nfb2021/canvodpy/main/docs/assets/logo/canvodpy_logo_dark_mode.svg">
    <img alt="canVODpy" src="https://raw.githubusercontent.com/nfb2021/canvodpy/main/docs/assets/logo/canvodpy_logo_bright_mode.svg" width="260">
  </picture>
</p>

# canvod-readers

[![PyPI](https://img.shields.io/pypi/v/canvod-readers.svg)](https://pypi.org/project/canvod-readers/)
[![Python](https://img.shields.io/badge/python-3.14-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://github.com/nfb2021/canvodpy/blob/main/LICENSE)
[![DOI](https://img.shields.io/badge/DOI-10.5281%2Fzenodo.18496233-blue)](https://doi.org/10.5281/zenodo.18496233)

**Readers for GNSS observation files: RINEX, SBF, and NMEA.** `canvod-readers` is a package of
[canVODpy](https://canvodpy.eu/), an open Python ecosystem for
GNSS-Transmissometry canopy VOD retrievals.

## What it does

- Reads RINEX v2.11, RINEX v3.04, stripped RINEX v3.05, NMEA v4.00 and Septentrio binary (SBF) files.
- Every reader returns the same validated xarray Dataset, with one value per epoch and signal, so the rest of canVODpy never depends on the file format.
- Your own readers can be added as plugins.

## Install

```bash
uv add canvod-readers
```

Most users install [canvodpy](https://pypi.org/project/canvodpy/), which
includes this package, the command line, and the processing pipeline.
canVODpy requires Python 3.14.

## Example

```python
from canvod.readers import Rnxv3Obs

ds = Rnxv3Obs(fpath="ROSA01TUW_R_20250011330_15M_05S_AA.rnx").to_ds()
print(ds["SNR"].dims)  # ('epoch', 'sid')
```

## Documentation

- [canvod-readers in the canVODpy documentation](https://canvodpy.eu/packages/readers/overview/)
- [Start here](https://canvodpy.eu/users/): from installation to the first VOD

## How to cite

If you use canVODpy, please cite it with its DOI,
[`10.5281/zenodo.18496233`](https://doi.org/10.5281/zenodo.18496233), which always leads to the newest
version. [CITATION.cff](https://github.com/nfb2021/canvodpy/blob/main/CITATION.cff) has the full
citation.

## License

[Apache License 2.0](https://github.com/nfb2021/canvodpy/blob/main/LICENSE)
