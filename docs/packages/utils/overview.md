# canvod-utils

## Purpose

The `canvod-utils` package provides date/time utilities and processing
diagnostics shared across the canVODpy ecosystem. The settings live in
[canvod-config](../config/overview.md), so `canvod-utils` has no YAML
dependency and no CLI code of its own (it depends on `pydantic` and
`structlog` only).

---

## Tools

```python
from canvod.utils.tools import YYYYDOY, file_hash

YYYYDOY.from_str("2025032").date  # datetime.date(2025, 2, 1)
file_hash(path)  # first 16 hex digits of the file's SHA-256
```

| Function | Purpose |
|---|---|
| `YYYYDOY` / `YYDOY` | Year + Day-of-Year date parsing/formatting (the GNSS-standard date convention) |
| `get_gps_week_from_filename` | Extract GPS week from a standard product filename |
| `gpsweekday` | GPS week and day of week of a date (a string must be `dd-mm-yyyy`) |
| `file_hash` | First 16 hex digits of a file's SHA-256, used by the store's dedup guardrails |
| `isfloat` | Safe float-parsing check |
| `get_version_from_pyproject` | Read a package version directly from `pyproject.toml` |
| `deprecated` | Decorator that marks code left over from development: warns on use and names the replacement |
| `sanitize_directory` | Remove files the OS drops into data folders (e.g. `.DS_Store`) |

---

## Diagnostics

`canvod.utils.logging` holds the run identifier (`get_run_id`, `set_run_id`,
`reset_run_id`) and the stage timing (`stage_timer`, `timed_stage`,
`emit_run_summary`, `reset_run_stats`), so that every canvod package can use them without
depending on canvodpy. The log output is configured by
`canvodpy.logging.configure_logging`. See the [Diagnostics & Performance
Monitoring guide](../../guides/diagnostics.md).

---

## CLI Quick Reference

canVODpy's CLI lives entirely in the `canvodpy` package (see
[canvod-config](../config/overview.md) for `config`/`doctor`, and
[canvod-store](../store/overview.md) for `store`) — collected here for a
one-stop reference:

=== "Setup"

    ```bash
    canvodpy config init                # Scaffold canvod-settings.yaml (recipes: just naming-init SITE NAME)
    canvodpy config init --interactive  # ...or answer a few questions instead of hand-editing YAML
    canvodpy config validate            # Validate configuration
    canvodpy config show                # Display resolved configuration
    canvodpy config edit                # Open canvod-settings.yaml in $EDITOR
    canvodpy doctor                     # Environment + config diagnostics (read-only)
    ```

=== "Development"

    ```bash
    just test             # Run full test suite
    just check            # Lint + format + type-check
    just hooks            # Install pre-commit hooks
    just docs             # Serve documentation locally
    just test-coverage    # Tests with coverage report
    just clean            # Remove build artifacts
    ```

=== "Processing"

    ```bash
    just run SITE START END       # Process days START to END (YYYYDOY) and compute VOD
    canvodpy run --site SITE      # Resume from the last processed day up to today
    canvodpy vod --help           # Compute VOD from an existing GNSS store
    canvodpy vod-reconcile --help # Find days with observations but no VOD
    ```

=== "Store inspection"

    ```bash
    canvodpy store list                    # Every site's gnss/vod store paths + status
    canvodpy store info <site>             # Tree of branches/groups + compression stats
    canvodpy store info <site> --group X   # Full dataset + metadata table for one group
    canvodpy store log <site>              # Commit graph
    canvodpy store log <site> --ops        # Ops audit trail
    canvodpy store maintain <site>         # Snapshot expiry + garbage collection (dry run unless --execute)
    ```
