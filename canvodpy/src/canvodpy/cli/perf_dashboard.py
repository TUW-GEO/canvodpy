"""``canvodpy dashboard``: launch the marimo performance dashboard.

Reads `stage_timing` events (see `canvodpy.logging.stage_timer`) from
`machine/performance*.json` and displays a per-iteration stage breakdown
plus an elapsed-time-per-receiver-per-day view. Works during a live run
(partial data, refresh button to reload) or after it's finished.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Annotated

import typer

_NOTEBOOK_PATH = Path(__file__).parent / "dashboards" / "performance.py"


def dashboard(
    logs_dir: Annotated[
        str | None,
        typer.Option(
            "--logs-dir",
            help=(
                "Log folder of the runs to show. Default: "
                "processing.logging.log_dir in canvod-settings.yaml."
            ),
        ),
    ] = None,
    edit: Annotated[
        bool,
        typer.Option(
            "--edit/--run",
            help="Open in marimo's editor instead of the read-only app view.",
        ),
    ] = False,
    host: Annotated[
        str | None,
        typer.Option(
            "--host", help="Host to bind to. Default: the marimo default, 127.0.0.1."
        ),
    ] = None,
    port: Annotated[
        int | None,
        typer.Option(
            "--port", "-p", help="Port to bind to. Default: a port that marimo picks."
        ),
    ] = None,
) -> None:
    """Launch the marimo performance dashboard for the pipeline's logs."""
    env = os.environ.copy()
    if logs_dir is not None:
        log_dir = Path(logs_dir).expanduser()
    else:
        from canvod.config import load_config
        from canvod.config.models.logging import LogDirNotSetError

        try:
            log_dir = load_config().processing.logging.get_log_dir()
        except LogDirNotSetError as e:
            typer.echo(f"Error: {e}\n\nOr pass the folder with --logs-dir.", err=True)
            raise typer.Exit(code=1) from None
    env["CANVODPY_PERF_LOG_DIR"] = str(log_dir)

    marimo_subcommand = "edit" if edit else "run"
    cmd = [sys.executable, "-m", "marimo", marimo_subcommand, str(_NOTEBOOK_PATH)]
    if host is not None:
        cmd += ["--host", host]
    if port is not None:
        cmd += ["--port", str(port)]
    result = subprocess.run(cmd, env=env, check=False)
    raise typer.Exit(code=result.returncode)
