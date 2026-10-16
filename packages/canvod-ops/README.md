<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/nfb2021/canvodpy/main/docs/assets/logo/canvodpy_logo_dark_mode.svg">
    <img alt="canVODpy" src="https://raw.githubusercontent.com/nfb2021/canvodpy/main/docs/assets/logo/canvodpy_logo_bright_mode.svg" width="260">
  </picture>
</p>

# canvod-ops

[![PyPI](https://img.shields.io/pypi/v/canvod-ops.svg)](https://pypi.org/project/canvod-ops/)
[![Python](https://img.shields.io/badge/python-3.14-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://github.com/nfb2021/canvodpy/blob/main/LICENSE)
[![DOI](https://img.shields.io/badge/DOI-10.5281%2Fzenodo.18496233-blue)](https://doi.org/10.5281/zenodo.18496233)

**Preprocessing of GNSS observations: temporal aggregation and grid cell assignment.** `canvod-ops` is a package of
[canVODpy](https://canvodpy.eu/), an open Python ecosystem for
GNSS-Transmissometry canopy VOD retrievals.

## What it does

- Applies operations to an observation dataset as a chain: temporal aggregation and grid cell assignment.
- Records what each operation did, for the log book of the store.
- `canvodpy run` applies it only if the `processing.preprocessing` setting is set; without it, the store keeps the observations at the receiver's sampling interval.

## Install

```bash
uv add canvod-ops
```

Most users install [canvodpy](https://pypi.org/project/canvodpy/), which
includes this package, the command line, and the processing pipeline.
canVODpy requires Python 3.14.

## Example

```python
from canvod.readers import Rnxv3Obs
from canvod.ops import Pipeline, TemporalAggregate

ds = Rnxv3Obs(fpath="ROSA01TUW_R_20250011330_15M_05S_AA.rnx").to_ds()
pipeline = Pipeline(
    [TemporalAggregate(freq="1min", method="mean", integer_method="first")]
)
ds_1min, result = pipeline(ds)
```

## Documentation

- [canvod-ops in the canVODpy documentation](https://canvodpy.eu/packages/ops/overview/)
- [Start here](https://canvodpy.eu/users/): from installation to the first VOD

## How to cite

If you use canVODpy, please cite it with its DOI,
[`10.5281/zenodo.18496233`](https://doi.org/10.5281/zenodo.18496233), which always leads to the newest
version. [CITATION.cff](https://github.com/nfb2021/canvodpy/blob/main/CITATION.cff) has the full
citation.

## License

[Apache License 2.0](https://github.com/nfb2021/canvodpy/blob/main/LICENSE)
