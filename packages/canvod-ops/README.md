# canvod-ops

Composable preprocessing operations pipeline for GNSS-Transmissometry.

Part of the [canVODpy](https://github.com/nfb2021/canvodpy) ecosystem.

## Overview

`canvod-ops` provides a modular `Op`-based pipeline for applying preprocessing
steps to GNSS datasets. Operations are composable and chainable via `Pipeline`.

## Key components

| Component | Purpose |
|---|---|
| `Op` | Abstract base class for all operations |
| `TemporalAggregate` | Aggregates observations into regular time bins |
| `GridAssignment` | Assigns satellite observations to hemispherical grid cells |
| `preprocess_files` | Applies `processing.preprocessing` to one receiver's files of a day |
| `Pipeline` | Chains operations and returns `PipelineResult` |

## Installation

```bash
uv add canvod-ops
```

## Configuration

`canvodpy run`, the Python API and Airflow apply these operations before
writing to the GNSS store if the `processing.preprocessing` section of
`canvod-settings.yaml` sets them; nothing is applied unless it is set.
`build_default_pipeline()` builds that pipeline. In a standalone install
outside a canvodpy monorepo checkout, point it at a settings file with:

- `CANVOD_CONFIG_DIR` — directory containing `canvod-settings.yaml`
- `CANVOD_CONFIG_FILE` — an overlay YAML file merged on top

## Quick Start

```python
from canvod.ops import GridAssignment, Pipeline, TemporalAggregate

pipeline = Pipeline(
    [
        TemporalAggregate(freq="1min", method="mean", integer_method="first"),
        GridAssignment(grid_type="equal_area", angular_resolution=2.0),
    ]
)
ds_out, result = pipeline(ds)
```

## Documentation

[Full documentation](https://canvodpy.eu/packages/ops/overview/)

## License

Apache License 2.0
