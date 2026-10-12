# canvod-utils

Shared utilities for canvodpy.

## Features

- **Date/time tools**: `YYYYDOY`/`YYDOY` GNSS date handling, GPS week helpers
- **Validation and hashing**: `isfloat`, `file_hash`

Performance tracing lives in `canvodpy.utils.telemetry` (OpenTelemetry-based),
not here — this package's old `diagnostics` module (timing/memory/dataset/
Airflow tracking, SQLite-backed) was removed 2026-07-14 as a fully dead
chain with zero real callers anywhere in the pipeline.

## Installation

```bash
uv pip install -e packages/canvod-utils
```

## Quick Start

```python
from canvod.utils.tools import YYYYDOY, get_version_from_pyproject, file_hash

date = YYYYDOY.from_str("2025024")
print(date.to_datetime())
```

## Documentation

[Full documentation](https://canvodpy.eu/packages/utils/overview/)

## Development

```bash
# From repo root
uv sync
uv run pytest packages/canvod-utils/tests
just check
```
