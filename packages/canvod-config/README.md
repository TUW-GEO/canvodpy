# canvod-config

Configuration models and YAML loading for canvodpy.

## Features

- **Type-safe configuration**: Pydantic models with validation
- **Single unified settings file**: one `canvod-settings.yaml`, not several
- **CLI tools**: Easy configuration management
- **API-ready**: Same models work for files and APIs

## Installation

```bash
uv pip install -e packages/canvod-config
```

## Quick Start

### 1. Initialize Configuration

```bash
just config-init
# or, for a guided walkthrough:
just config-init-interactive
```

This creates `config/canvod-settings.yaml` — a single file with three
top-level sections: `processing` (metadata, credentials, auxiliary data,
storage, parallelism), `sites` (research sites and receivers), and `sids`
(signal-ID filtering).

### 2. Edit Configuration

```bash
just config-edit
```

Opens `config/canvod-settings.yaml` in `$EDITOR`. Or edit it directly:
- Set `processing.credentials.nasa_earthdata_acc_mail` (optional) for NASA CDDIS access
- Define your research sites under `sites`
- Set `gnss_site_data_root` per site

### 3. Validate Configuration

```bash
just config-validate
```

### 4. Use in Code

```python
from canvod.config import load_config

# Load configuration
config = load_config()

# Access values
print(config.processing.credentials.nasa_earthdata_acc_mail)
print(config.processing.aux_data.agency)

# FTP server selection (auto-detect based on nasa_earthdata_acc_mail)
servers = config.processing.aux_data.get_ftp_servers(
    config.processing.credentials.nasa_earthdata_acc_mail
)
for server_url, auth_email in servers:
    print(f"Server: {server_url}, Auth: {auth_email}")
```

## Configuration Structure

`config/canvod-settings.yaml` — one file, three top-level sections:

```yaml
processing:
  metadata:
    author: Your Name
    email: your.email@example.com
    license: CC-BY-4.0
    # ... DataCite/ACDD provenance fields, written as Zarr store metadata

  credentials:
    nasa_earthdata_acc_mail: null  # optional; prefer the env var override below

  aux_data:
    agency: COD              # Analysis center: COD, GFZ, IGS, ESA, etc.
    product_type: final      # final, rapid, ultra-rapid

  storage:
    stores_root_dir: /path/to/stores

  params:
    resource_mode: auto
    keep_rnx_vars: [SNR]
    # ... science-relevant processing settings

sites:
  examplesite:
    gnss_site_data_root: /path/to/examplesite
    receivers:
      reference_01:
        type: reference
        directory: 01_reference/01_GNSS/01_raw
      canopy_01:
        type: canopy
        directory: 02_canopy/01_GNSS/01_raw
    vod_analyses:
      canopy_01_vs_reference_01:
        canopy_receiver: canopy_01
        reference_receiver: reference_01

sids:
  mode: all  # all, preset, custom
  # preset: gps_galileo
  # custom_sids: [G01|L1|C, G01|L2|W, ...]
```

See `config/canvod-settings.yaml.example` (installed with the package) for
the full, commented template with every field.

## CLI Commands

```bash
# Initialize configuration (scaffold or guided wizard)
just config-init
just config-init-interactive

# Validate configuration
just config-validate

# Show current configuration
just config-show
uv run canvodpy config show --section processing  # filtered view (processing, sites, sids)

# Edit configuration ($EDITOR)
just config-edit
```

## FTP Server Selection

- **If `nasa_earthdata_acc_mail` is set**: NASA CDDIS (primary) → ESA (fallback)
- **If `nasa_earthdata_acc_mail` is null**: ESA only (no authentication)
- ESA server is always available as fallback

## Configuration Priority

1. Package defaults (lowest priority)
2. `canvod-settings.yaml` (user configuration)
3. `CANVOD__...` environment variable overrides (highest priority)

## Resolving the settings file location

Outside a canvodpy monorepo checkout (e.g. a standalone `pip install
canvod-config`), there's no `.git` to find, so `load_config()` falls back to
XDG: `$XDG_CONFIG_HOME/canvodpy`, or `~/.config/canvodpy` if that isn't set.
Two environment variables override this:

- `CANVOD_CONFIG_DIR` — directory containing `canvod-settings.yaml`
- `CANVOD_CONFIG_FILE` — an overlay YAML file merged on top

`canvodpy doctor` reports which of these was actually used for a given run.

## API-Ready Design

Same Pydantic models work for both local files and future API:

```python
# Local development (YAML file)
config = load_config()

# Future API usage (same models!)
@app.post("/process")
def process(config: CanvodConfig):
    return processor.run(config)
```

## Documentation

[Full documentation](https://canvodpy.eu/packages/config/overview/)

## Development

```bash
# From repo root
uv sync
uv run pytest packages/canvod-config/tests
just check
```
