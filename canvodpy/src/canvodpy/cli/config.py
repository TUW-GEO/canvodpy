"""
CLI for canvodpy configuration management.

Provides commands for:
- Initializing configuration files from templates
- Validating configuration
- Viewing current configuration
- Editing configuration files
"""

import os
import shutil
import subprocess
from pathlib import Path
from typing import Annotated

import typer
import yaml
from rich.console import Console
from rich.prompt import Prompt
from rich.table import Table

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
from canvodpy.cli.options import CONFIG_DIR_OPTION

# Config subcommand
config_app = typer.Typer(
    name="config",
    help="Create, check, show, and edit canvod-settings.yaml.",
    no_args_is_help=True,
)

console = Console()


@config_app.callback()
def config_callback(
    config: Annotated[
        Path | None,
        typer.Option(
            "--config",
            help="Settings file whose values replace those of canvod-settings.yaml.",
            show_default=False,
        ),
    ] = None,
) -> None:
    if config is not None:
        if not config.exists():
            typer.echo(f"Error: overlay config file not found: {config}", err=True)
            raise typer.Exit(1)
        os.environ["CANVOD_CONFIG_FILE"] = str(config.expanduser().resolve())


def _yaml_scalar(value: str) -> str:
    """Render value as a safely-quoted YAML scalar for inline text substitution.

    Used to patch specific placeholder lines in the template's raw text
    (not a full YAML parse/re-dump, which would strip all its comments).
    """
    dumped = yaml.safe_dump(value).strip()
    return dumped.removesuffix("...").strip()


def _run_interactive_wizard(canvod_dest: Path) -> None:
    """Ask ~8 setup questions and patch their answers into canvod_dest's text.

    Targeted string replacement of known placeholder lines from the
    template — not a full YAML parse/re-dump, so every comment in the file
    survives untouched. Only ever called on a file this same ``init``
    invocation just created (never one that already existed), so the known
    placeholder strings are guaranteed present.
    """
    console.print("\n[bold]Interactive setup[/bold]. Answer a few questions:\n")

    author = Prompt.ask("  Your name")
    email = Prompt.ask("  Your email")
    institution = Prompt.ask("  Institution")
    stores_root_dir = Prompt.ask("  Where should processed results be stored?")
    log_dir = Prompt.ask("  Where should the log files go?")
    site_name = Prompt.ask("  Site name (e.g. ExampleSite)")
    data_root = Prompt.ask(f"  Data root directory for site '{site_name}'")
    canopy_dir = Prompt.ask(
        "  Canopy receiver directory (relative to the data root)",
        default="02_canopy",
    )
    reference_dir = Prompt.ask(
        "  Reference receiver directory (relative to the data root)",
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
        console.print("[yellow]⚠️  A few things still need attention:[/yellow]\n")
        console.print(format_validation_error(e))
        console.print()
    else:
        console.print("[green]✓ Configuration is valid: you're ready to go![/green]\n")


@config_app.command()
def init(
    config_dir: Annotated[Path | None, CONFIG_DIR_OPTION] = None,
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Overwrite existing files",
    ),
    interactive: bool = typer.Option(
        False,
        "--interactive",
        "-i",
        help="Walk through setup with a guided Q&A instead of hand-editing YAML",
    ),
) -> None:
    """Create canvod-settings.yaml from its template.

    The file goes into the configuration directory that --config-dir sets.
    Create a naming recipe for each receiver with
    just naming-init SITE NAME.

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

    Returns
    -------
    None
    """
    config_dir = get_default_config_dir()
    console.print("\n[bold]Initializing canvodpy configuration...[/bold]\n")

    # Create config directory
    config_dir.mkdir(parents=True, exist_ok=True)

    # Templates ship as real package data inside canvod-config (see
    # get_template_dir()'s docstring): always reachable regardless of
    # install method or invocation directory, no monorepo search needed.
    template_dir = get_template_dir()

    if not template_dir.exists():
        console.print(
            f"[red]❌ Template directory not found: {template_dir}[/red]",
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
        console.print(f"[yellow]⚠️  Template not found: {canvod_example}[/yellow]")

    # Show results
    if files_created:
        console.print("[green]✓ Created:[/green]")
        for f in files_created:
            console.print(f"  {f}")

    if files_skipped:
        console.print("\n[yellow]⊘ Skipped (already exist):[/yellow]")
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
            "\n[yellow]⊘ canvod-settings.yaml already exists; skipping interactive "
            "setup.[/yellow] Use --force to start over.\n"
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
        say(f"  [red]❌ {report.site}: {escape(error)}[/red]")
    for rx in report.receivers.values():
        label = f"{report.site}/{rx.name}"
        if rx.errors:
            say(f"  [red]❌ {label}[/red]")
        elif rx.files:
            recipe = f", recipe '{rx.recipe}'" if rx.recipe else ""
            say(
                f"  [green]✓ {label} ({rx.identity}): {rx.files} files on "
                f"{len(rx.days)} days, {rx.days[0]} to {rx.days[-1]} "
                f"({rx.reader_format}{recipe})[/green]"
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
            say(f"  [yellow]⚠️  {label}[/yellow]")
        for error in rx.errors:
            say(f"      [red]{escape(error)}[/red]")
        for warning in rx.warnings:
            say(f"      [yellow]{escape(warning)}[/yellow]")
        if rx.compressed:
            say("      Compressed, not processed, by file type:")
            for kind, count, example in group_by_file_type(rx.compressed):
                say(f"        {escape(kind)}: {count} (e.g. {escape(example.name)})")
        if rx.unrecognized:
            say("      Not processed, by file type:")
            for kind, count, example in group_by_file_type(rx.unrecognized):
                say(f"        {escape(kind)}: {count} (e.g. {escape(example.name)})")


@config_app.command()
def validate(
    config_dir: Annotated[Path | None, CONFIG_DIR_OPTION] = None,
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
) -> None:
    """Validate the configuration and the receiver data it points to.

    It finds the data files the same way as canvodpy run, so every error
    it reports would stop a run or make its results wrong.

    \f
    Parameters
    ----------
    config_dir : Path | None
        Directory containing config files (see ``--config-dir``).
    site : list[str] | None
        Sites whose data to check; ``None`` checks all sites.
    check_sampling : bool
        Compare named and actual sampling intervals.

    Returns
    -------
    None
    """
    from canvod.config.loader import load_config
    from canvodpy.orchestrator.data_check import check_site_data

    config_dir = get_default_config_dir()
    console.print(f"\n[bold]Validating configuration in {config_dir}...[/bold]\n")

    try:
        config = load_config(config_dir)
    except ConfigValidationError as e:
        console.print("[red]❌ Validation failed:[/red]\n")
        console.print(format_validation_error(e))
        console.print()
        raise typer.Exit(1) from e
    except Exception as e:
        console.print("[red]❌ Validation failed:[/red]\n")
        console.print(str(e))
        console.print()
        raise typer.Exit(1) from e

    console.print("[green]✓ Configuration is valid![/green]\n")

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
            console.print(f"\n[red]❌ Orbit product:[/red]\n{e}\n")
            raise typer.Exit(1) from e
        console.print(f"  Orbit product: {spec.prefix} ({spec.description})")

    for name, site_cfg in config.sites.sites.items():
        console.print(f"  {name} data root: {site_cfg.gnss_site_data_root}")

    email = config.processing.credentials.nasa_earthdata_acc_mail
    if email:
        console.print(f"  NASA Earthdata email: {email}")
        console.print("  [green]✓ NASA CDDIS enabled[/green]")
    else:
        console.print("  [yellow]⊘ NASA CDDIS disabled (ESA only)[/yellow]")

    unknown = [s for s in site or [] if s not in config.sites.sites]
    if unknown:
        console.print(
            f"\n[red]❌ Unknown site(s): {', '.join(unknown)}. Configured: "
            f"{', '.join(config.sites.sites) or '(none)'}[/red]\n"
        )
        raise typer.Exit(1)

    console.print("\n[bold]Checking receiver data...[/bold]")
    reports = [
        check_site_data(name, config, check_sampling)
        for name in site or list(config.sites.sites)
    ]
    for report in reports:
        _print_site_report(report)

    failed = [r.site for r in reports if not r.ok]
    if failed:
        console.print(
            f"\n[red]❌ Receiver data of {', '.join(failed)} would not be "
            f"processed correctly. Fix the errors above.[/red]\n"
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
            f"\n[red]❌ Error loading config:[/red]\n\n{format_validation_error(e)}\n"
        )
        raise typer.Exit(1) from e
    except Exception as e:
        console.print(f"\n[red]❌ Error loading config:[/red] {e}\n")
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
    config_dir: Annotated[Path | None, CONFIG_DIR_OPTION] = None,
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
    import os

    config_dir = get_default_config_dir()
    file_path = config_dir / "canvod-settings.yaml"

    if not file_path.exists():
        console.print(f"[red]File not found:[/red] {file_path}")
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
        email or "[yellow]Not set (ESA only)[/yellow]",
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
    table.add_row("Days per Batch", str(config.params.days_per_batch))
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
        str(lg.log_dir) if lg.log_dir else "[red]not set (required for a run)[/red]"
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

        console.print(f"\n  [bold cyan]{site_name}[/bold cyan]")
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
                f"      [green]{recv_name}[/green] "
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
            pair_table.add_column("Store Group", style="green")
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
            vod_table.add_column("Name", style="green")
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
