# canvod-readers

GNSS data format readers for canVODpy.

## Features

- **RINEX v3.04 Support**: Complete reader for RINEX v3 observation files
- **Signal IDs**: Unique identifiers for each GNSS signal (SV|BAND|CODE format)
- **xarray Integration**: Convert observations to xarray Datasets
- **Automatic Validation**: Header parsing and epoch completeness checking
- **Memory Efficient**: Lazy iteration through large files
- **Flexible Filtering**: Filter by GNSS system, frequency band, or code type

## Installation

```bash
uv pip install canvod-readers
```

## Configuration (optional)

Readers pull optional defaults (author/email/institution metadata for
dataset attrs, `keep_rnx_vars`, compression settings) from `canvod-config`'s
`load_config()` when available — missing config just falls back to
minimal attrs, it's never required. If you do want those defaults in a
standalone install, point `load_config()` at a settings file with:

- `CANVOD_CONFIG_DIR` — directory containing `canvod-settings.yaml`
- `CANVOD_CONFIG_FILE` — an overlay YAML file merged on top

## Quick Start

```python
from pathlib import Path
from canvod.readers import Rnxv3Obs

# Load RINEX file
filepath = Path("path/to/rinex.25o")
reader = Rnxv3Obs(fpath=filepath)

# Convert to xarray Dataset
dataset = reader.to_ds(keep_rnx_data_vars=["SNR"])

# Filter GPS L1 signals
gps_l1 = dataset.where(
    (dataset.system == 'G') & (dataset.band == 'L1'),
    drop=True
)
```

## Interactive Examples

View interactive examples using marimo notebooks:

```bash
# Edit mode (interactive development)
just marimo

# Presentation mode (read-only)
just marimo-present
```

Or directly:

```bash
uv run marimo edit docs/examples.py
```

## Development

```bash
# Clone repository
git clone https://github.com/nfb2021/canvodpy.git
cd canvodpy/packages/canvod-readers

# Install dependencies
uv sync

# Run tests
just test

# Check code quality
just check
```

## Documentation

- Interactive examples: `docs/examples.py` (marimo notebook)
- [Full documentation](https://canvodpy.eu/packages/readers/overview/)

## License

Apache License 2.0
