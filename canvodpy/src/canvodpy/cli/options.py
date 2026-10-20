"""Command-line options shared by the ``canvodpy`` commands."""

from __future__ import annotations

import enum
import os
from pathlib import Path

import typer


def _use_config_dir(config_dir: Path | None) -> Path | None:
    """Make ``config_dir`` the configuration directory of this process.

    Sets ``CANVOD_CONFIG_DIR``, which the configuration lookup
    (:func:`canvod.config.loader.get_default_config_dir`) reads first, so
    the settings file and the naming recipes both come from this directory.
    """
    if config_dir is not None:
        os.environ["CANVOD_CONFIG_DIR"] = str(config_dir.expanduser().resolve())
    return config_dir


CONFIG_DIR_OPTION = typer.Option(
    "--config-dir",
    "-c",
    help=(
        "Configuration directory, holding canvod-settings.yaml and recipes/. "
        "Default: $CANVOD_CONFIG_DIR, else config/ of the canvodpy checkout, "
        "else ~/.config/canvodpy."
    ),
    callback=_use_config_dir,
    is_eager=True,
    show_default=False,
)


def _use_config_file(config_file: Path | None) -> Path | None:
    """Make ``config_file`` the overlay file of this process.

    Sets ``CANVOD_CONFIG_FILE``, which the settings loader
    (:func:`canvod.config.loader.load_config`) reads, as ``canvodpy run
    --config`` does.
    """
    if config_file is not None:
        if not config_file.exists():
            typer.echo(f"Error: overlay config file not found: {config_file}", err=True)
            raise typer.Exit(1)
        os.environ["CANVOD_CONFIG_FILE"] = str(config_file.expanduser().resolve())
    return config_file


CONFIG_FILE_OPTION = typer.Option(
    "--config",
    help="Settings file whose values replace those of canvod-settings.yaml.",
    callback=_use_config_file,
    is_eager=True,
    show_default=False,
)


def _build_vod_calculator_choice() -> type[enum.StrEnum]:
    """Build the VOD-calculator choice enum from the live factory registry.

    A dynamic StrEnum: Typer renders it as a restricted choice in --help,
    while downstream code can keep treating the value as a plain string
    (calculator_name=args.vod_calculator works unchanged).
    """
    from canvodpy.factories import VODFactory

    names = VODFactory.list_available()
    return enum.StrEnum("VodCalculatorChoice", {name: name for name in names})


VodCalculatorChoice = _build_vod_calculator_choice()
