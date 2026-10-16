<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/nfb2021/canvodpy/main/docs/assets/logo/canvodpy_logo_dark_mode.svg">
    <img alt="canVODpy" src="https://raw.githubusercontent.com/nfb2021/canvodpy/main/docs/assets/logo/canvodpy_logo_bright_mode.svg" width="260">
  </picture>
</p>

# canvod-config

[![PyPI](https://img.shields.io/pypi/v/canvod-config.svg)](https://pypi.org/project/canvod-config/)
[![Python](https://img.shields.io/badge/python-3.14-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://github.com/nfb2021/canvodpy/blob/main/LICENSE)
[![DOI](https://img.shields.io/badge/DOI-10.5281%2Fzenodo.18496233-blue)](https://doi.org/10.5281/zenodo.18496233)

**The canVODpy settings file: models, loading, and checks.** `canvod-config` is a package of
[canVODpy](https://canvodpy.eu/), an open Python ecosystem for
GNSS-Transmissometry canopy VOD retrievals.

## What it does

- Reads `canvod-settings.yaml` and checks it with Pydantic models.
- Gives every other canVODpy package its settings.
- `canvodpy config init`, `validate` and `explain` on the command line use it.

## Install

```bash
uv add canvod-config
```

Most users install [canvodpy](https://pypi.org/project/canvodpy/), which
includes this package, the command line, and the processing pipeline.
canVODpy requires Python 3.14.

## Example

```python
from canvod.config import load_config

config = load_config()  # finds canvod-settings.yaml as the command line does
print(config.processing.storage.stores_root_dir)
```

## Documentation

- [canvod-config in the canVODpy documentation](https://canvodpy.eu/packages/config/overview/)
- [Start here](https://canvodpy.eu/users/): from installation to the first VOD

## How to cite

If you use canVODpy, please cite it with its DOI,
[`10.5281/zenodo.18496233`](https://doi.org/10.5281/zenodo.18496233), which always leads to the newest
version. [CITATION.cff](https://github.com/nfb2021/canvodpy/blob/main/CITATION.cff) has the full
citation.

## License

[Apache License 2.0](https://github.com/nfb2021/canvodpy/blob/main/LICENSE)
