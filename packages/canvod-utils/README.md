<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/nfb2021/canvodpy/main/docs/assets/logo/canvodpy_logo_dark_mode.svg">
    <img alt="canVODpy" src="https://raw.githubusercontent.com/nfb2021/canvodpy/main/docs/assets/logo/canvodpy_logo_bright_mode.svg" width="260">
  </picture>
</p>

# canvod-utils

[![PyPI](https://img.shields.io/pypi/v/canvod-utils.svg)](https://pypi.org/project/canvod-utils/)
[![Python](https://img.shields.io/badge/python-3.14-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://github.com/nfb2021/canvodpy/blob/main/LICENSE)
[![DOI](https://img.shields.io/badge/DOI-10.5281%2Fzenodo.18496233-blue)](https://doi.org/10.5281/zenodo.18496233)

**Shared utilities of the canVODpy packages.** `canvod-utils` is a package of
[canVODpy](https://canvodpy.eu/), an open Python ecosystem for
GNSS-Transmissometry canopy VOD retrievals.

## What it does

- Dates as year and day of year, and GPS weeks.
- File hashes, which the store uses to recognize files it already holds.
- The plugin loader, the run identifier, the timing of processing stages, and the decorators that mark code left over from development.

## Install

```bash
uv add canvod-utils
```

Most users install [canvodpy](https://pypi.org/project/canvodpy/), which
includes this package, the command line, and the processing pipeline.
canVODpy requires Python 3.14.

## Example

```python
from canvod.utils.tools import YYYYDOY

print(YYYYDOY.from_str("2025032").date)  # 2025-02-01
```

## Documentation

- [canvod-utils in the canVODpy documentation](https://canvodpy.eu/packages/utils/overview/)
- [Start here](https://canvodpy.eu/users/): from installation to the first VOD

## How to cite

If you use canVODpy, please cite it with its DOI,
[`10.5281/zenodo.18496233`](https://doi.org/10.5281/zenodo.18496233), which always leads to the newest
version. [CITATION.cff](https://github.com/nfb2021/canvodpy/blob/main/CITATION.cff) has the full
citation.

## License

[Apache License 2.0](https://github.com/nfb2021/canvodpy/blob/main/LICENSE)
