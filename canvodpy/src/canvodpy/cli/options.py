"""Command-line options shared by the ``canvodpy`` commands."""

from __future__ import annotations

import enum
import os
from pathlib import Path

import typer


def _config_dir(value: str) -> Path:
    """A configuration directory, or the one made from a settings file URL.

    A URL is a settings file in a GitHub repository, pinned to a commit or
    a tag; its configuration directory is made in the cache by
    :func:`canvod.config.remote.resolve_config_dir`.
    """
    from canvod.utils.pinned import PinnedFileError, is_url

    if not is_url(value):
        return Path(value)
    from canvod.config.remote import resolve_config_dir

    try:
        return resolve_config_dir(value)
    except PinnedFileError as exc:
        raise typer.BadParameter(str(exc)) from None


def _local_config_dir(value: str) -> Path:
    """A configuration directory that this command writes to: no URL."""
    from canvod.utils.pinned import is_url

    if is_url(value):
        msg = (
            "This command writes the settings file, so it needs a local "
            "folder. A settings file read from a URL is changed in its "
            "repository."
        )
        raise typer.BadParameter(msg)
    return Path(value)


def _use_config_dir(config_dir: Path | None) -> Path | None:
    """Make ``config_dir`` the configuration directory of this process.

    Sets ``CANVOD_CONFIG_DIR``, which the configuration lookup
    (:func:`canvod.config.loader.get_default_config_dir`) reads first, so
    the settings file and the naming recipes both come from this directory.
    """
    if config_dir is None:
        # A URL in the variable is resolved here too, so a failed fetch is
        # a usage error like one of the option, not a traceback later.
        from canvod.utils.pinned import is_url

        env_dir = os.environ.get("CANVOD_CONFIG_DIR", "")
        if is_url(env_dir):
            config_dir = _config_dir(env_dir)
    if config_dir is not None:
        os.environ["CANVOD_CONFIG_DIR"] = str(config_dir.expanduser().resolve())
    return config_dir


CONFIG_DIR_OPTION = typer.Option(
    "--config-dir",
    "-c",
    help=(
        "Configuration directory, holding canvod-settings.yaml and recipes/, "
        "or the URL of a settings file in a GitHub repository, pinned to a "
        "commit or tag (https://raw.githubusercontent.com/<account>/<repo>/"
        "<commit or refs/tags/tag>/.../canvod-settings.yaml). "
        "Default: $CANVOD_CONFIG_DIR, else config/ of the canvodpy checkout, "
        "else ~/.config/canvodpy."
    ),
    parser=_config_dir,
    callback=_use_config_dir,
    is_eager=True,
    show_default=False,
)

LOCAL_CONFIG_DIR_OPTION = typer.Option(
    "--config-dir",
    "-c",
    help=(
        "Configuration directory, holding canvod-settings.yaml and recipes/. "
        "Default: $CANVOD_CONFIG_DIR, else config/ of the canvodpy checkout, "
        "else ~/.config/canvodpy."
    ),
    parser=_local_config_dir,
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
