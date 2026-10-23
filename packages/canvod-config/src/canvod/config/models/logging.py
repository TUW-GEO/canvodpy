"""Logging configuration."""

from __future__ import annotations

import warnings
from pathlib import Path

from pydantic import Field, field_validator, model_validator

from canvod.utils.tools import deprecated

from .base import _StrictModel


class LogDirNotSetError(ValueError):
    """File logging needs ``processing.logging.log_dir``, which is not set."""


class LoggingConfig(_StrictModel):
    """Logging configuration.

    Notes
    -----
    This is a Pydantic model for configuration validation.
    """

    log_dir: Path | None = Field(
        None,
        description=(
            "Folder of the log files. Required for a processing run: a run "
            "stops if it is not set."
        ),
    )
    worker_log_retention_days: int = Field(
        30,
        ge=1,
        description=(
            "Days after which the log files of worker processes are deleted, "
            "counted from their last change. Each worker process writes its "
            "own files, with its process ID in the name."
        ),
    )
    log_file_name: str | None = Field(
        None,
        description=(
            "Left over from development; has no effect. Removed with the next "
            "major version."
        ),
    )
    log_path_depth: int = Field(
        6,
        ge=1,
        le=20,
        description="Number of path components to include in log file references",
    )

    @model_validator(mode="before")
    @classmethod
    def _warn_log_file_name(cls, data: object) -> object:
        if isinstance(data, dict) and data.get("log_file_name") is not None:
            warnings.warn(
                "The logging setting 'log_file_name' is left over from development "
                "and will be removed with the next major version. "
                "It has no effect: the log files have fixed names under 'log_dir'. "
                "Remove it from your settings.",
                FutureWarning,
                stacklevel=2,
            )
        return data

    @field_validator("log_dir", mode="before")
    @classmethod
    def _validate_log_dir(cls, v: object) -> object:
        """Expand ~ and reject the placeholder of the settings template."""
        if isinstance(v, str):
            if v.strip() in {"/path/to/logs", "/path/to/your/logs"}:
                raise ValueError(
                    f"log_dir is set to placeholder {v!r}: "
                    "set a real directory path in canvod-settings.yaml"
                )
            return Path(v).expanduser()
        return v

    def get_log_dir(self) -> Path:
        """Return the log folder, creating it if needed.

        Returns
        -------
        Path
            Log folder.

        Raises
        ------
        LogDirNotSetError
            If ``log_dir`` is not set.
        """
        if self.log_dir is None:
            raise LogDirNotSetError(
                "No log folder set. Set processing.logging.log_dir in "
                "canvod-settings.yaml, for example:\n\n"
                "processing:\n"
                "  logging:\n"
                "    log_dir: /path/to/your/logs"
            )
        self.log_dir.mkdir(parents=True, exist_ok=True)
        return self.log_dir

    @deprecated(
        "`LoggingConfig.get_log_file` is left over from development and will be "
        "removed with the next major version. Use `get_log_dir` instead."
    )
    def get_log_file(self) -> Path:
        """Return a file path in the log folder.

        .. deprecated::
            Use :meth:`get_log_dir` instead.
        """
        return self.get_log_dir() / (self.log_file_name or "canvodpy.log")
