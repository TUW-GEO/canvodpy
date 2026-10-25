"""canvodpy store: inspect Icechunk stores from the terminal.

Thin CLI wrappers around canvod-store's existing MyIcechunkStore methods
(print_tree, print_history, plot_commit_graph, print_ops_log,
get_store_stats), which themselves delegate to icechunk v2's native
ancestry_graph()/ops_log(). No new store-introspection logic here except
_print_group_content, a terminal port of the group-content drill-down that
canvod-store's marimo/Jupyter-only IcechunkStoreViewer renders as HTML.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer
from rich.console import Console
from rich.table import Table
from rich.tree import Tree

from canvod.store_metadata.location import S3StoreLocation
from canvodpy.cli.options import CONFIG_DIR_OPTION

if TYPE_CHECKING:
    from canvod.store_metadata import StoreMetadata

store_app = typer.Typer(
    name="store",
    help="Inspect the Icechunk stores of the sites and maintain them.",
    no_args_is_help=True,
)

console = Console()

_STORE_KINDS = ("gnss", "vod")


def _store_path(site_name: str, store_kind: str) -> tuple[Path | str, str]:
    """Resolve a site + store kind (gnss/vod) to its path and store type.

    Exits cleanly with an actionable message if the site is unknown or the
    store hasn't been created yet; matches the rest of the CLI's error
    style (config.py, doctor.py), not a raw traceback.
    """
    from canvod.config import load_config
    from canvod.store_metadata import store_exists

    if store_kind not in _STORE_KINDS:
        console.print(
            f"[red]❌ --store must be one of: {', '.join(_STORE_KINDS)}[/red]"
        )
        raise typer.Exit(1)

    config = load_config()
    sites = config.sites.sites
    if site_name not in sites:
        console.print(f"[red]❌ Unknown site:[/red] {site_name}")
        known = ", ".join(sites) or "(none configured)"
        console.print(f"  Known sites: {known}")
        raise typer.Exit(1)

    storage = config.processing.storage
    if store_kind == "gnss":
        path = storage.get_gnss_store_path(site_name)
        store_type = "gnss_store"
    else:
        path = storage.get_vod_store_path(site_name)
        store_type = "vod_store"

    if not store_exists(path):
        console.print(
            f"[yellow]⊘ No {store_kind} store yet for '{site_name}'[/yellow] ({path})"
        )
        raise typer.Exit(1)

    return path, store_type


def _open_store(site_name: str, store_kind: str):
    """Resolve a site + store kind (gnss/vod) to an opened MyIcechunkStore."""
    from canvod.store import MyIcechunkStore

    path, store_type = _store_path(site_name, store_kind)
    return MyIcechunkStore(path, store_type=store_type)


@store_app.command("list")
def list_stores(
    config_dir: Annotated[Path | None, CONFIG_DIR_OPTION] = None,
) -> None:
    """List every configured site's GNSS and VOD store paths and status."""
    from canvod.config import load_config
    from canvod.store_metadata import store_exists

    config = load_config()
    storage = config.processing.storage
    sites = config.sites.sites

    if not sites:
        console.print("[yellow]No sites configured.[/yellow]")
        return

    table = Table(show_header=True)
    table.add_column("Site")
    table.add_column("Store")
    table.add_column("Path")
    table.add_column("Status")

    path_getters = {
        "gnss": storage.get_gnss_store_path,
        "vod": storage.get_vod_store_path,
    }
    for site_name in sites:
        for kind, get_path in path_getters.items():
            path = get_path(site_name)
            status = (
                "[green]✓ exists[/green]"
                if store_exists(path)
                else "[dim]not yet created[/dim]"
            )
            table.add_row(site_name, kind, str(path), status)

    console.print(table)


@store_app.command()
def info(
    site: Annotated[
        str,
        typer.Argument(
            help="Site name, as defined under sites: in canvod-settings.yaml"
        ),
    ],
    store: Annotated[
        str, typer.Option("--store", metavar="gnss|vod", help="Store to open.")
    ] = "gnss",
    branch: Annotated[str, typer.Option("--branch", help="Branch to inspect")] = "main",
    group: Annotated[
        str | None,
        typer.Option(
            "--group",
            help="Show the full content of one group: its dataset and its metadata table.",
        ),
    ] = None,
    config_dir: Annotated[Path | None, CONFIG_DIR_OPTION] = None,
) -> None:
    """Show branches, groups, and stats for one site's store."""
    if store not in _STORE_KINDS:
        console.print(
            f"[red]❌ --store must be one of: {', '.join(_STORE_KINDS)}[/red]"
        )
        raise typer.Exit(1)

    icestore = _open_store(site, store)
    stats = icestore.get_store_stats()

    console.print(f"\n[bold]{site}[/bold]: {store} store")
    console.print(f"  Path:        {stats['store_path']}")
    console.print(f"  Groups:      {stats['total_groups']}")
    console.print(
        f"  Compression: {stats['compression_algorithm']} (level {stats['compression_level']})"
    )
    console.print(
        f"  Content settings: {_content_settings_line(icestore.store_path)}\n"
    )

    if group is not None:
        _print_group_content(icestore, group, branch)
    else:
        icestore.print_tree()
        console.print(
            "\n[dim]Use --group <name> to see a group's dataset and metadata table.[/dim]"
        )


def _content_settings_line(store_path) -> str:
    """One line on a store's content settings (ADR 0019) for ``store info``."""
    from canvod.store_metadata import read_repository_metadata

    content = read_repository_metadata(store_path).get("content_settings")
    if not content:
        return "none (canvodpy store migrate-metadata writes them)"
    return (
        f"{content['hash'][:12]}, {content.get('origin')} "
        f"{str(content.get('set_at'))[:10]} by {content.get('set_by')}; "
        'full list: show_metadata(path, section="content")'
    )


def _print_group_content(icestore, group_name: str, branch: str) -> None:
    """Terminal port of IcechunkStoreViewer's per-group HTML drill-down:
    plain-text xarray Dataset repr + metadata table, in a rich.Tree:
    same content, no browser/notebook required."""
    tree = Tree(f"[bold]{group_name}[/bold] (branch: {branch})")

    try:
        ds = icestore.read_group(group_name, branch=branch)
        tree.add(f"[bold]Dataset[/bold]\n{ds}")
    except Exception as e:
        tree.add(f"[red]Failed to load dataset: {e}[/red]")

    try:
        with icestore.readonly_session(branch) as session:
            metadata_df = icestore.load_metadata(session.store, group_name)
        tree.add(
            f"[bold]Metadata table[/bold] ({len(metadata_df)} rows)\n{metadata_df}"
        )
    except Exception:
        pass  # not every group has a metadata table; skip it

    console.print(tree)


@store_app.command()
def log(
    site: Annotated[
        str | None,
        typer.Argument(
            help="Site name, as defined under sites: in canvod-settings.yaml. Omit when using --path."
        ),
    ] = None,
    store: Annotated[
        str,
        typer.Option("--store", metavar="gnss|vod", help="Store of the site to open."),
    ] = "gnss",
    path: Annotated[
        str | None,
        typer.Option(
            "--path",
            metavar="STORE",
            help=(
                "Open the store at this local path or s3://bucket/prefix "
                "instead of a site's store, for example a copy. Needs no settings file."
            ),
        ),
    ] = None,
    branch: Annotated[
        str | None,
        typer.Option(
            "--branch",
            help="Show the history of this branch only. Default: all branches.",
        ),
    ] = None,
    ops: Annotated[
        bool,
        typer.Option(
            "--ops",
            help="Show the operations on the store instead of the commit graph.",
        ),
    ] = False,
    limit: Annotated[
        int, typer.Option("--limit", help="Number of operations that --ops shows.")
    ] = 50,
    svg: Annotated[
        Path | None,
        typer.Option(
            "--svg",
            metavar="FILE",
            help="Write the commit graph to this SVG file instead of printing it.",
        ),
    ] = None,
    plain: Annotated[
        bool,
        typer.Option(
            "--plain",
            help="Draw the commit graph without colors, for a file or a CI log.",
        ),
    ] = False,
    config_dir: Annotated[Path | None, CONFIG_DIR_OPTION] = None,
) -> None:
    """Show the commit history as a graph, or the store operations with --ops."""
    if ops and svg is not None:
        console.print(
            "[red]❌ --svg writes the commit graph; it doesn't go with --ops.[/red]"
        )
        raise typer.Exit(1)
    if site is not None and path is None:
        if store not in _STORE_KINDS:
            console.print(
                f"[red]❌ --store must be one of: {', '.join(_STORE_KINDS)}[/red]"
            )
            raise typer.Exit(1)
        icestore = _open_store(site, store)
    elif path is not None and site is None:
        icestore = _open_path(path)
    else:
        console.print("[red]❌ Give a site or --path: one of them, not both.[/red]")
        raise typer.Exit(1)

    if ops:
        icestore.print_ops_log(limit=limit)
        return
    graph = icestore.plot_commit_graph(branch=branch, plain=plain)
    if svg is None:
        print(graph)
        return
    svg.write_text(graph._repr_svg_(), encoding="utf-8")
    console.print(f"[green]✓ Wrote[/green] {svg}")


def _open_path(path: str):
    """The store at ``path`` (local or ``s3://``), opened without settings.

    Exits with a message that names the path if no store is there or the
    storage can't be reached.
    """
    from canvod.store import MyIcechunkStore
    from canvod.store_metadata import store_exists
    from canvod.store_metadata.location import StorageUnreachableError

    try:
        exists = store_exists(path)
    except (StorageUnreachableError, ValueError) as exc:
        console.print(f"[red]❌ {exc}[/red]")
        raise typer.Exit(1) from None
    if not exists:
        console.print(f"[red]❌ No store at[/red] {path}")
        raise typer.Exit(1)
    return MyIcechunkStore(path, store_type=_folder_store_type(path) or "gnss_store")


@store_app.command()
def maintain(
    site: Annotated[
        str,
        typer.Argument(
            help="Site name, as defined under sites: in canvod-settings.yaml"
        ),
    ],
    store: Annotated[
        str, typer.Option("--store", metavar="gnss|vod", help="Store to open.")
    ] = "gnss",
    expire_days: Annotated[
        int,
        typer.Option(
            "--expire-days",
            help="Keep the snapshots of this many past days. Use weeks to months, not hours.",
        ),
    ] = 90,
    gc: Annotated[
        bool, typer.Option("--gc/--no-gc", help="Run garbage collection")
    ] = True,
    execute: Annotated[
        bool,
        typer.Option(
            "--execute",
            help=(
                "Expire snapshots and collect garbage, after you confirm. "
                "Without this flag the command only reports and changes "
                "nothing."
            ),
        ),
    ] = False,
    config_dir: Annotated[Path | None, CONFIG_DIR_OPTION] = None,
) -> None:
    """Expire old snapshots of one site's store and collect garbage.

    Without --execute, this is a dry run: it reports what garbage
    collection would delete and how many snapshots of the main branch are
    older than the cutoff, and changes nothing. With --execute, it asks
    for confirmation, expires the old snapshots and, unless you pass
    --no-gc, collects garbage.

    Don't run it while a canvodpy run writes to the same store.

    On a store on S3, maintenance is a dry run only: a store there may be
    written by several machines, so ``--execute`` is refused (exit 1) and
    only the report is printed.
    """
    if store not in _STORE_KINDS:
        console.print(
            f"[red]❌ --store must be one of: {', '.join(_STORE_KINDS)}[/red]"
        )
        raise typer.Exit(1)

    from datetime import UTC, datetime, timedelta

    icestore = _open_store(site, store)
    on_s3 = isinstance(icestore.location, S3StoreLocation)
    cutoff = datetime.now(UTC) - timedelta(days=expire_days)

    if not execute or on_s3:
        console.print(
            f"\n[bold]{site}[/bold]: {store} store, [yellow]DRY RUN[/yellow] "
            f"(cutoff: {cutoff.isoformat()})\n"
        )

        if on_s3:
            console.print(
                "[dim]Maintenance on a store on S3 is not supported yet "
                "(another machine may be writing to it): a dry run only.[/dim]\n"
            )

        if gc:
            gc_result = icestore.garbage_collect(days=expire_days, dry_run=True)
            console.print("[bold]Would garbage-collect:[/bold]")
            for key in (
                "bytes_deleted",
                "chunks_deleted",
                "manifests_deleted",
                "snapshots_deleted",
                "attributes_deleted",
                "transaction_logs_deleted",
            ):
                console.print(f"  {key}: {gc_result[key]}")
        else:
            console.print("[dim]--no-gc: skipping garbage-collect dry run.[/dim]")

        stale = sum(
            1
            for snap in icestore.repo.ancestry(branch="main")
            if snap.written_at < cutoff
        )
        console.print(f"\n[bold]Ancestry entries older than cutoff:[/bold] {stale}")
        if on_s3:
            console.print(
                "\n[dim]Nothing was deleted or expired.[/dim]\n"
                "[yellow]--execute is not supported on S3 yet.[/yellow]"
            )
        else:
            console.print(
                "\n[dim]Nothing was deleted or expired. Re-run with --execute "
                "to actually run maintenance (after confirming).[/dim]"
            )
        if execute:
            raise typer.Exit(1)
        return

    console.print(
        f"\n[bold red]About to run maintenance on {site} ({store} store)[/bold red]"
    )
    console.print(f"  Cutoff: {cutoff.isoformat()} ({expire_days} days)")
    console.print(f"  Garbage collection: {'yes' if gc else 'no'}")
    console.print(
        "\n[yellow]This is an administrative operation. Do not run it while "
        "a pipeline run is active against this store.[/yellow]"
    )
    if not typer.confirm("Proceed?"):
        console.print("Aborted.")
        raise typer.Exit(0)

    results = icestore.maintenance(expire_days=expire_days, run_gc=gc)
    console.print("\n[bold green]Maintenance complete:[/bold green]")
    console.print(f"  Expired snapshots: {results['expired_snapshots']}")
    console.print(f"  Deleted branches:  {results['deleted_branches']}")
    if results["gc_summary"] is not None:
        console.print(f"  GC summary:        {results['gc_summary']}")


@store_app.command("maintain-due")
def maintain_due(
    site: Annotated[
        str | None,
        typer.Argument(help="Site name. Omit when using --all-sites."),
    ] = None,
    all_sites: Annotated[
        bool,
        typer.Option("--all-sites", help="Run for every site in canvod-settings.yaml."),
    ] = False,
    store: Annotated[
        str,
        typer.Option("--store", metavar="gnss|vod|both", help="Store to maintain."),
    ] = "both",
    config_dir: Annotated[Path | None, CONFIG_DIR_OPTION] = None,
) -> None:
    """Run only the store maintenance that's due, without prompting.

    Use this command, not maintain, in scheduled jobs such as cron: it
    never asks for confirmation, and it exits with status 0 when nothing
    is due. It reads processing.storage.maintenance in
    canvod-settings.yaml and does nothing unless both of these hold:

    \b
    - maintenance.enabled or maintenance.manifests_enabled is true. Both
      are false by default. Before you set them, run
      canvodpy store maintain SITE, which is a dry run, on your store and
      check its report.
    - No canvodpy run is active on this computer.

    maintenance.enabled allows snapshot expiry and garbage collection.
    Expiry is due when the last one ran more than
    maintenance.expire_interval_days ago, or never ran. Garbage
    collection is due maintenance.gc_delay_days after an expiry, once per
    expiry. maintenance.manifests_enabled allows manifest compaction,
    which is due when the store holds at least
    maintenance.manifest_count_threshold manifest files.

    While maintenance.dry_run_until_confirmed is true, the default, a
    store that's due is only reported, not changed. Set it to
    false once the reports look right.

    On a store on S3, maintenance is a dry run only: a store there may
    be written by several machines, so a due store is always reported,
    never changed, and this command still exits 0 (a cron job does not
    fail overnight).
    """
    if store == "both":
        store_kinds = _STORE_KINDS
    elif store in _STORE_KINDS:
        store_kinds = (store,)
    else:
        console.print(
            f"[red]❌ --store must be one of: both, {', '.join(_STORE_KINDS)}[/red]"
        )
        raise typer.Exit(1)

    if bool(site) == all_sites:
        console.print("[red]❌ Pass exactly one of: a site name, or --all-sites[/red]")
        raise typer.Exit(1)

    from canvod.config import load_config
    from canvod.store_metadata import store_exists
    from canvodpy.orchestrator.resources import is_pipeline_running

    config = load_config()
    mcfg = config.processing.storage.maintenance

    if not mcfg.enabled and not mcfg.manifests_enabled:
        console.print(
            "[dim]maintenance.enabled and maintenance.manifests_enabled are "
            "both false in canvod-settings.yaml -- nothing to do.[/dim]"
        )
        return

    if is_pipeline_running():
        console.print(
            "[yellow]⊘ A canvodpy run is active on this host -- skipping "
            "(never run maintenance alongside active writes).[/yellow]"
        )
        return

    if all_sites:
        site_names = list(config.sites.sites)
    else:
        # The `bool(site) == all_sites` guard above already ensures site is
        # truthy here (exactly one of site/--all-sites is set) -- assert
        # narrows the type for ty rather than leaving it `str | None`.
        assert site is not None
        if site not in config.sites.sites:
            console.print(f"[red]❌ Unknown site:[/red] {site}")
            raise typer.Exit(1)
        site_names = [site]

    for site_name in site_names:
        for kind in store_kinds:
            storage = config.processing.storage
            path = (
                storage.get_gnss_store_path(site_name)
                if kind == "gnss"
                else storage.get_vod_store_path(site_name)
            )
            if not store_exists(path):
                console.print(
                    f"[dim]{site_name} ({kind}): no store yet, skipping.[/dim]"
                )
                continue

            from canvod.store import MyIcechunkStore

            icestore = MyIcechunkStore(
                path, store_type="gnss_store" if kind == "gnss" else "vod_store"
            )
            on_s3 = isinstance(icestore.location, S3StoreLocation)
            due = icestore.maintenance_due(
                expire_interval_days=mcfg.expire_interval_days,
                gc_delay_days=mcfg.gc_delay_days,
                manifest_count_threshold=(
                    mcfg.manifest_count_threshold if mcfg.manifests_enabled else None
                ),
            )
            if not mcfg.enabled:
                # expire/GC stay gated on `enabled` specifically --
                # `manifests_enabled` only ever authorizes compaction.
                due["expire_due"] = False
                due["gc_due"] = False

            if not due["expire_due"] and not due["gc_due"] and not due["manifests_due"]:
                console.print(
                    f"[dim]{site_name} ({kind}): not due "
                    f"(last expire: {due['last_expire']}, "
                    f"last gc: {due['last_gc']}, "
                    f"manifests: {due['manifest_count']}).[/dim]"
                )
                continue

            console.print(
                f"\n[bold]{site_name}[/bold] ({kind}) -- due: "
                f"expire={due['expire_due']} gc={due['gc_due']} "
                f"manifests={due['manifests_due']}"
            )

            dry_run = on_s3 or mcfg.dry_run_until_confirmed
            if dry_run:
                header = (
                    "DRY RUN (store on S3: maintenance on S3 is not supported yet)"
                    if on_s3
                    else "DRY RUN (maintenance.dry_run_until_confirmed=true)"
                )
                console.print(f"[yellow]{header}[/yellow]")
                if due["gc_due"]:
                    gc_result = icestore.garbage_collect(
                        days=mcfg.retention_days, dry_run=True
                    )
                    console.print(f"  Would garbage-collect: {gc_result}")
                if due["expire_due"]:
                    from datetime import UTC, datetime, timedelta

                    cutoff = datetime.now(UTC) - timedelta(days=mcfg.retention_days)
                    stale = sum(
                        1
                        for snap in icestore.repo.ancestry(branch="main")
                        if snap.written_at < cutoff
                    )
                    console.print(
                        f"  Would expire: {stale} ancestry entries older than cutoff"
                    )
                if due["manifests_due"]:
                    # rewrite_manifests() has no dry-run mode -- report the
                    # fragmentation count that triggered due-ness instead.
                    console.print(
                        f"  Would compact manifests: {due['manifest_count']} "
                        f">= threshold {mcfg.manifest_count_threshold}"
                    )
                continue

            if due["expire_due"]:
                expired = icestore.expire_old_snapshots(days=mcfg.retention_days)
                console.print(f"  Expired: {len(expired)} snapshots")
            if due["gc_due"]:
                gc_result = icestore.garbage_collect(
                    days=mcfg.retention_days, dry_run=False
                )
                console.print(f"  GC: {gc_result}")
            if due["manifests_due"]:
                snapshot_id = icestore.compact_manifests(branch="main")
                console.print(f"  Compacted manifests: snapshot {snapshot_id}")


@store_app.command("migrate-metadata")
def migrate_metadata_command(
    site: Annotated[
        str,
        typer.Argument(
            help="Site name, as defined under sites: in canvod-settings.yaml"
        ),
    ],
    store: Annotated[
        str, typer.Option("--store", metavar="gnss|vod", help="Store to migrate.")
    ] = "gnss",
    naming_authority: Annotated[
        str | None,
        typer.Option(
            "--naming-authority",
            help=(
                "Your institution's domain in reverse order, for example "
                "org.middle-earth. Default: the store's own, if it is a reverse "
                "DNS name; otherwise processing.metadata.naming_authority in "
                "the settings."
            ),
        ),
    ] = None,
    set_values: Annotated[
        list[str] | None,
        typer.Option(
            "--set",
            metavar="field.path=value",
            help="A field or content setting the store lacks, for example identity.description=Beech forest site, or sites.my_site.receivers.reference_01.paired_canopies=[canopy_01]. Repeat for more.",
        ),
    ] = None,
    yes: Annotated[bool, typer.Option("--yes", help="Migrate without asking.")] = False,
    config_dir: Annotated[Path | None, CONFIG_DIR_OPTION] = None,
) -> None:
    """Move a store written before repository metadata to the current form.

    Writes the store's description into its repository metadata, gives it
    a new store id, made of the site name in lowercase and the store kind,
    and a UUID, and keeps the old id in the migration record. Snapshots
    from before stay readable.

    The migrated store must pass the standards checks: fields the store
    lacks, such as its description, are given with --set, otherwise the
    migration is refused and lists them. In a VOD store, the attributes of
    VOD are replaced with the current ones: older versions copied the
    attributes of SNR and theta to VOD, among them the valid range of theta.
    A VOD store also lists each VOD analysis it holds a group of, with its
    receivers from the settings. The migration record keeps who migrated
    the store, the initials set in processing.metadata.initials.

    Fields the store lacks and the settings hold are taken from them: the
    site's store_description, the publisher and license, the site's
    latitude and longitude. A value given with --set wins.

    canVODpy 0.x stored epochs without recording their time scale. The
    epochs of groups read from RINEX files are GPS time and are recorded
    as such; a VOD store's, when its site's GNSS store holds RINEX epochs
    only. A group read from SBF or NMEA files holds UTC epochs: the
    command stops, and the store is rebuilt from the raw files.

    A GNSS or VOD store also gets its content settings (ADR 0019), also
    when it was moved to repository metadata before: the settings that
    shape its data, taken from the settings recorded in its first commit.
    A setting that commit does not record is not guessed: the command
    stops and lists it, to be given with --set by its key in
    canvod-settings.yaml. A setting the data show (the preprocessing,
    store_delta_snr, store_radial_diff, store_radial_distance) is read
    from the data: canVODpy 0.x recorded settings its runs didn't follow.
    """
    _migrate_metadata(site, store, naming_authority, set_values, yes=yes)


def _migrate_metadata(
    site: str,
    store: str,
    naming_authority: str | None,
    set_values: list[str] | None,
    *,
    yes: bool,
    command: str | None = None,
    set_option: str = "--set",
) -> None:
    """migrate-metadata; ``command`` and ``set_option`` are what an error
    names for giving a missing value (``canvodpy store migrate`` passes its
    own).
    """
    from canvod.config import load_config
    from canvod.store_metadata import read_metadata
    from canvod.store_metadata.migration import epochs_to_label

    path, _ = _store_path(site, store)
    try:
        old = read_metadata(path)
    except KeyError:
        console.print(
            f"[red]❌ The {store} store of '{site}' has no store metadata.[/red]"
        )
        raise typer.Exit(1) from None
    store_type = old.identity.store_type
    values = _amend_changes(site, store_type, set_values or [], [], [], [])
    content_values = {k: v for k, v in values.items() if _is_content_key(k)}
    values = {k: v for k, v in values.items() if k not in content_values}
    # Each store's migration reads the other store of the site: a VOD
    # store's epochs and content-settings hash come from the GNSS store,
    # and the GNSS store records VOD settings the VOD data show.
    storage = load_config().processing.storage
    gnss_store = (
        storage.get_gnss_store_path(site) if store_type == "vod_store" else None
    )
    vod_store = storage.get_vod_store_path(site) if store_type == "gnss_store" else None
    # Checked before anything is written: a store whose epochs cannot be
    # labelled is rebuilt, not migrated.
    try:
        unlabelled = epochs_to_label(path, gnss_store=gnss_store)
    except ValueError as exc:
        console.print(f"[red]❌ {exc}[/red]")
        raise typer.Exit(1) from None

    asked = False
    if old.written_before_migration:
        _migrate_repository_metadata(
            site,
            store,
            path,
            old,
            naming_authority,
            values,
            yes=yes,
            set_option=set_option,
        )
        asked = True
    elif values:
        console.print(
            f"[red]❌ The {store} store of '{site}' is already migrated; change "
            f"{', '.join(values)} with canvodpy store amend.[/red]"
        )
        raise typer.Exit(1)
    if unlabelled:
        _label_epoch_time_system(
            site, store, path, unlabelled, gnss_store, yes=yes or asked
        )
        asked = True
    if (
        not _migrate_content_settings(
            site,
            store,
            path,
            store_type,
            content_values,
            gnss_store,
            vod_store,
            yes=yes or asked,
            command=command,
            set_option=set_option,
        )
        and not asked
    ):
        console.print(
            f"[green]✓ The {store} store of '{site}' is already migrated.[/green]"
        )


def _label_epoch_time_system(
    site: str,
    store: str,
    path: Path | str,
    groups: list[str],
    gnss_store: Path | str | None,
    *,
    yes: bool,
) -> None:
    """Record GPS time on epochs canVODpy 0.x stored without a time scale."""
    from canvod.store_metadata.migration import label_epoch_time_system

    console.print(f"\n[bold]{site}[/bold]: {store} store ({path})")
    console.print(
        "  Epochs:            recorded as GPS time, stored by canVODpy 0.x "
        "without their time scale"
    )
    for group in groups:
        console.print(f"    {group}")
    if not yes and not typer.confirm("Record the time scale of the epochs?"):
        raise typer.Exit(1)
    try:
        _, snapshot_id = label_epoch_time_system(path, gnss_store=gnss_store)
    except ValueError as exc:
        console.print(f"[red]❌ {exc}[/red]")
        raise typer.Exit(1) from None
    console.print(
        f"[green]✓ Epochs recorded as GPS time[/green] "
        f"(snapshot {(snapshot_id or '')[:12]})"
    )


def _is_content_key(field: str) -> bool:
    """Whether a --set field of migrate-metadata names a content setting."""
    from canvod.store_metadata.content import GNSS_CONTENT_HASH, SETTINGS_ROOTS

    if field == GNSS_CONTENT_HASH:
        return True
    return field.split(".", 1)[0] in SETTINGS_ROOTS


def _migrate_repository_metadata(
    site: str,
    store: str,
    path: Path | str,
    old: StoreMetadata,
    naming_authority: str | None,
    values: dict[str, object],
    *,
    yes: bool,
    set_option: str = "--set",
) -> None:
    """Move a store's metadata to repository metadata (ADR 0014)."""
    from canvod.config.store_names import store_folder_name
    from canvod.store_metadata import migrate_metadata
    from canvod.store_metadata.identity import check_naming_authority, store_id

    who = _who()
    from_settings = {
        field: value
        for field, value in _fields_from_settings(site, old).items()
        if field not in values
    }
    from_groups = {
        field: value
        for field, value in _vod_analyses_from_groups(site, path, old).items()
        if field not in values
    }
    source = "--naming-authority"
    if naming_authority is None:
        source = "the store"
        try:
            check_naming_authority(old.identity.naming_authority)
        except ValueError:
            # The store has none, or one that is not reverse DNS (older
            # versions described the field as a URI).
            from canvod.config import load_config

            naming_authority = load_config().processing.metadata.naming_authority
            if naming_authority:
                source = "the settings, processing.metadata.naming_authority"
    new_id = store_id(
        old.spatial.site.name, old.identity.store_type, store_folder_name(path)
    )
    console.print(f"\n[bold]{site}[/bold]: {store} store ({path})")
    console.print(f"  Store id:          {old.identity.id} -> {new_id}")
    console.print(f"  Who:               {who}")
    console.print(
        "  Naming authority:  "
        f"{naming_authority or old.identity.naming_authority or '(none)'}"
        f" (from {source})"
    )
    for field, value in values.items():
        console.print(f"  Set {field}: {value!r}")
    for field, value in from_settings.items():
        console.print(f"  Set {field}: {value!r} (from the settings)")
    for field, value in from_groups.items():
        console.print(
            f"  Set {field}: {value!r} (its group is in the store; receivers "
            "from the settings)"
        )
    values = {**from_settings, **from_groups, **values}
    variable_attrs = {}
    if old.identity.store_type == "vod_store":
        from canvod.vod.calculator import VOD_ATTRS

        variable_attrs = {"VOD": VOD_ATTRS}
        console.print("  VOD attributes:   replaced with the current ones")
    if not yes and not typer.confirm("Migrate the store metadata?"):
        raise typer.Exit(1)

    try:
        snapshot_id = migrate_metadata(
            path,
            who=who,
            naming_authority=naming_authority,
            values=values,
            variable_attrs=variable_attrs,
            set_option=set_option,
        )
    except ValueError as exc:
        console.print(f"[red]❌ {exc}[/red]")
        raise typer.Exit(1) from None
    console.print(f"[green]✓ Migrated[/green] (snapshot {snapshot_id[:12]})")


def _fields_from_settings(site: str, old: StoreMetadata) -> dict[str, object]:
    """Fields an old store lacks that the settings hold, by dotted path.

    The site's store description, the publisher and license, the site's
    position: what a new store takes from the settings when it is created.
    """
    from canvod.config import load_config
    from canvod.store_metadata.collectors import (
        _site_store_description,
        collect_publisher,
    )

    config = load_config()
    meta_cfg = config.processing.metadata
    site_cfg = config.sites.sites[site]
    publisher = collect_publisher(meta_cfg)
    candidates: dict[str, tuple[object, object]] = {
        "identity.description": (
            old.identity.description,
            _site_store_description(site_cfg, meta_cfg) or None,
        ),
        "publisher.name": (old.publisher.name, publisher.name),
        "publisher.url": (
            old.publisher.url,
            str(publisher.url) if publisher.url else None,
        ),
        "publisher.license": (old.publisher.license, publisher.license),
        "publisher.license_uri": (
            old.publisher.license_uri,
            str(publisher.license_uri) if publisher.license_uri else None,
        ),
        "spatial.geospatial_lat": (
            old.spatial.geospatial_lat,
            getattr(site_cfg, "latitude", None),
        ),
        "spatial.geospatial_lon": (
            old.spatial.geospatial_lon,
            getattr(site_cfg, "longitude", None),
        ),
    }
    return {
        field: new
        for field, (stored, new) in candidates.items()
        if stored is None and new is not None
    }


def _vod_analyses_from_groups(
    site: str, path: Path | str, old: StoreMetadata
) -> dict[str, object]:
    """VOD analyses an old VOD store holds groups of but does not list.

    canVODpy 0.x listed no VOD analyses. A data group
    ``{calculator}/{analysis}`` shows the analysis; its receivers come from
    the settings (``sites.<site>.vod_analyses``), as ``canvodpy store amend
    --add-vod-analysis`` takes them. An analysis the settings do not define
    is left out.
    """
    import zarr

    from canvod.config import load_config
    from canvod.store_metadata.location import open_repository, store_location
    from canvod.store_metadata.snapshot import RESERVED_GROUP

    if old.identity.store_type != "vod_store":
        return {}
    analyses = load_config().sites.sites[site].vod_analyses or {}
    session = open_repository(store_location(path)).readonly_session(branch="main")
    root = zarr.open_group(session.store, mode="r")
    held = {
        name
        for calculator, group in root.groups()
        if calculator != RESERVED_GROUP
        for name, _ in group.groups()
    }
    listed = set(old.vod_analyses or {})
    return {
        f"vod_analyses.{name}": {
            "canopy_receiver": analyses[name].canopy_receiver,
            "reference_receiver": analyses[name].reference_receiver,
        }
        for name in sorted((held & set(analyses)) - listed)
    }


def _migrate_content_settings(
    site: str,
    store: str,
    path: Path | str,
    store_type: str,
    values: dict[str, object],
    gnss_store: Path | str | None = None,
    vod_store: Path | str | None = None,
    *,
    yes: bool,
    command: str | None = None,
    set_option: str = "--set",
) -> bool:
    """Give a store its content settings from its first commit (ADR 0019).

    Returns whether they were written; ``False`` if the store has them or
    its type keeps none.
    """
    from canvod.store_metadata import read_repository_metadata
    from canvod.store_metadata.content import (
        CONTENT_SETTINGS_FIELD,
        CONTENT_STORE_TYPES,
    )
    from canvod.store_metadata.migration import (
        first_recorded_settings,
        migrate_content_settings,
    )

    if store_type not in CONTENT_STORE_TYPES:
        if values:
            console.print(f"[red]❌ A {store} store keeps no content settings.[/red]")
            raise typer.Exit(1)
        return False
    if read_repository_metadata(path).get(CONTENT_SETTINGS_FIELD):
        if values:
            console.print(
                f"[red]❌ The {store} store of '{site}' already has content "
                "settings; they never change. Write to a new store instead.[/red]"
            )
            raise typer.Exit(1)
        return False
    who = _who()
    first = first_recorded_settings(path)
    console.print(f"\n[bold]{site}[/bold]: {store} store ({path})")
    console.print(
        "  Content settings:  from the settings of the first commit"
        + (f" (snapshot {first[0][:12]})" if first else "")
    )
    for field, value in values.items():
        console.print(f"  Set {field}: {value!r}")
    if not yes and not typer.confirm("Write the content settings?"):
        raise typer.Exit(1)
    try:
        snapshot_id = migrate_content_settings(
            path,
            who=who,
            values=values,
            gnss_store=gnss_store,
            vod_store=vod_store,
            command=command,
            set_option=set_option,
        )
    except ValueError as exc:
        console.print(f"[red]❌ {exc}[/red]")
        raise typer.Exit(1) from None
    console.print(
        f"[green]✓ Content settings written[/green] (snapshot {snapshot_id[:12]})"
    )
    return True


def _who() -> str:
    """Who changes a store's metadata: the initials in the settings."""
    from canvod.config import load_config
    from canvod.store_metadata.io import INITIALS_SETTING

    who = load_config().processing.metadata.initials
    if not who or not who.strip():
        console.print(
            "[red]❌ A change of store metadata records who made it: set "
            f"{INITIALS_SETTING} in the settings (e.g. 'NFB').[/red]"
        )
        raise typer.Exit(1)
    return who.strip()


def _amend_changes(
    site: str,
    store_type: str,
    set_values: list[str],
    add_receivers: list[str],
    add_vod_analyses: list[str],
    update_recipes: list[str],
) -> dict[str, object]:
    """The changes of an amendment, with receiver and VOD analysis entries
    and naming recipes taken from the settings."""
    import yaml

    from canvod.config import load_config
    from canvod.store_metadata.collectors import collect_receiver, recipe_sha256_of
    from canvod.store_metadata.schema import RepositoryReceiver
    from canvod.utils.remote_file import recorded_name

    changes: dict[str, object] = {}
    for item in set_values:
        field, sep, value = item.partition("=")
        if not sep:
            console.print(f"[red]❌ --set takes field.path=value, not {item!r}[/red]")
            raise typer.Exit(1)
        if not value.strip():
            console.print(
                f"[red]❌ --set {field.strip()}= has no value; give one after "
                "the =.[/red]"
            )
            raise typer.Exit(1)
        changes[field.strip()] = yaml.safe_load(value)

    site_cfg = load_config().sites.sites[site]
    for name in add_receivers:
        if name not in site_cfg.receivers:
            console.print(
                f"[red]❌ {name!r} is not a receiver of '{site}' in the settings "
                f"(sites.{site}.receivers).[/red]"
            )
            raise typer.Exit(1)
        receiver = collect_receiver(site_cfg.receivers[name], site)
        if receiver.recipe and receiver.recipe_sha256 is None:
            _refuse_missing_recipe(site, name, receiver.recipe)
        if store_type == "vod_store":
            # A VOD store reads the hardware from the GNSS store's entries.
            receiver = receiver.model_copy(
                update={"receiver_hardware": None, "antenna": None}
            )
        changes[f"instruments.receivers.{name}"] = receiver.model_dump(
            mode="json", include=set(RepositoryReceiver.model_fields)
        )
    for name in update_recipes:
        if name not in site_cfg.receivers:
            console.print(
                f"[red]❌ {name!r} is not a receiver of '{site}' in the settings "
                f"(sites.{site}.receivers).[/red]"
            )
            raise typer.Exit(1)
        recipe = site_cfg.receivers[name].recipe
        sha256 = recipe_sha256_of(site, recipe) if recipe else None
        if recipe and sha256 is None:
            _refuse_missing_recipe(site, name, recipe)
        changes[f"instruments.receivers.{name}.recipe"] = (
            recorded_name(recipe) if recipe else recipe
        )
        changes[f"instruments.receivers.{name}.recipe_sha256"] = sha256
    analyses = site_cfg.vod_analyses or {}
    for name in add_vod_analyses:
        if name not in analyses:
            console.print(
                f"[red]❌ {name!r} is not a VOD analysis of '{site}' in the settings "
                f"(sites.{site}.vod_analyses).[/red]"
            )
            raise typer.Exit(1)
        changes[f"vod_analyses.{name}"] = {
            "canopy_receiver": analyses[name].canopy_receiver,
            "reference_receiver": analyses[name].reference_receiver,
        }
    return changes


def _refuse_missing_recipe(site: str, receiver: str, recipe: str) -> None:
    from canvodpy.orchestrator.discovery import FILEMAP_INSTALL_HINT

    console.print(
        f"[red]❌ Found no naming recipe {recipe!r} of receiver {receiver!r}, "
        f"so its sha256 can't be recorded. If canvod-filemap is missing: "
        f"{FILEMAP_INSTALL_HINT} Then check that `canvodpy config validate "
        f"--site {site}` finds the recipe.[/red]"
    )
    raise typer.Exit(1)


@store_app.command("migrate-layout")
def migrate_layout_command(
    site: Annotated[
        str,
        typer.Argument(
            help="Site name, as defined under sites: in canvod-settings.yaml"
        ),
    ],
    store: Annotated[
        str, typer.Option("--store", metavar="gnss|vod", help="Store to move.")
    ] = "gnss",
    yes: Annotated[bool, typer.Option("--yes", help="Move without asking.")] = False,
    config_dir: Annotated[Path | None, CONFIG_DIR_OPTION] = None,
) -> None:
    """Move a store written by appending files to day blocks (ADR 0016).

    Runs write day blocks only, so a store whose groups were written by
    appending has to be moved first. Each such group is written again, day
    by day: every day gets a block of slots at its cadence, the finest step
    between its epochs. An epoch stored more than once keeps the entry
    written last. The groups keep their attributes, log books and other
    metadata, and get the chunks of the settings
    (`processing.icechunk.chunk_strategies`).

    Shows what it will do and asks first. Everything goes into one commit;
    snapshots from before stay readable. A store written before repository
    metadata is moved with canvodpy store migrate SITE.
    """
    from canvod.config import load_config
    from canvod.store.day_blocks import CadenceError
    from canvod.store.migrate_layout import (
        NOTHING,
        migrate_layout,
        plan_layout_migration,
    )
    from canvod.store_metadata.layout import LayoutError

    path, _ = _store_path(site, store)
    try:
        plans = plan_layout_migration(path)
    except (ValueError, LayoutError, CadenceError) as exc:
        console.print(f"[red]❌ {exc}[/red]")
        raise typer.Exit(1) from None
    if all(plan.action == NOTHING for plan in plans):
        console.print(
            f"[green]✓ The {store} store of '{site}' is made of day blocks "
            "already.[/green]"
        )
        return

    console.print(f"\n[bold]{site}[/bold]: {store} store ({path})")
    table = Table(show_header=True)
    table.add_column("Group")
    table.add_column("Change")
    table.add_column("Days", justify="right")
    table.add_column("Cadences (s)")
    table.add_column("Epochs", justify="right")
    table.add_column("Duplicates", justify="right")
    changes = {
        "rewrite": "rewrite",
        "index": "add block index",
        "nothing": "none",
    }
    for plan in plans:
        cadences = sorted(set(plan.cadences.values()))
        table.add_row(
            plan.group,
            changes[plan.action],
            str(len(plan.cadences)),
            ", ".join(f"{c:g}" for c in cadences),
            str(plan.epochs) if plan.action == "rewrite" else "",
            str(plan.duplicates) if plan.action == "rewrite" else "",
        )
    console.print(table)
    if not yes and not typer.confirm("Move the store to day blocks?"):
        raise typer.Exit(1)

    config = load_config()
    icestore = _open_store(site, store)
    chunks = dict(icestore.chunk_strategy or {})
    epoch_chunk = int(chunks.pop("epoch", 180))
    try:
        result = migrate_layout(
            path, epoch_chunk=epoch_chunk, dim_chunks=chunks, config=config
        )
    except (ValueError, LayoutError, CadenceError) as exc:
        console.print(f"[red]❌ {exc}[/red]")
        raise typer.Exit(1) from None
    for plan in result.groups:
        if plan.unlogged:
            console.print(
                f"[yellow]⚠ {plan.group}: {plan.unlogged} epochs are covered "
                "by no log-book row; the snapshot summary does not count "
                "them.[/yellow]"
            )
    snapshot = (result.snapshot_id or "")[:12]
    console.print(f"[green]✓ Moved to day blocks[/green] (snapshot {snapshot})")


@store_app.command()
def amend(
    site: Annotated[
        str,
        typer.Argument(
            help="Site name, as defined under sites: in canvod-settings.yaml"
        ),
    ],
    store: Annotated[
        str, typer.Option("--store", metavar="gnss|vod", help="Store to amend.")
    ] = "gnss",
    set_values: Annotated[
        list[str] | None,
        typer.Option(
            "--set",
            metavar="field.path=value",
            help="New value of a field, for example identity.title=Rosalia GNSS observations. Repeat for more fields.",
        ),
    ] = None,
    add_receiver: Annotated[
        list[str] | None,
        typer.Option(
            "--add-receiver",
            metavar="name",
            help="Add a receiver of the site's settings to the store, so runs may write it.",
        ),
    ] = None,
    add_vod_analysis: Annotated[
        list[str] | None,
        typer.Option(
            "--add-vod-analysis",
            metavar="name",
            help="Add a VOD analysis of the site's settings to the VOD store.",
        ),
    ] = None,
    update_recipe: Annotated[
        list[str] | None,
        typer.Option(
            "--update-recipe",
            metavar="name",
            help="Record a receiver's naming recipe of the settings and its sha256 in the GNSS store, after the recipe changed on purpose.",
        ),
    ] = None,
    from_file: Annotated[
        Path | None,
        typer.Option(
            "--from",
            metavar="<path>",
            help=(
                "YAML file with the keys reason, set (field paths and values), "
                "and the lists add_receivers, add_vod_analyses and update_recipes."
            ),
        ),
    ] = None,
    reason: Annotated[
        str | None,
        typer.Option("--reason", help="Why the fields change; recorded with each one."),
    ] = None,
    yes: Annotated[bool, typer.Option("--yes", help="Amend without asking.")] = False,
    config_dir: Annotated[Path | None, CONFIG_DIR_OPTION] = None,
) -> None:
    """Change the description of a site's store, with a reason.

    Fixed fields (the store id, UUID, store type, source format, naming
    authority and creation date) never change. Each changed field is
    recorded with its old and new value, the reason, who and when, and a
    new commit carries the new description. Who is the initials set in
    processing.metadata.initials.
    """
    import yaml

    from canvod.config import load_config
    from canvod.store_metadata import amend_metadata, read_repository_metadata
    from canvod.store_metadata.amend import check_amendable
    from canvod.store_metadata.content import receiver_content_settings

    path, store_type = _store_path(site, store)
    set_values = list(set_values or [])
    receivers = list(add_receiver or [])
    vod_analyses = list(add_vod_analysis or [])
    recipes = list(update_recipe or [])
    if from_file is not None:
        spec = yaml.safe_load(from_file.read_text()) or {}
        set_values += [
            f"{k}={yaml.safe_dump(v).strip()}"
            for k, v in (spec.get("set") or {}).items()
        ]
        receivers += list(spec.get("add_receivers") or [])
        vod_analyses += list(spec.get("add_vod_analyses") or [])
        recipes += list(spec.get("update_recipes") or [])
        reason = reason or spec.get("reason")
    if not reason:
        console.print(
            "[red]❌ An amendment needs --reason (or reason: in the --from file).[/red]"
        )
        raise typer.Exit(1)
    if recipes and store_type != "gnss_store":
        console.print(
            "[red]❌ --update-recipe records the recipe in the GNSS store, the "
            "store whose runs read the files: use --store gnss.[/red]"
        )
        raise typer.Exit(1)
    current = read_repository_metadata(path)
    listed = (current.get("instruments") or {}).get("receivers") or {}
    for name in recipes:
        if name not in listed and name not in receivers:
            console.print(
                f"[red]❌ {name!r} is not in the store; add it with "
                f"--add-receiver {name}.[/red]"
            )
            raise typer.Exit(1)
    who = _who()

    changes = _amend_changes(
        site, store_type, set_values, receivers, vod_analyses, recipes
    )
    if not changes:
        console.print(
            "[red]❌ Nothing to change: use --set, --add-receiver, --add-vod-analysis, --update-recipe or --from.[/red]"
        )
        raise typer.Exit(1)

    try:
        for field in changes:
            check_amendable(field)
    except ValueError as exc:
        console.print(f"[red]❌ {exc}[/red]")
        raise typer.Exit(1) from None

    table = Table(title=f"{site}: {store} store", show_lines=False)
    table.add_column("Field")
    table.add_column("Old")
    table.add_column("New")
    for field, value in changes.items():
        old: object = current
        for part in field.split("."):
            old = old.get(part) if isinstance(old, dict) else None
        table.add_row(field, str(old), str(value))
    console.print(table)
    console.print(f"Reason: {reason}")
    console.print(f"Who: {who}")
    if not yes and not typer.confirm("Amend the store metadata?"):
        raise typer.Exit(1)

    config = load_config()
    site_receivers = config.sites.sites[site].receivers
    try:
        snapshot_id = amend_metadata(
            path,
            changes,
            reason=reason,
            who=who,
            config=config,
            receiver_content={
                name: receiver_content_settings(site_receivers[name])
                for name in receivers
            },
        )
    except ValueError as exc:
        console.print(f"[red]❌ {exc}[/red]")
        raise typer.Exit(1) from None
    console.print(f"[green]✓ Amended[/green] (snapshot {snapshot_id[:12]})")


@store_app.command("migrate")
def migrate_command(
    site: Annotated[
        str,
        typer.Argument(
            help="Site name, as defined under sites: in canvod-settings.yaml"
        ),
    ],
    rename: Annotated[
        list[str] | None,
        typer.Option(
            "--rename",
            metavar="OLD=NEW",
            help=(
                "The new name of a store folder whose name is not its kind, "
                "for example vod_2024=vod-2024. rinex is moved to gnss "
                "without it. Repeat for more."
            ),
        ),
    ] = None,
    naming_authority: Annotated[
        str | None,
        typer.Option(
            "--naming-authority",
            help="As for migrate-metadata: your institution's domain in reverse order.",
        ),
    ] = None,
    gnss_set: Annotated[
        list[str] | None,
        typer.Option(
            "--gnss-set",
            metavar="field.path=value",
            help="A field or content setting the GNSS store lacks (migrate-metadata --set). Repeat for more.",
        ),
    ] = None,
    vod_set: Annotated[
        list[str] | None,
        typer.Option(
            "--vod-set",
            metavar="field.path=value",
            help="A field or content setting the VOD store lacks (migrate-metadata --set). Repeat for more.",
        ),
    ] = None,
    yes: Annotated[bool, typer.Option("--yes", help="Migrate without asking.")] = False,
    config_dir: Annotated[Path | None, CONFIG_DIR_OPTION] = None,
) -> None:
    """Move a site's stores from canVODpy 0.x to the current form, in one go.

    1. Folders: a store's folder is named by its kind (gnss, vod), with an
       optional suffix (vod-recompute). The GNSS store's old folder rinex is
       moved to gnss; any other folder whose name is not a kind is moved to
       the name given with --rename. The store id is taken from the new
       folder name.
    2. The GNSS store, then the VOD store: their metadata
       (migrate-metadata), and their groups to day blocks (migrate-layout).
    3. A GNSS store made with CLK files loses its clock variable and records
       fetch_clock: false; since v1.0.0 runs read no CLK files by default,
       and VOD doesn't use the clock. The VOD store records the GNSS store's
       new content-settings hash.

    Shows the plan and asks once. Each step that is done already is
    skipped, so the command can run again after a step failed;
    migrate-metadata and migrate-layout rerun single steps. Snapshots from
    before stay readable in the store's history. Stores on S3 need no
    migration: canVODpy writes stores to S3 since v1.0.0 only.
    """
    from canvod.config import load_config
    from canvod.store_metadata.migration import gnss_content_hash_behind

    config = load_config()
    if site not in config.sites.sites:
        console.print(f"[red]❌ Unknown site:[/red] {site}")
        raise typer.Exit(1)
    storage = config.processing.storage
    if isinstance(storage.stores_root_dir, str):
        console.print(
            "[red]❌ The stores are on S3, which canVODpy writes stores to "
            "since v1.0.0 only: they need no migration.[/red]"
        )
        raise typer.Exit(1)
    site_dir = Path(storage.stores_root_dir) / site
    stores = {
        "gnss": Path(storage.get_gnss_store_path(site)),
        "vod": Path(storage.get_vod_store_path(site)),
    }
    renames, problems = _plan_renames(site_dir, _parse_renames(rename or []))
    moved_to = {new: old for old, new in renames}
    now = {kind: moved_to.get(path, path) for kind, path in stores.items()}
    problems += _refused_ids(stores, now)
    if problems:
        console.print(f"[red]❌ The stores of '{site}' cannot be migrated:[/red]")
        for problem in problems:
            console.print(f"  - {problem}")
        raise typer.Exit(1)

    steps = {kind: _migration_steps(kind, path) for kind, path in now.items()}
    # The VOD store follows a GNSS hash that the clock step changes now, or
    # that a run stopped before the VOD store followed changed already.
    clock_changes = any("fetch_clock" in step for step in steps["gnss"])
    follow = (clock_changes and _has_content_settings(now["vod"])) or (
        gnss_content_hash_behind(now["vod"], now["gnss"])
    )
    if follow:
        steps["vod"].append(FOLLOW_STEP)
    # --gnss-set and --vod-set fill only what a store still lacks: a rerun
    # with the same flags passes the steps done already.
    set_values = {
        "gnss": _values_due(now["gnss"], gnss_set),
        "vod": _values_due(now["vod"], vod_set),
    }
    others = _stores_left_out(site_dir, renames, now)
    if not renames and not any(steps.values()):
        console.print(f"[green]✓ The stores of '{site}' are migrated.[/green]")
        _print_left_out(others)
        return
    console.print(f"\n[bold]{site}[/bold]: stores in {site_dir}")
    for old, new in renames:
        console.print(f"  Move folder:  {old.name}/ -> {new.name}/")
    for kind, kind_steps in steps.items():
        if not kind_steps:
            continue
        console.print(f"  {kind.upper()} store ({stores[kind]}):")
        for step in kind_steps:
            console.print(f"    - {step}")
    _print_left_out(others)
    console.print(
        "  Each step adds a commit; snapshots from before stay readable in "
        "the store's history."
    )
    if not yes and not typer.confirm("Migrate the stores?"):
        raise typer.Exit(1)

    for old, new in renames:
        _move_store_folder(old, new)
        console.print(f"[green]✓ Moved {old.name}/ to {new.name}/[/green]")
    for kind in ("gnss", "vod"):
        if [step for step in steps[kind] if step != FOLLOW_STEP]:
            _migrate_store(site, kind, naming_authority, set_values[kind], config)
    if steps["vod"]:
        _follow_gnss_hash(site, stores, config)
    _print_left_out(others)


def _parse_renames(pairs: list[str]) -> dict[str, str]:
    renames = {}
    for pair in pairs:
        old, sep, new = pair.partition("=")
        if not sep or not old.strip() or not new.strip():
            console.print(f"[red]❌ --rename {pair!r}: write OLD=NEW.[/red]")
            raise typer.Exit(1)
        renames[old.strip()] = new.strip()
    return renames


def _folder_store_type(path: Path | str) -> str | None:
    """A store's type, from its repository metadata or its old-form metadata."""
    from canvod.store_metadata import open_repository, read_metadata

    repository = open_repository(path).get_metadata()
    if repository:
        return repository.get("identity", {}).get("store_type")
    try:
        return read_metadata(path).identity.store_type
    except KeyError, ValueError:
        return None


def _plan_renames(
    site_dir: Path, given: dict[str, str]
) -> tuple[list[tuple[Path, Path]], list[str]]:
    """The folders to move, and why the plan can't go on (if it can't)."""
    from canvod.config.store_names import (
        OLD_GNSS_STORE_NAME,
        StoreNameError,
        check_store_name,
        kind_of_store_name,
        store_kind,
    )
    from canvod.store_metadata import open_repository, store_exists
    from canvod.store_metadata.identity import check_store_folder

    given = dict(given)
    renames: list[tuple[Path, Path]] = []
    problems: list[str] = []
    folders = (
        sorted(p for p in site_dir.iterdir() if p.is_dir() and store_exists(p))
        if site_dir.is_dir()
        else []
    )
    for folder in folders:
        name = folder.name
        if kind_of_store_name(name) is not None:
            if name in given:
                problems.append(f"{name}/ is named by its kind already.")
                given.pop(name)
            continue
        store_type = _folder_store_type(folder)
        try:
            kind = store_kind(store_type or "")
        except ValueError:
            problems.append(f"{name}/: the store records no known store type.")
            continue
        new = given.pop(name, None)
        if new is None and kind == "gnss" and name == OLD_GNSS_STORE_NAME:
            new = kind
        if new is None:
            problems.append(
                f"{name}/ is not named by its kind; give its new name with "
                f"--rename {name}={kind}-SUFFIX (or {kind})."
            )
            continue
        try:
            check_store_name(new, kind)
        except StoreNameError as exc:
            problems.append(f"--rename {name}={new}: {exc}")
            continue
        target = site_dir / new
        if store_exists(target) or target.exists() or target in {n for _, n in renames}:
            problems.append(
                f"{name}/ would move to {new}/, which exists already. Decide "
                "which store to keep and move or remove the other by hand."
            )
            continue
        repository = open_repository(folder).get_metadata()
        if repository and check_store_folder(repository, target):
            problems.append(
                f"{name}/ records the store id "
                f"{repository['identity']['id']!r}, which a folder {new}/ "
                "would not fit."
            )
            continue
        renames.append((folder, target))
    problems += [f"--rename {old}=...: there is no store {old}/." for old in given]
    return renames, problems


def _stores_left_out(
    site_dir: Path, renames: list[tuple[Path, Path]], now: dict[str, Path]
) -> list[Path]:
    """Stores of the site the settings don't point to, not migrated yet.

    The migration steps find a store by the settings (gnss_store_name,
    vod_store_name), so such a store is only moved.
    """
    from canvod.config.store_names import OLD_GNSS_STORE_NAME
    from canvod.store_metadata import store_exists

    if not site_dir.is_dir():
        return []
    moved = dict(renames)
    return [
        moved.get(folder, folder)
        for folder in sorted(site_dir.iterdir())
        if folder.is_dir()
        and store_exists(folder)
        and folder not in now.values()
        and moved.get(folder, folder) not in now.values()
        and folder.name != OLD_GNSS_STORE_NAME
        and not _has_content_settings(folder)
    ]


def _print_left_out(folders: list[Path]) -> None:
    from canvod.config.store_names import kind_of_store_name

    for folder in folders:
        kind = kind_of_store_name(folder.name) or "gnss"
        console.print(
            f"  [yellow]{folder.name}/ is not one of the stores your settings "
            f"name, so it is only moved, not migrated. To migrate it, set "
            f"processing.storage.{kind}_store_name: {folder.name} and run the "
            "command again.[/yellow]"
        )


def _refused_ids(stores: dict[str, Path], now: dict[str, Path]) -> list[str]:
    """Stores that already record an id their folder doesn't fit."""
    from canvod.store_metadata import open_repository, store_exists
    from canvod.store_metadata.identity import check_store_folder

    problems = []
    for kind, path in now.items():
        if path != stores[kind] or not store_exists(path):
            continue  # moved first; checked when its move is planned
        repository = open_repository(path).get_metadata()
        mismatch = check_store_folder(repository, path) if repository else None
        if mismatch:
            problems.append(mismatch)
    return problems


FOLLOW_STEP = "record the GNSS store's new content-settings hash"


def _values_due(path: Path, set_values: list[str] | None) -> list[str] | None:
    """The --set values for steps the store at ``path`` still lacks.

    Fields go with the move to repository metadata, content settings with
    the content-settings step; each is left out once its step is done.
    """
    from canvod.store_metadata import open_repository, store_exists

    if not set_values or not store_exists(path):
        return None
    repository = open_repository(path).get_metadata()
    due = [
        value
        for value in set_values
        if (
            not (repository or {}).get("content_settings")
            if _is_content_key(value.partition("=")[0].strip())
            else not repository
        )
    ]
    return due or None


def _has_content_settings(path: Path) -> bool:
    from canvod.store_metadata import open_repository, store_exists

    if not store_exists(path):
        return False
    return bool((open_repository(path).get_metadata() or {}).get("content_settings"))


def _migration_steps(kind: str, path: Path) -> list[str]:
    """What the migration does to the store now at ``path``."""
    from canvod.store.migrate_layout import NOTHING, plan_layout_migration
    from canvod.store_metadata import open_repository, store_exists
    from canvod.store_metadata.migration import clock_to_drop

    if not store_exists(path):
        return []
    steps = []
    repository = open_repository(path).get_metadata()
    if not repository:
        steps.append(
            "move its metadata to repository metadata: a store id from the "
            "site and folder name, a UUID, the content settings from its "
            "first commit (migrate-metadata)"
        )
    elif not repository.get("content_settings"):
        steps.append("write its content settings from its first commit")
    if kind == "gnss":
        groups = clock_to_drop(path)
        if groups:
            steps.append(
                f"delete the variable 'clock' of the groups {', '.join(groups)}; "
                "record fetch_clock: false"
            )
        elif groups is not None:
            steps.append("record fetch_clock: false (no group holds 'clock')")
    if not repository:
        steps.append("write groups not made of day blocks again (checked then)")
    else:
        try:
            plans = plan_layout_migration(path)
        except Exception as exc:  # shown, and raised again when the step runs
            steps.append(f"move the groups to day blocks: {exc}")
        else:
            rewrite = [p.group for p in plans if p.action != NOTHING]
            if rewrite:
                steps.append(
                    f"write the groups {', '.join(rewrite)} again as day blocks"
                )
    return steps


def _move_store_folder(old: Path, new: Path) -> None:
    """Rename a store's folder while no run commits to it."""
    from canvod.store_metadata import commit_lock

    with commit_lock(old):
        pass  # waits for a commit in progress
    old.rename(new)


def _migrate_store(
    site: str,
    kind: str,
    naming_authority: str | None,
    set_values: list[str] | None,
    config: object,
) -> None:
    from canvod.store_metadata.migration import drop_clock

    _migrate_metadata(
        site,
        kind,
        naming_authority,
        set_values,
        yes=True,
        command=f"canvodpy store migrate {site}",
        set_option=f"--{kind}-set",
    )
    if kind == "gnss":
        path, _ = _store_path(site, kind)
        if drop_clock(path, who=_who(), config=config):
            console.print(
                "[green]✓ Removed the clock variable; fetch_clock: false[/green]"
            )
    migrate_layout_command(site, store=kind, yes=True)


def _follow_gnss_hash(site: str, stores: dict[str, Path], config: object) -> None:
    from canvod.store_metadata import store_exists
    from canvod.store_metadata.migration import follow_gnss_content_hash

    if not store_exists(stores["gnss"]):
        return
    try:
        followed = follow_gnss_content_hash(
            stores["vod"], stores["gnss"], who=_who(), config=config
        )
    except ValueError as exc:
        console.print(f"[red]❌ {exc}[/red]")
        raise typer.Exit(1) from None
    if followed:
        console.print(
            "[green]✓ The VOD store records the GNSS store's new "
            "content-settings hash[/green]"
        )
