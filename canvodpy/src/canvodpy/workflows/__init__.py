"""Workflow definitions for automation (Airflow, Prefect, etc.)."""

from canvodpy.workflows.tasks import (
    calculate_vod,
    check_day,
    check_rinex,
    check_sbf,
    cleanup,
    fetch_aux_data,
    parse_sampling_interval_from_filename,
    process_day,
    process_rinex,
    process_sbf,
    validate_data_dirs,
    validate_ingest,
)

__all__ = [
    "calculate_vod",
    "check_day",
    "check_rinex",
    "check_sbf",
    "cleanup",
    "fetch_aux_data",
    "parse_sampling_interval_from_filename",
    "process_day",
    "process_rinex",
    "process_sbf",
    "validate_data_dirs",
    "validate_ingest",
]
