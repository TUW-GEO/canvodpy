# canvodpy (umbrella package)

The CLI, `Site`/`Pipeline`, the orchestrator that runs one receiver-day
after another, the Airflow tasks and the single VOD implementation. Every
other package is a library this one composes.

## Where things live

| Path (under `src/canvodpy/`) | What |
|---|---|
| `cli/app.py` | The `canvodpy` console script: `run`, `vod`, `vod-reconcile`, `doctor`, `dashboard`, `config ...`, `store ...` |
| `cli/run.py` | `canvodpy run`; resumes from the store's last date when `--start` is omitted |
| `api.py` | `Site`, `Pipeline` (`Site(site).pipeline()`); the deprecated flat functions |
| `orchestrator/discovery.py` | Which files of a receiver a day processes: naming recipe or canonical names, any folder layout; compressed files never (`is_compressed`) |
| `orchestrator/pipeline.py` | `PipelineOrchestrator`: days, receivers, batches; warns `files_not_processed` and `compressed_files_not_processed` |
| `orchestrator/processor.py` | Reads, adds geometry, applies preprocessing, writes the GNSS store |
| `orchestrator/data_check.py` | `canvodpy config validate`: same discovery as a run |
| `vod_computer.py` | `VodComputer`, the only VOD implementation (`site.vod`, `canvodpy run`, `canvodpy vod`, `vod-reconcile`) |
| `workflows/tasks.py` | Airflow tasks; `check_day` and `process_day` run the code of `canvodpy run` |
| `factories.py`, `__init__.py` | `ReaderFactory` and friends; built-in readers are registered in `_register_builtin_components`, then installed plugins in `register_plugins` (`docs/guides/plugins.md`) |

## Invariants

- **One code path.** CLI, `Site.pipeline()` and `process_day` share
  discovery, processing and VOD. A fix in one entry point that the others
  don't get is a bug. Deprecated surfaces (`fluent.py`, `functional.py`,
  `workflow.py`, the flat functions in `api.py`, the per-format Airflow
  tasks, `orchestrator/interpolator.py`) are not fixed or extended.
- **Discovery** picks a receiver's files by the canonical name, or through
  the receiver's naming recipe (`recipe:` setting, canvod-filemap). It
  never guesses with globs. Files it skips are reported, never dropped
  silently.
- **Reference geometry**: in broadcast mode the reference receiver takes
  θ/φ from its own canopy's file, matched by canonical start time.
- **Preprocessing** (`processing.preprocessing`) runs per receiver-day
  through `canvod.ops.preprocess_files` before the store write, only if
  set.
- **The CLI never stops a long run for one bad file**: it warns and goes
  on. Library code raises.
- **Plugins** (installed readers and VOD calculators) are registered when
  canvodpy is imported; a broken plugin raises `PluginError` then. A
  run uses them only when the settings or `--vod-calculator` name them;
  `reader_format: auto` never picks one.
- The CLI lives here only; canvod-utils has no CLI code.

## Before changing public API

canvod-airflow calls `canvodpy.workflows.tasks`, canvod-filemap is called
from `orchestrator/discovery.py`, canvod-adapters imports the contracts.
Search canvodpy-extensions (`extensions:packages/canvod-airflow/src/canvod/airflow`)
before renaming anything here.

## Tests

```bash
just test-package canvodpy
```

`tests/test_package_boundaries.py` keeps lower packages from importing
`canvodpy`.
