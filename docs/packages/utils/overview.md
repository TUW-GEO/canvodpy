# canvod-utils

## Purpose

The `canvod-utils` package holds the small tools that the other canVODpy
packages share:

- dates as year and day of year, and GPS weeks;
- file hashes, which the store uses to recognize files it already holds;
- decorators that mark code left over from development;
- the plugin loader, which finds readers and VOD calculators in installed
  packages;
- the run identifier and the timing of the processing stages, which go
  into the logs.

It depends on `pydantic` and `structlog` only. The settings live in
[canvod-config](../config/overview.md), and the `canvodpy` package holds
the [command line](../../api/cli.md).

---

## Tools

```python
from canvod.utils.tools import YYYYDOY, file_hash

YYYYDOY.from_str("2025032").date  # datetime.date(2025, 2, 1)
file_hash(path)  # first 16 hex digits of the file's SHA-256
```

`canvod.utils.tools` provides these functions and classes:

| Name | Purpose |
|---|---|
| `YYYYDOY`, `YYDOY` | Parse and format a date given as year and day of year, for example `2025032` or `25032` |
| `get_gps_week_from_filename` | Read the GPS week from the filename of an orbit or clock product |
| `gpsweekday` | GPS week and day of the week of a date; a date given as a string must be `dd-mm-yyyy` |
| `file_hash` | First 16 hex digits of a file's SHA-256; the store uses it to recognize files it already holds |
| `bytes_hash` | The same hash for file content that is already in memory |
| `isfloat` | Check whether a value can be read as a float |
| `get_version_from_pyproject` | Read a package version from its `pyproject.toml` |
| `deprecated` | Decorator that marks code left over from development: it warns on use and names the replacement |
| `deprecated_argument` | Decorator that marks one argument of a function as left over from development: it warns when the argument is passed |
| `sanitize_directory` | Remove the files that the operating system puts into data folders, for example `.DS_Store` |

---

## Plugins

`canvod.utils.plugins` finds readers and VOD calculators that installed
packages declare as entry points. `plugin_names` lists the plugins of a
group without importing them, `load_plugins` imports them, and
`plugin_package` names the package that declares a plugin. A plugin that
can't be used raises `PluginError`, which names that package. To write a
plugin, see [Your own readers and VOD calculators](../../guides/plugins.md).

---

## Diagnostics

`canvod.utils.logging` holds the run identifier (`get_run_id`, `set_run_id`,
`reset_run_id`, `new_run_id`) and the stage timing (`stage_timer`,
`timed_stage`, `record_stage_timing`, `emit_run_summary`,
`reset_run_stats`), so that every canVODpy package can use them without
depending on canvodpy. The log output is configured by
`canvodpy.logging.configure_logging`. See [Diagnostics](../../guides/diagnostics.md).
