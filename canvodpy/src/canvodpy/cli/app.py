"""canvodpy console-script entry point.

Composes the config/run/doctor/store/stac subcommands into a single Typer
app. All CLI code lives in this package — the entry point, ``config``,
``run``, ``doctor``, ``store`` and ``stac`` — matching where the rest of
canvodpy's user-facing surface (``Site``, ``Pipeline``)
already lives.
"""

import functools
import shutil
import textwrap
from importlib.metadata import version as _pkg_version
from typing import Annotated, Any

import typer
import typer.main
from typer.core import TyperGroup


class _MainGroup(TyperGroup):
    """The main command: ``--help-all`` next to ``--help``, at the end."""

    def get_params(self, ctx: Any) -> list[Any]:
        params = super().get_params(ctx)
        last = ("help_all", "help")  # Click adds --help last; --help-all goes before it
        return [p for p in params if p.name not in last] + [
            p for name in last for p in params if p.name == name
        ]


main_app = typer.Typer(
    name="canvodpy",
    help="Process GNSS observations into VOD and inspect the stores.",
    cls=_MainGroup,
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
    help=(
        "Compute VOD for a range of days from the GNSS store of a site, one day "
        "per worker. Days stored from the same GNSS files are skipped; days "
        "without data are listed."
    ),
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


#: The command-line reference: every command and option with its help.
CLI_REFERENCE = "https://canvodpy.eu/api/cli/"


def command_overview(root: Any, width: int = 100) -> str:
    """Every command of ``root`` with its options and arguments, by name.

    One block per command (``config validate``), its options and arguments
    wrapped after it; hidden commands and options are left out.
    """
    rows: list[tuple[str, list[str]]] = []

    def walk(command: Any, path: list[str]) -> None:
        if hasattr(command, "commands"):  # a group
            for name, sub in command.commands.items():
                if not sub.hidden:
                    walk(sub, [*path, name])
            return
        names = [
            _option_name(param)
            if param.param_type_name == "option"
            else param.name.upper()
            for param in command.params
            if not getattr(param, "hidden", False) and param.name != "help"
        ]
        rows.append((" ".join(path), names))

    walk(root, [])
    column = max(len(name) for name, _ in rows) + 2
    lines = []
    for name, params in rows:
        wrapped = textwrap.wrap(" ".join(params), width=max(width - column, 20)) or [""]
        lines.append(f"{name:<{column}}{wrapped[0]}".rstrip())
        lines += [f"{'':<{column}}{line}" for line in wrapped[1:]]
    return "\n".join(lines)


def _option_name(param: Any) -> str:
    """An option by its long name (``--site``, not ``-s``)."""
    return next((opt for opt in param.opts if opt.startswith("--")), param.opts[0])


def _help_all_callback(ctx: typer.Context, value: bool) -> None:
    if value and not ctx.resilient_parsing:
        root = ctx.find_root().command
        typer.echo(command_overview(root, min(shutil.get_terminal_size().columns, 100)))
        typer.echo("\nOne command with descriptions: canvodpy COMMAND --help")
        typer.echo(f"All commands with descriptions: {CLI_REFERENCE}")
        raise typer.Exit()


#: How to load a new completion in the open terminal, by shell (Typer's names).
_RELOAD = {
    "zsh": "exec zsh",
    "bash": "exec bash",
    "fish": "exec fish",
    "powershell": ". $PROFILE",
    "pwsh": ". $PROFILE",
}


def _current_shell() -> str | None:
    """The shell this runs in, detected as Typer detects it (shellingham)."""
    import shellingham

    try:
        name, _command = shellingham.detect_shell()
    except shellingham.ShellDetectionFailure:
        return None
    return name.lower()


def _with_reload_hint(install: Any) -> Any:
    """Typer's ``--install-completion`` callback, then how to load it now.

    Typer ends the install with "Completion will take effect once you
    restart the terminal"; this adds the command that loads it in the
    open terminal instead, for the shell it was installed for: the one
    this runs in, as Typer picks it, or the one named where Typer takes a
    name (with its shell detection off). For a shell not in
    :data:`_RELOAD` it adds nothing.
    """

    @functools.wraps(install)
    def callback(ctx: typer.Context, param: Any, value: Any) -> Any:
        try:
            return install(ctx, param, value)
        except SystemExit as done:
            shell = value.lower() if isinstance(value, str) else _current_shell()
            reload = _RELOAD.get(shell or "")
            if done.code in (0, None) and reload:
                typer.echo(f"Or load it in this terminal now: {reload}")
            raise

    return callback


_typer_completion_arguments = typer.main.get_install_completion_arguments


def _completion_arguments() -> tuple[Any, Any]:
    """Typer's two completion options, the install one with the reload hint."""
    install, show = _typer_completion_arguments()
    install.callback = _with_reload_hint(install.callback)
    return install, show


# Typer builds its completion options when it builds the command; it looks
# this function up there, so canvodpy's command gets the wrapped option.
# canvodpy pins only typer>=0.9: if a Typer release renames this function or
# stops looking it up, test_hint_after_typers_own_install fails.
setattr(typer.main, "get_install_completion_arguments", _completion_arguments)  # noqa: B010


@main_app.callback(invoke_without_command=True)
def _main_callback(
    ctx: typer.Context,
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_version_callback,
            is_eager=True,
            help="Show canvodpy's version and exit.",
        ),
    ] = False,
    help_all: Annotated[
        bool,
        typer.Option(
            "--help-all",
            callback=_help_all_callback,
            is_eager=True,
            expose_value=False,
            help=(
                "Show every command with its options, and exit. One command "
                "with descriptions: canvodpy COMMAND --help; all of them: "
                f"{CLI_REFERENCE}"
            ),
        ),
    ] = False,
) -> None:
    """Process GNSS observations into VOD and inspect the stores."""
    if ctx.invoked_subcommand is None:
        # No command: the help, and a clean exit.
        typer.echo(ctx.get_help())
        raise typer.Exit()


def main() -> None:
    """Run the CLI entry point."""
    main_app()


if __name__ == "__main__":
    main()
