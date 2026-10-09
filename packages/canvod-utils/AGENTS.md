# canvod-utils

Small shared tools every package may use: dates, file hashes, the
deprecation decorator, the logging run context. No CLI, no settings.

## Where things live

| Path (under `src/canvod/utils/`) | What |
|---|---|
| `tools/date_utils.py` | `YYYYDOY` and friends |
| `tools/hashing.py` | File hash (the `"File Hash"` attribute) |
| `tools/deprecation.py` | `deprecated` for code, `deprecated_argument` for one argument (both `FutureWarning`) |
| `logging/` | `run_context`, `stage_timer` |
| `plugins.py` | Entry point groups `canvodpy.readers` / `canvodpy.vod_calculators`, `load_plugins`, `PluginError`: the one place plugins are found |

## Invariants

- Lower packages deprecate with this decorator, so a package using it
  lists canvod-utils as a dependency. See the `deprecate` guide.
- Logging: every module uses `structlog.get_logger(__name__)`; no private
  logger wrappers.
- Nothing here imports another canvod package.

## Tests

```bash
just test-package canvod-utils
```
