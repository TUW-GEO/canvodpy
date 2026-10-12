# canvod-config

The settings: pydantic models for `canvod-settings.yaml` and the loader
that finds and reads it. Every other package depends on it.

## Where things live

| Path (under `src/canvod/config/`) | What |
|---|---|
| `models/` | One module per section; `models/root.py` (`CanvodConfig`) composes them. `models/base.py`: `_StrictModel` forbids unknown keys, so typos fail |
| `models/sites.py` | Sites, receivers (`reader_format`, `recipe`), VOD analyses |
| `models/storage.py` | Store paths and write strategies |
| `models/preprocessing.py` | Optional preprocessing; `statistics` is reserved, not applied |
| `loader.py` | `get_default_config_dir` (the only lookup of the config folder), `load_config` |
| `templates/` | The template users start from (`just config-init`) |

Background: `docs/guides/configuration.md`, `docs/packages/config/overview.md`.

## Invariants

- **Config folder**: `CANVOD_CONFIG_DIR` (set by `--config-dir`), else
  `config/` of a canvodpy checkout, else `~/.config/canvodpy`. Settings
  file and naming recipes are both read from there.
- The user's `config/canvod-settings.yaml` is never committed.
- **Only entry points load settings.** Library code takes values as
  arguments; a library function calling `load_config()` is a hidden
  default (some remain, being removed step by step; don't add new ones).
- A canopy and its reference record the same file format
  (`mixed_format_error` in `models/sites.py`, the one check used by the
  settings, `config validate` and `run`). Mixed setups are not supported.
- Every new setting has a description on the model, a visible default or
  none, and an entry in the template. Edit the shipped template
  (`src/canvod/config/templates/canvod-settings.yaml.example`) and copy it
  to the repository's `config/canvod-settings.yaml.example`; a test keeps
  the two identical.

## Tests

```bash
just test-package canvod-config
```
