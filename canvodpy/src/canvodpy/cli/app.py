"""canvodpy console-script entry point.

Composes the config/run/doctor/store/stac subcommands into a single Typer
app. All CLI code lives in this package — the entry point, ``config``,
``run``, ``doctor``, ``store`` and ``stac`` — matching where the rest of
canvodpy's user-facing surface (``Site``, ``Pipeline``)
already lives.
"""

from importlib.metadata import version as _pkg_version
from typing import Annotated

import typer

main_app = typer.Typer(
    name="canvodpy",
    help="Process GNSS observations into VOD and inspect the stores.",
    no_args_is_help=True,
)

from canvodpy.cli.config import config_app  # noqa: E402
from canvodpy.cli.doctor import doctor as doctor_command  # noqa: E402
from canvodpy.cli.perf_dashboard import dashboard as dashboard_command  # noqa: E402
from canvodpy.cli.run import run as run_command  # noqa: E402
from canvodpy.cli.stac import stac_app  # noqa: E402
from canvodpy.cli.store import store_app  # noqa: E402
from canvodpy.cli.vod import vod as vod_command  # noqa: E402
from canvodpy.cli.vod import vod_reconcile as vod_reconcile_command  # noqa: E402

main_app.add_typer(config_app, name="config")
main_app.add_typer(store_app, name="store")
main_app.add_typer(stac_app, name="stac")
main_app.command("run")(run_command)
main_app.command(
    "vod",
    help="Compute VOD for a range of dates from the GNSS store of a site.",
)(vod_command)
main_app.command(
    "vod-reconcile",
    help="List the dates that have observations but no VOD, and compute it with --execute.",
)(vod_reconcile_command)
main_app.command(
    "doctor",
    help="Report canvodpy's version, its environment, and its configuration directory.",
)(doctor_command)
main_app.command(
    "dashboard", help="Launch the marimo performance dashboard for the pipeline's logs."
)(dashboard_command)


def _version_callback(value: bool) -> None:
    if value:
        try:
            typer.echo(f"canvodpy {_pkg_version('canvodpy')}")
        except Exception:
            typer.echo("canvodpy 0.0.0+unknown")
        raise typer.Exit()


@main_app.callback()
def _main_callback(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_version_callback,
            is_eager=True,
            help="Show canvodpy's version and exit.",
        ),
    ] = False,
) -> None:
    """Process GNSS observations into VOD and inspect the stores."""


def main() -> None:
    """Run the CLI entry point."""
    main_app()


if __name__ == "__main__":
    main()
