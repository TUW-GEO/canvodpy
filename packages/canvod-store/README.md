# canvod-store

Icechunk storage for GNSS VOD data.

Part of the [canVODpy](https://github.com/nfb2021/canvodpy) ecosystem.

## Overview

This package provides versioned storage for GNSS data using Icechunk, managing:

- **GNSS Store (Level 1)**: Augmented observations per receiver
- **VOD Store (Level 2)**: Analysis products comparing receiver pairs

## Installation

```bash
uv pip install canvod-store
```

## Configuration (optional)

`MyIcechunkStore` and `GnssResearchSite` read
compression/chunking/resource settings from `canvod-config`'s
`load_config()`. In a standalone install outside a canvodpy monorepo
checkout, point it at a settings file with:

- `CANVOD_CONFIG_DIR` — directory containing `canvod-settings.yaml`
- `CANVOD_CONFIG_FILE` — an overlay YAML file merged on top

## Quick Start

```python
from canvod.store import create_gnss_store, GnssResearchSite
from pathlib import Path

# Create stores
gnss_store = create_gnss_store(Path("./gnss_store"))

# Or use site manager
site = GnssResearchSite(site_name="ExampleSite")
```

## Features

- Automatic repository creation/connection
- Group management with validation
- Session management with context managers
- Integrated logging and metadata tracking
- Configurable compression and chunking
- Deduplication support

## Documentation

[Full documentation](https://nfb2021.github.io/canvodpy/packages/store/overview/)

## License

Apache License 2.0 - see LICENSE file
