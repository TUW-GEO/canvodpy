<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/TUW-GEO/canvodpy/main/docs/assets/logo/canvodpy_logo_dark_mode.svg">
    <img alt="canVODpy" src="https://raw.githubusercontent.com/TUW-GEO/canvodpy/main/docs/assets/logo/canvodpy_logo_bright_mode.svg" width="260">
  </picture>
</p>

# canvod-store

[![PyPI](https://img.shields.io/pypi/v/canvod-store.svg)](https://pypi.org/project/canvod-store/)
[![Python](https://img.shields.io/badge/python-3.14-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://github.com/TUW-GEO/canvodpy/blob/main/LICENSE)
[![DOI](https://img.shields.io/badge/DOI-10.5281%2Fzenodo.18496233-blue)](https://doi.org/10.5281/zenodo.18496233)

**Versioned Icechunk stores for GNSS-T observations and VOD.** `canvod-store` is a package of
[canVODpy](https://canvodpy.eu/), an open Python ecosystem for
GNSS-Transmissometry canopy VOD retrievals.

## What it does

- Keeps the observations of a site in a GNSS store and its VOD in a VOD store, both [Icechunk](https://icechunk.io/) repositories of Zarr arrays.
- Records every write as a commit, so earlier states of a store stay readable.
- Keeps a log book of which file produced which data, so a file is never stored twice.

## Install

```bash
uv add canvod-store
```

Most users install [canvodpy](https://pypi.org/project/canvodpy/), which
includes this package, the command line, and the processing pipeline.
canVODpy requires Python 3.14.

## Example

```python
from pathlib import Path
from canvod.store import open_gnss_store

store = open_gnss_store(Path("stores/ExampleSite/rinex"))
print(store.list_groups())  # one group per receiver
ds = store.read_group("canopy_01", date="2025001")
```

## Documentation

- [canvod-store in the canVODpy documentation](https://canvodpy.eu/packages/store/overview/)
- [Start here](https://canvodpy.eu/users/): from installation to the first VOD

## How to cite

If you use canVODpy, please cite it with its DOI,
[`10.5281/zenodo.18496233`](https://doi.org/10.5281/zenodo.18496233), which always leads to the newest
version. [CITATION.cff](https://github.com/TUW-GEO/canvodpy/blob/main/CITATION.cff) has the full
citation.

## License

[Apache License 2.0](https://github.com/TUW-GEO/canvodpy/blob/main/LICENSE)
