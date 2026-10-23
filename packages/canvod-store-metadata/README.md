<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/TUW-GEO/canvodpy/main/docs/assets/logo/canvodpy_logo_dark_mode.svg">
    <img alt="canVODpy" src="https://raw.githubusercontent.com/TUW-GEO/canvodpy/main/docs/assets/logo/canvodpy_logo_bright_mode.svg" width="260">
  </picture>
</p>

# canvod-store-metadata

[![PyPI](https://img.shields.io/pypi/v/canvod-store-metadata.svg)](https://pypi.org/project/canvod-store-metadata/)
[![Python](https://img.shields.io/badge/python-3.14-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://github.com/TUW-GEO/canvodpy/blob/main/LICENSE)
[![DOI](https://img.shields.io/badge/DOI-10.5281%2Fzenodo.18496233-blue)](https://doi.org/10.5281/zenodo.18496233)

**Store metadata for canVODpy stores, in DataCite, ACDD, and STAC.** `canvod-store-metadata` is a package of
[canVODpy](https://canvodpy.eu/), an open Python ecosystem for
GNSS-Transmissometry canopy VOD retrievals.

## What it does

- Describes a whole store: who made it, with which software and settings, for which site and receivers, and which period it covers.
- Writes the metadata in the vocabularies of DataCite, ACDD, and STAC.
- Reads and checks the metadata of a store, and lists the stores of a folder in a STAC catalog.

## Install

```bash
uv add canvod-store-metadata
```

Most users install [canvodpy](https://pypi.org/project/canvodpy/), which
includes this package, the command line, and the processing pipeline.
canVODpy requires Python 3.14.

## Example

```python
from canvod.store_metadata import read_metadata, show_metadata

meta = read_metadata("stores/ExampleSite/rinex")
print(meta.identity.title)
show_metadata("stores/ExampleSite/rinex")  # every section
```

## Documentation

- [canvod-store-metadata in the canVODpy documentation](https://canvodpy.eu/packages/store-metadata/overview/)
- [Start here](https://canvodpy.eu/users/): from installation to the first VOD

## How to cite

If you use canVODpy, please cite it with its DOI,
[`10.5281/zenodo.18496233`](https://doi.org/10.5281/zenodo.18496233), which always leads to the newest
version. [CITATION.cff](https://github.com/TUW-GEO/canvodpy/blob/main/CITATION.cff) has the full
citation.

## License

[Apache License 2.0](https://github.com/TUW-GEO/canvodpy/blob/main/LICENSE)
