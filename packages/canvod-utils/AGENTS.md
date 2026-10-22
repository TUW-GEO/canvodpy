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
| `pinned.py` | Files from a raw GitHub link pinned to a commit or tag: URL check, token from `GH_TOKEN`/`GITHUB_TOKEN`, per-user cache. canvod-filemap's recipe URLs use it |
| `testing.py` | Made-up people, sites and settings for tests; `PinnedFileServer` stands in for GitHub |
| `plugins.py` | Entry point groups `canvodpy.readers` / `canvodpy.vod_calculators`, `load_plugins`, `PluginError`: the one place plugins are found |

## Invariants

- Lower packages deprecate with this decorator, so a package using it
  lists canvod-utils as a dependency. See the `deprecate` guide.
- Logging: every module uses `structlog.get_logger(__name__)`; no private
  logger wrappers.
- Nothing here imports another canvod package.
- `pinned.py`: a token never appears in a message, a log or a redirect;
  a branch is never a pin. Tests send downloads to
  `testing.PinnedFileServer`, never to the network.

## Tests

```bash
just test-package canvod-utils
```
