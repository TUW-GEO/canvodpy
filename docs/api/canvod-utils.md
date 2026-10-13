# `canvod.utils` API reference

Shared date/time utilities and processing diagnostics. Configuration
management lives in [canvod.config](canvod-config.md) instead.

## Tools

::: canvod.utils.tools
    options:
      members:
        - YYYYDOY
        - YYDOY
        - file_hash
        - get_gps_week_from_filename
        - gpsweekday
        - isfloat
        - get_version_from_pyproject

## Logging

The run identifier and the stage timing; the log output is configured by
`canvodpy.setup_logging` (see [Diagnostics](../guides/diagnostics.md)).

::: canvod.utils.logging
    options:
      members:
        - get_run_id
        - set_run_id
        - reset_run_id
        - new_run_id
        - stage_timer
        - timed_stage
        - record_stage_timing
        - emit_run_summary
