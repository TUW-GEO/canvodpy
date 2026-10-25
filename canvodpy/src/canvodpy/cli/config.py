"""
CLI for canvodpy configuration management.

Provides commands for:
- Initializing configuration files from templates
- Validating configuration
- Viewing current configuration
- Editing configuration files
- Explaining a setting
"""

import os
import shutil
import subprocess
from pathlib import Path
from typing import Annotated

import typer
import yaml
from rich.prompt import Prompt
from rich.table import Table

from canvod.config import settings_help
from canvod.config.loader import (
    ConfigValidationError,
    format_validation_error,
    get_default_config_dir,
    get_template_dir,
)
from canvod.config.models import (
    ProcessingConfig,
    SidsConfig,
    SitesConfig,
    reference_store_group,
)
from canvodpy.cli.options import (
    CONFIG_DIR_OPTION,
    CONFIG_FILE_OPTION,
    LOCAL_CONFIG_DIR_OPTION,
)
from canvodpy.cli.theme import console

# Config subcommand
config_app = typer.Typer(
    name="config",
    help="Create, check, show, and edit canvod-settings.yaml.",
    no_args_is_help=True,
)


@config_app.callback()
def config_callback(
    config_file: Annotated[Path | None, CONFIG_FILE_OPTION] = None,
) -> None:
    """The overlay file, set by the option's callback."""


def _yaml_scalar(value: str) -> str:
    """Render value as a safely-quoted YAML scalar for inline text substitution.

    Used to patch specific placeholder lines in the template's raw text
    (not a full YAML parse/re-dump, which would strip all its comments).
    """
    dumped = yaml.safe_dump(value).strip()
    return dumped.removesuffix("...").strip()


def _print_setting_help(setting: str) -> None:
    """Print what *setting* means, indented under the question."""
    text = settings_help.explain(setting)
    indented = "\n".join(f"    {line}" if line else "" for line in text.splitlines())
    console.print(f"\n{indented}\n", markup=False, highlight=False, soft_wrap=True)


def _ask(question: str, setting: str, default: str | None = None) -> str:
    """Ask *question*; the answer ``?`` explains *setting* and asks again."""
    while True:
        if default is None:
            answer = Prompt.ask(question)
        else:
            answer = Prompt.ask(question, default=default)
        if answer.strip() != "?":
            return answer
        _print_setting_help(setting)


def _run_interactive_wizard(canvod_dest: Path) -> None:
    """Ask ~8 setup questions and patch their answers into canvod_dest's text.

    Targeted string replacement of known placeholder lines from the
    template — not a full YAML parse/re-dump, so every comment in the file
    survives untouched. Only ever called on a file this same ``init``
    invocation just created (never one that already existed), so the known
    placeholder strings are guaranteed present.
    """
    console.print(
        "\n[bold]Interactive setup[/bold]. Answer a few questions; "
        "answer ? to see what a question sets.\n"
    )

    author = _ask("  Your name", "processing.metadata.author")
    email = _ask("  Your email", "processing.metadata.email")
    institution = _ask("  Institution", "processing.metadata.institution")
    stores_root_dir = _ask(
        "  Where should processed results be stored?",
        "processing.storage.stores_root_dir",
    )
    log_dir = _ask("  Where should the log files go?", "processing.logging.log_dir")
    site_name = _ask("  Site name (e.g. ExampleSite)", "sites.<site>")
    data_root = _ask(
        f"  Data root directory for site '{site_name}'",
        "sites.<site>.gnss_site_data_root",
    )
    canopy_dir = _ask(
        "  Canopy receiver directory (relative to the data root)",
        "sites.<site>.receivers.<receiver>.directory",
        default="02_canopy",
    )
    reference_dir = _ask(
        "  Reference receiver directory (relative to the data root)",
        "sites.<site>.receivers.<receiver>.directory",
        default="01_reference",
    )

    text = canvod_dest.read_text()
    replacements = {
        "    author: Your Name": f"    author: {_yaml_scalar(author)}",
        "    email: your.email@example.com": f"    email: {_yaml_scalar(email)}",
        "    institution: Your Institution": f"    institution: {_yaml_scalar(institution)}",
        "    stores_root_dir: /path/to/your/gnss/stores": (
            f"    stores_root_dir: {_yaml_scalar(stores_root_dir)}"
        ),
        "    log_dir: /path/to/your/gnss/logs": f"    log_dir: {_yaml_scalar(log_dir)}",
        "  my_site:": f"  {site_name}:",
        "    gnss_site_data_root: /path/to/your/gnss/data/my_site": (
            f"    gnss_site_data_root: {_yaml_scalar(data_root)}"
        ),
        "        directory: 01_reference": f"        directory: {_yaml_scalar(reference_dir)}",
        "        directory: 02_canopy": f"        directory: {_yaml_scalar(canopy_dir)}",
    }
    for old, new in replacements.items():
        text = text.replace(old, new, 1)
    canvod_dest.write_text(text)

    console.print("\n[bold]Validating your new configuration...[/bold]\n")
    from canvod.config.loader import load_config

    try:
        load_config(canvod_dest.parent)
    except ConfigValidationError as e:
        console.print(
            "[canvod.warning]⚠️  A few things still need attention:[/canvod.warning]\n"
        )
        console.print(format_validation_error(e))
        console.print()
    else:
        console.print(
            "[canvod.ok]✓ Configuration is valid: you're ready to go![/canvod.ok]\n"
        )


def _store_file_comment(store: str) -> str:
    """The comment header of a settings file written from a store."""
    return (
        f"# Settings written by `canvodpy config init --from-store {store}`.\n"
        "# The content settings below are the store's and must stay as they "
        "are;\n"
        "# the values that are TODO are yours to fill in (an interactive run "
        "asks).\n"
    )


def _run_store_wizard(settings, site_name, receiver_dirs):
    """Ask the machine values in ``settings``; answers fill them in.

    ``settings`` is the mapping from ``settings_from_store``, whose machine
    values are ``TODO``. A receiver's directory offers the directory the
    store records as the default answer.
    """
    site = settings["sites"][site_name]
    site["gnss_site_data_root"] = _ask(
        f"  Data root directory for site '{site_name}'",
        f"sites.{site_name}.gnss_site_data_root",
    )
    for name, receiver in site["receivers"].items():
        receiver["directory"] = _ask(
            f"  Data directory for receiver '{name}'",
            f"sites.{site_name}.receivers.{name}.directory",
            default=receiver_dirs.get(name),
        )
    storage = settings["processing"]["storage"]
    storage["aux_data_dir"] = _ask(
        "  Where should the auxiliary files go?",
        "processing.storage.aux_data_dir",
    )
    storage["shared_aux_cache_dir"] = _ask(
        "  Where should the shared aux cache go?",
        "processing.storage.shared_aux_cache_dir",
    )
    settings["processing"]["logging"]["log_dir"] = _ask(
        "  Where should the log files go?", "processing.logging.log_dir"
    )
    metadata = settings["processing"]["metadata"]
    metadata["author"] = _ask("  Your name", "processing.metadata.author")
    metadata["email"] = _ask("  Your email", "processing.metadata.email")
    metadata["institution"] = _ask("  Institution", "processing.metadata.institution")
    return settings


def _print_store_credentials(store: str) -> None:
    """Tell the user which environment variables to set (never written)."""
    console.print("\n[bold]Set these environment variables:[/bold]")
    console.print("  - For NASA CDDIS access:")
    console.print(
        "      export CANVOD__PROCESSING__CREDENTIALS__NASA_EARTHDATA_ACC_MAIL="
        "you@example.com"
    )
    if store.startswith("s3://"):
        console.print("  - For the S3 store, credentials and endpoint come from:")
        console.print(
            "      AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY (or AWS_PROFILE), "
            "AWS_REGION,"
        )
        console.print(
            "      AWS_ENDPOINT_URL; set CANVOD_S3_PATH_STYLE=1 for a "
            "self-hosted S3 service."
        )
    console.print()


def _init_from_store(config_dir: Path, store: str, no_interactive: bool) -> None:
    """Write ``config_dir/canvod-settings.yaml`` from ``store``."""
    from canvod.store_metadata import read_repository_metadata, settings_from_store

    canvod_dest = config_dir / "canvod-settings.yaml"
    if canvod_dest.exists():
        console.print(
            f"[canvod.error]❌ {canvod_dest} already exists; not overwritten.[/canvod.error]"
        )
        console.print(
            "  Use a different --config-dir, or remove the file and run it again."
        )
        raise typer.Exit(1)

    try:
        settings = settings_from_store(store)
    except (ValueError, OSError) as e:
        console.print(f"[canvod.error]❌ {e}[/canvod.error]", highlight=False)
        raise typer.Exit(1) from e

    site_name = next(iter(settings["sites"]))
    if not no_interactive:
        repository = read_repository_metadata(store)
        receivers = repository.get("instruments", {}).get("receivers", {})
        receiver_dirs = {
            name: meta.get("directory") for name, meta in receivers.items()
        }
        settings = _run_store_wizard(settings, site_name, receiver_dirs)

    text = _store_file_comment(store) + yaml.safe_dump(settings, sort_keys=False)
    canvod_dest.write_text(text)
    console.print(f"[canvod.ok]✓ Wrote {canvod_dest}[/canvod.ok]")
    console.print(
        "\n[i]The content settings are the store's and must stay as they are; "
        "the TODO values are yours to fill in.[/i]"
    )
    _print_store_credentials(store)


@config_app.command()
def init(
    config_dir: Annotated[Path | None, LOCAL_CONFIG_DIR_OPTION] = None,
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Overwrite existing files (no effect with --from-store)",
    ),
    interactive: bool = typer.Option(
        False,
        "--interactive",
        "-i",
        help="Walk through setup with a guided Q&A instead of hand-editing YAML",
    ),
    from_store: Annotated[
        str | None,
        typer.Option(
            "--from-store",
            help="Write the settings of a store from its content settings: a "
            "local dir or an s3://bucket/prefix URL",
        ),
    ] = None,
    no_interactive: bool = typer.Option(
        False,
        "--no-interactive",
        help="With --from-store: keep the machine-value placeholders (TODO) "
        "instead of asking",
    ),
) -> None:
    """Create canvod-settings.yaml from its template, or from a store.

    The file goes into the configuration directory that --config-dir sets.
    Create a naming recipe for each receiver with
    just naming-init SITE NAME.

    With --from-store STORE, the file is written from the store's content
    settings (a folder or an s3:// URL): the settings that shape its data
    stay as they are, and the machine values are asked (or left as TODO
    with --no-interactive).

    \f
    Parameters
    ----------
    config_dir : Path | None
        Directory where configuration files are created (see
        ``--config-dir``).
    force : bool
        Overwrite existing files.
    interactive : bool
        Ask setup questions instead of leaving placeholder values for the
        user to hand-edit afterward.
    from_store : str | None
        A store whose content settings the file reproduces.
    no_interactive : bool
        Keep the ``TODO`` machine values instead of asking.

    Returns
    -------
    None
    """
    config_dir = get_default_config_dir()
    console.print("\n[bold]Initializing canvodpy configuration...[/bold]\n")

    # Create config directory
    config_dir.mkdir(parents=True, exist_ok=True)

    if from_store is not None:
        _init_from_store(config_dir, from_store, no_interactive)
        return

    # Templates ship as real package data inside canvod-config (see
    # get_template_dir()'s docstring): always reachable regardless of
    # install method or invocation directory, no monorepo search needed.
    template_dir = get_template_dir()

    if not template_dir.exists():
        console.print(
            f"[canvod.error]❌ Template directory not found: {template_dir}[/canvod.error]",
        )
        console.print("\nThis looks like a broken canvod-config install; reinstall it.")
        raise typer.Exit(1)

    files_created = []
    files_skipped = []

    # Copy unified template (canvod-settings.yaml.example → canvod-settings.yaml)
    canvod_example = template_dir / "canvod-settings.yaml.example"
    canvod_dest = config_dir / "canvod-settings.yaml"
    if canvod_example.exists():
        if canvod_dest.exists() and not force:
            files_skipped.append(canvod_dest)
        else:
            shutil.copy(canvod_example, canvod_dest)
            files_created.append(canvod_dest)
    else:
        console.print(
            f"[canvod.warning]⚠️  Template not found: {canvod_example}[/canvod.warning]"
        )

    # Show results
    if files_created:
        console.print("[canvod.ok]✓ Created:[/canvod.ok]")
        for f in files_created:
            console.print(f"  {f}")

    if files_skipped:
        console.print("\n[canvod.warning]⊘ Skipped (already exist):[/canvod.warning]")
        for f in files_skipped:
            console.print(f"  {f}")
        console.print("\n  Use --force to overwrite")

    if interactive and canvod_dest in files_created:
        _run_interactive_wizard(canvod_dest)
        console.print("[bold]Optional next steps:[/bold]")
        console.print("  - For NASA CDDIS access, set this environment variable:")
        console.print(
            "      export CANVOD__PROCESSING__CREDENTIALS__NASA_EARTHDATA_ACC_MAIL=you@example.com"
        )
        console.print(
            "  - If a receiver writes non-canonical file names, create its naming "
            "recipe with: just naming-init SITE NAME\n"
        )
        return

    if interactive:
        console.print(
            "\n[canvod.warning]⊘ canvod-settings.yaml already exists; skipping interactive "
            "setup.[/canvod.warning] Use --force to start over.\n"
        )

    # Next steps
    console.print("\n[bold]Next steps:[/bold]")
    console.print("  1. Edit config/canvod-settings.yaml:")
    console.print("     - processing.metadata: fill in author, email, institution")
    console.print("     - processing.storage.stores_root_dir: set your store path")
    console.print("     - processing.logging.log_dir: set your log folder")
    console.print("     - sites: replace the example site with your own")
    console.print("     (or re-run with --interactive/-i for a guided Q&A instead)")
    console.print("  2. For NASA CDDIS access, set this environment variable:")
    console.print(
        "       export CANVOD__PROCESSING__CREDENTIALS__NASA_EARTHDATA_ACC_MAIL=you@example.com"
    )
    console.print(
        "  3. If a receiver writes non-canonical file names, create its naming "
        "recipe with: just naming-init SITE NAME"
    )
    console.print("  4. Run: canvodpy config validate\n")


def _print_site_report(report) -> None:
    """Print a :class:`~canvodpy.orchestrator.data_check.SiteReport`.

    Lines are not wrapped, so the paths in them can be copied.
    """

    from rich.markup import escape

    from canvodpy.orchestrator.data_check import group_by_file_type

    def say(text: str) -> None:
        console.print(text, soft_wrap=True, highlight=False)

    for error in report.errors:
        say(f"  [canvod.error]❌ {report.site}: {escape(error)}[/canvod.error]")
    for rx in report.receivers.values():
        label = f"{report.site}/{rx.name}"
        if rx.errors:
            say(f"  [canvod.error]❌ {label}[/canvod.error]")
        elif rx.files:
            recipe = f", recipe '{rx.recipe}'" if rx.recipe else ""
            say(
                f"  [canvod.ok]✓ {label} ({rx.identity}): {rx.files} files on "
                f"{len(rx.days)} days, {rx.days[0]} to {rx.days[-1]} "
                f"({rx.reader_format}{recipe})[/canvod.ok]"
            )
            if rx.sampling_checked:
                intervals = ", ".join(
                    f"{s:g} s" for s in dict.fromkeys(rx.sampling_checked)
                )
                say(
                    f"      Sampling matches the file names in "
                    f"{len(rx.sampling_checked)} file(s) checked: {intervals}"
                )
        else:
            say(f"  [canvod.warning]⚠️  {label}[/canvod.warning]")
        for error in rx.errors:
            say(f"      [canvod.error]{escape(error)}[/canvod.error]")
        for warning in rx.warnings:
            say(f"      [canvod.warning]{escape(warning)}[/canvod.warning]")
        if rx.compressed:
            say("      Compressed, not processed, by file type:")
            for kind, count, example in group_by_file_type(rx.compressed):
                say(f"        {escape(kind)}: {count} (e.g. {escape(example.name)})")
        if rx.unrecognized:
            say("      Not processed, by file type:")
            for kind, count, example in group_by_file_type(rx.unrecognized):
                say(f"        {escape(kind)}: {count} (e.g. {escape(example.name)})")


def _todo_placeholders(config_dir: Path) -> list[str]:
    """The dotted keys of every ``TODO`` value in ``config_dir``'s settings."""
    from canvod.store_metadata import PLACEHOLDER

    settings_file = config_dir / "canvod-settings.yaml"
    if not settings_file.exists():
        return []
    data = yaml.safe_load(settings_file.read_text()) or {}

    def walk(node, path: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                walk(value, f"{path}.{key}" if path else str(key))
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{path}[{index}]")
        elif node == PLACEHOLDER:
            placeholder_keys.append(path)

    placeholder_keys: list[str] = []
    walk(data, "")
    return placeholder_keys


def _period_days(start: str | None, end: str | None) -> tuple[str | None, str | None]:
    """``--start`` and ``--end`` as YYYYDOY, checked; a usage error if not."""
    from canvod.utils.tools import YYYYDOY

    days = []
    for option, value in (("--start", start), ("--end", end)):
        if value is None:
            days.append(None)
            continue
        try:
            days.append(YYYYDOY.from_str(value).to_str())
        except ValueError as exc:
            msg = f"{value} is not a day in YYYYDOY format, for example 2025001: {exc}"
            raise typer.BadParameter(msg, param_hint=option) from None
    if days[0] and days[1] and days[0] > days[1]:
        msg = f"--start {days[0]} is after --end {days[1]}."
        raise typer.BadParameter(msg)
    return days[0], days[1]


@config_app.command()
def validate(
    config_dir: Annotated[Path | None, CONFIG_DIR_OPTION] = None,
    config_file: Annotated[Path | None, CONFIG_FILE_OPTION] = None,
    site: Annotated[
        list[str] | None,
        typer.Option(
            "--site",
            help="Check the data of this site only. Repeat for several sites. "
            "Default: all sites.",
            show_default=False,
        ),
    ] = None,
    check_sampling: Annotated[
        bool,
        typer.Option(
            "--check-sampling/--no-check-sampling",
            help="Read the first file of the first and the last day of each "
            "receiver and compare the sampling interval of its data with the "
            "one in its canonical name.",
        ),
    ] = True,
    start: Annotated[
        str | None,
        typer.Option(
            "--start",
            help="Check the data from this day on, in YYYYDOY format, for "
            "example 2025001, as for canvodpy run. Default: the first day "
            "with files.",
            show_default=False,
        ),
    ] = None,
    end: Annotated[
        str | None,
        typer.Option(
            "--end",
            help="Check the data up to this day, in YYYYDOY format. Default: "
            "the last day with files.",
            show_default=False,
        ),
    ] = None,
) -> None:
    """Validate the configuration and the receiver data it points to.

    It finds the data files the same way as canvodpy run, so every error
    it reports would stop a run or make its results wrong. A settings file
    written from a store (:meth:`init`) that still has placeholder values is
    listed, and the command exits with code 1.

    \f
    Parameters
    ----------
    config_dir : Path | None
        Directory containing config files (see ``--config-dir``).
    config_file : Path | None
        Overlay file (see ``--config``), also accepted before ``validate``.
    site : list[str] | None
        Sites whose data to check; ``None`` checks all sites.
    check_sampling : bool
        Compare named and actual sampling intervals.
    start, end : str | None
        First and last day (YYYYDOY) whose data to check; ``None`` checks
        from the first or up to the last day with files. An overlay for
        part of the days is validated over those days.

    Returns
    -------
    None
    """
    from canvod.config.loader import load_config
    from canvodpy.orchestrator.data_check import check_site_data

    start, end = _period_days(start, end)
    config_dir = get_default_config_dir()
    console.print(f"\n[bold]Validating configuration in {config_dir}...[/bold]\n")

    # A settings file written from a store keeps TODO machine values; list
    # them before anything else, so the user knows what to fill in (and so a
    # not-yet-valid value such as a placeholder email does not hide them).
    placeholders = _todo_placeholders(config_dir)
    if placeholders:
        console.print(
            f"\n[canvod.warning]⚠️  {len(placeholders)} placeholder value(s) (TODO) "
            "in canvod-settings.yaml:[/canvod.warning]\n"
        )
        for key in placeholders:
            console.print(f"    {key}")
        console.print("\nFill them in, or re-run the interactive wizard:")
        console.print("  canvodpy config init --from-store <store>\n")
        raise typer.Exit(1)

    try:
        config = load_config(config_dir)
    except ConfigValidationError as e:
        console.print("[canvod.error]❌ Validation failed:[/canvod.error]\n")
        console.print(format_validation_error(e))
        console.print()
        raise typer.Exit(1) from e
    except Exception as e:
        console.print("[canvod.error]❌ Validation failed:[/canvod.error]\n")
        console.print(str(e))
        console.print()
        raise typer.Exit(1) from e

    console.print("[canvod.ok]✓ Configuration is valid![/canvod.ok]\n")

    console.print(f"  Sites: {len(config.sites.sites)}")
    for name in config.sites.sites.keys():
        console.print(f"    - {name}")

    console.print(f"\n  SID mode: {config.sids.mode}")
    aux = config.processing.aux_data
    console.print(f"  Agency: {aux.agency} ({aux.product_type})")
    if config.processing.params.ephemeris_source != "broadcast":
        from canvod.auxiliary.products import check_product

        try:
            spec = check_product(aux.agency, aux.product_type, aux.fetch_clock)
        except (KeyError, ValueError) as e:
            console.print(f"\n[canvod.error]❌ Orbit product:[/canvod.error]\n{e}\n")
            raise typer.Exit(1) from e
        console.print(f"  Orbit product: {spec.prefix} ({spec.description})")

    for name, site_cfg in config.sites.sites.items():
        console.print(f"  {name} data root: {site_cfg.gnss_site_data_root}")

    email = config.processing.credentials.nasa_earthdata_acc_mail
    if email:
        console.print(f"  NASA Earthdata email: {email}")
        console.print("  [canvod.ok]✓ NASA CDDIS enabled[/canvod.ok]")
    else:
        console.print(
            "  [canvod.warning]⊘ NASA CDDIS disabled (ESA only)[/canvod.warning]"
        )

    unknown = [s for s in site or [] if s not in config.sites.sites]
    if unknown:
        console.print(
            f"\n[canvod.error]❌ Unknown site(s): {', '.join(unknown)}. Configured: "
            f"{', '.join(config.sites.sites) or '(none)'}[/canvod.error]\n"
        )
        raise typer.Exit(1)

    console.print("\n[bold]Checking receiver data...[/bold]")
    reports = [
        check_site_data(name, config, check_sampling, start, end)
        for name in site or list(config.sites.sites)
    ]
    for report in reports:
        _print_site_report(report)

    failed = [r.site for r in reports if not r.ok]
    if failed:
        console.print(
            f"\n[canvod.error]❌ Receiver data of {', '.join(failed)} would not be "
            f"processed correctly. Fix the errors above.[/canvod.error]\n"
        )
        raise typer.Exit(1)
    console.print()


@config_app.command()
def show(
    config_dir: Annotated[Path | None, CONFIG_DIR_OPTION] = None,
    section: str = typer.Option(
        None,
        "--section",
        "-s",
        metavar="processing|sites|sids",
        help="Show this section only. Default: all sections.",
    ),
) -> None:
    """Show the settings that canvodpy uses.

    \f
    Parameters
    ----------
    config_dir : Path | None
        Directory containing config files (see ``--config-dir``).
    section : str
        Optional section name (processing, sites, sids).

    Returns
    -------
    None
    """
    from canvod.config.loader import load_config

    config_dir = get_default_config_dir()
    try:
        config = load_config(config_dir)
    except ConfigValidationError as e:
        console.print(
            f"\n[canvod.error]❌ Error loading config:[/canvod.error]\n\n{format_validation_error(e)}\n"
        )
        raise typer.Exit(1) from e
    except Exception as e:
        console.print(f"\n[canvod.error]❌ Error loading config:[/canvod.error] {e}\n")
        raise typer.Exit(1) from e

    console.print("\n[bold]Current Configuration[/bold]\n")

    if section == "processing" or section is None:
        _show_processing(config.processing)

    if section == "sites" or section is None:
        _show_sites(config.sites)

    if section == "sids" or section is None:
        _show_sids(config.sids)

    console.print()


@config_app.command()
def edit(
    config_dir: Annotated[Path | None, LOCAL_CONFIG_DIR_OPTION] = None,
) -> None:
    """Open canvod-settings.yaml in $EDITOR.

    \f
    Parameters
    ----------
    config_dir : Path | None
        Directory containing config files (see ``--config-dir``).

    Returns
    -------
    None
    """

    config_dir = get_default_config_dir()
    file_path = config_dir / "canvod-settings.yaml"

    if not file_path.exists():
        console.print(f"[canvod.error]❌ File not found:[/canvod.error] {file_path}")
        console.print("\nRun: canvodpy config init")
        raise typer.Exit(1)

    editor = os.getenv("EDITOR", "nano")
    subprocess.run([editor, str(file_path)])


def _show_processing(config: ProcessingConfig) -> None:
    """Display processing config.

    Parameters
    ----------
    config : ProcessingConfig
        Processing configuration object.

    Returns
    -------
    None
    """
    console.print("[bold]Processing Configuration:[/bold]")
    table = Table(show_header=False, padding=(0, 2))

    email = config.credentials.nasa_earthdata_acc_mail
    table.add_row(
        "NASA Earthdata Email",
        email or "[canvod.warning]Not set (ESA only)[/canvod.warning]",
    )
    if email:
        table.add_row("FTP Priority", "NASA CDDIS -> ESA (fallback)")
    else:
        table.add_row("FTP Priority", "ESA only")

    table.add_row("Agency", config.aux_data.agency)
    table.add_row("Product Type", config.aux_data.product_type)
    table.add_row("Resource Mode", config.params.resource_mode)
    table.add_row(
        "Max Threads",
        str(config.params.n_max_threads or "auto"),
    )
    table.add_row(
        "Keep GNSS Observables", ", ".join(config.params.keep_gnss_observables)
    )
    table.add_row(
        "Days per Unit",
        "from the memory budget"
        if config.params.days_per_batch is None
        else f"at most {config.params.days_per_batch} (days_per_batch, deprecated)",
    )
    affinity_str = (
        str(config.params.cpu_affinity)
        if config.params.cpu_affinity
        else "[dim]no restriction[/dim]"
    )
    table.add_row("CPU Affinity", affinity_str)
    table.add_row("Nice Priority", str(config.params.nice_priority))
    console.print(table)
    console.print()

    # Storage
    console.print("[bold]Storage:[/bold]")
    st = config.storage
    console.print(f"  Stores root:       {st.stores_root_dir}")
    console.print(f"  GNSS store name:   {st.gnss_store_name}")
    console.print(f"  VOD store name:    {st.vod_store_name}")
    aux_dir = str(st.aux_data_dir) if st.aux_data_dir else "[dim]system temp[/dim]"
    console.print(f"  Aux data dir:      {aux_dir}")
    console.print(f"  GNSS strategy:     {st.gnss_store_strategy}")
    console.print()

    # Icechunk
    ic = config.icechunk
    console.print("[bold]Icechunk:[/bold]")
    console.print(
        f"  Compression:       {ic.compression_algorithm} (level {ic.compression_level})"
    )
    console.print(f"  Inline threshold:  {ic.inline_chunk_threshold_bytes} bytes")
    console.print(f"  Get concurrency:   {ic.get_partial_values_concurrency}")
    for store_name, strategy in ic.chunk_strategies:
        console.print(
            f"  Chunks ({store_name}): epoch={strategy.epoch}, sid={strategy.sid}"
        )
    console.print()

    # Logging
    lg = config.logging
    console.print("[bold]Logging:[/bold]")
    log_dir = (
        str(lg.log_dir)
        if lg.log_dir
        else "[canvod.error]❌ not set (required for a run)[/canvod.error]"
    )
    console.print(f"  Log directory:     {log_dir}")
    console.print(
        f"  Worker log files:  deleted after {lg.worker_log_retention_days} days"
    )
    console.print(f"  Log path depth:    {lg.log_path_depth}")
    console.print()


def _show_sites(config: SitesConfig) -> None:
    """Display sites config.

    Parameters
    ----------
    config : SitesConfig
        Sites configuration object.

    Returns
    -------
    None
    """
    from canvod.config.loader import load_config as _load_config

    try:
        full_config = _load_config()
        storage = full_config.processing.storage
    except Exception:
        storage = None

    console.print("[bold]Research Sites:[/bold]")

    for site_name, site in config.sites.items():
        base_path = site.get_base_path()

        console.print(f"\n  [canvod.heading]{site_name}[/canvod.heading]")
        console.print(f"    Data root: {site.gnss_site_data_root}")

        # Store paths
        if storage:
            console.print(f"    GNSS store:  {storage.get_gnss_store_path(site_name)}")
            console.print(f"    VOD store:   {storage.get_vod_store_path(site_name)}")

        # Receivers table
        canopy_names = site.get_canopy_receiver_names()
        ref_names = [n for n, c in site.receivers.items() if c.type == "reference"]

        console.print(
            f"\n    [bold]Receivers[/bold] "
            f"({len(canopy_names)} canopy, {len(ref_names)} reference):"
        )

        for recv_name, recv in site.receivers.items():
            abs_dir = str(base_path / recv.directory)
            type_color = "magenta" if recv.type == "reference" else "blue"
            console.print(
                f"      [canvod.name]{recv_name}[/canvod.name] "
                f"[{type_color}]({recv.type})[/{type_color}]"
            )
            console.print(f"        dir: {abs_dir}")
            if recv.recipe:
                console.print(f"        recipe: {recv.recipe}")
            if recv.paired_canopies is not None:
                if recv.paired_canopies == "all":
                    console.print(f"        paired_canopies: all -> {canopy_names}")
                else:
                    console.print(f"        paired_canopies: {recv.paired_canopies}")

        # Reference-canopy pairs (expanded from paired_canopies)
        pairs = site.get_reference_canopy_pairs()
        if pairs:
            console.print(
                f"\n    [bold]Reference x Canopy store groups[/bold] ({len(pairs)}):"
            )
            pair_table = Table(
                show_header=True, padding=(0, 1), box=None, pad_edge=False
            )
            pair_table.add_column("Store Group", style="canvod.name")
            pair_table.add_column("Reference")
            pair_table.add_column("Position From")

            for ref_name, canopy_name in pairs:
                group_name = reference_store_group(ref_name, canopy_name)
                pair_table.add_row(group_name, ref_name, canopy_name)

            console.print(pair_table)

        # VOD analyses
        if site.vod_analyses:
            console.print(
                f"\n    [bold]VOD Analyses[/bold] ({len(site.vod_analyses)}):"
            )
            vod_table = Table(
                show_header=True, padding=(0, 1), box=None, pad_edge=False
            )
            vod_table.add_column("Name", style="canvod.name")
            vod_table.add_column("Canopy")
            vod_table.add_column("Reference")

            for analysis_name, analysis in site.vod_analyses.items():
                vod_table.add_row(
                    analysis_name,
                    analysis.canopy_receiver,
                    analysis.reference_receiver,
                )

            console.print(vod_table)


def _show_sids(config: SidsConfig) -> None:
    """Display SIDs config.

    Parameters
    ----------
    config : SidsConfig
        SIDs configuration object.

    Returns
    -------
    None
    """
    console.print("[bold]Signal IDs:[/bold]")
    table = Table(show_header=False)
    table.add_row("Mode", config.mode)
    if config.mode == "preset":
        table.add_row("Preset", config.preset or "")
    elif config.mode == "custom":
        table.add_row("Custom SIDs", f"{len(config.custom_sids)} defined")
    console.print(table)
    console.print()


@config_app.command()
def explain(
    setting: Annotated[
        str,
        typer.Argument(
            help=(
                "The setting's path in canvod-settings.yaml, or the end of it "
                "(for example gnss_store.epoch)."
            ),
        ),
    ],
) -> None:
    """Print what a setting of canvod-settings.yaml means.

    Prints the setting's description, type, limits and default, and a link
    to its entry in the settings reference. Name a site, receiver or VOD
    analysis as in your file:
    sites.my_site.receivers.reference_01.directory.

    \f
    Parameters
    ----------
    setting : str
        The setting's path, or the end of it.

    Raises
    ------
    typer.Exit
        With code 1 if no setting, or more than one, has that path.
    """
    try:
        text = settings_help.explain(setting)
    except settings_help.UnknownSettingError as exc:
        console.print(f"[canvod.error]❌ {exc.args[0]}[/canvod.error]", highlight=False)
        raise typer.Exit(1) from exc
    console.print(text, markup=False, highlight=False, soft_wrap=True)
