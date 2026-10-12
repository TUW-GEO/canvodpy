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
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table
from rich.tree import Tree

from canvodpy.cli.options import CONFIG_DIR_OPTION

store_app = typer.Typer(
    name="store",
    help="Inspect the Icechunk stores of the sites and maintain them.",
    no_args_is_help=True,
)

console = Console()

_STORE_KINDS = ("gnss", "vod")


def _store_path(site_name: str, store_kind: str) -> tuple[Path, str]:
    """Resolve a site + store kind (gnss/vod) to its path and store type.

    Exits cleanly with an actionable message if the site is unknown or the
    store hasn't been created yet; matches the rest of the CLI's error
    style (config.py, doctor.py), not a raw traceback.
    """
    from canvod.config import load_config

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

    if not path.exists():
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
                if path.exists()
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
        f"  Compression: {stats['compression_algorithm']} (level {stats['compression_level']})\n"
    )

    if group is not None:
        _print_group_content(icestore, group, branch)
    else:
        icestore.print_tree()
        console.print(
            "\n[dim]Use --group <name> to see a group's dataset and metadata table.[/dim]"
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
        str,
        typer.Argument(
            help="Site name, as defined under sites: in canvod-settings.yaml"
        ),
    ],
    store: Annotated[
        str, typer.Option("--store", metavar="gnss|vod", help="Store to open.")
    ] = "gnss",
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
    config_dir: Annotated[Path | None, CONFIG_DIR_OPTION] = None,
) -> None:
    """Show the commit history as a graph, or the store operations with --ops."""
    if store not in _STORE_KINDS:
        console.print(
            f"[red]❌ --store must be one of: {', '.join(_STORE_KINDS)}[/red]"
        )
        raise typer.Exit(1)

    icestore = _open_store(site, store)

    if ops:
        icestore.print_ops_log(limit=limit)
    else:
        print(icestore.plot_commit_graph(branch=branch))


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
    """
    if store not in _STORE_KINDS:
        console.print(
            f"[red]❌ --store must be one of: {', '.join(_STORE_KINDS)}[/red]"
        )
        raise typer.Exit(1)

    from datetime import UTC, datetime, timedelta

    icestore = _open_store(site, store)
    cutoff = datetime.now(UTC) - timedelta(days=expire_days)

    if not execute:
        console.print(
            f"\n[bold]{site}[/bold]: {store} store, [yellow]DRY RUN[/yellow] "
            f"(cutoff: {cutoff.isoformat()})\n"
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
        console.print(
            "\n[dim]Nothing was deleted or expired. Re-run with --execute "
            "to actually run maintenance (after confirming).[/dim]"
        )
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
            if not path.exists():
                console.print(
                    f"[dim]{site_name} ({kind}): no store yet, skipping.[/dim]"
                )
                continue

            from canvod.store import MyIcechunkStore

            icestore = MyIcechunkStore(
                path, store_type="gnss_store" if kind == "gnss" else "vod_store"
            )
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

            if mcfg.dry_run_until_confirmed:
                console.print(
                    "[yellow]DRY RUN[/yellow] (maintenance.dry_run_until_confirmed=true)"
                )
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
                "at.ac.tuwien. Default: the store's own, if it is a reverse "
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
            help="A field the store lacks, for example identity.description=Beech forest site, Rosalia. Repeat for more fields.",
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
    The migration record keeps who migrated the store, the initials set in
    processing.metadata.initials.
    """
    from canvod.store_metadata import migrate_metadata, read_metadata
    from canvod.store_metadata.identity import check_naming_authority, store_id

    path, _ = _store_path(site, store)
    try:
        old = read_metadata(path)
    except KeyError:
        console.print(
            f"[red]❌ The {store} store of '{site}' has no store metadata.[/red]"
        )
        raise typer.Exit(1) from None
    if not old.written_before_migration:
        console.print(
            f"[green]✓ The {store} store of '{site}' is already migrated.[/green]"
        )
        return

    who = _who()
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
    new_id = store_id(old.spatial.site.name, old.identity.store_type)
    console.print(f"\n[bold]{site}[/bold]: {store} store ({path})")
    console.print(f"  Store id:          {old.identity.id} -> {new_id}")
    console.print(f"  Who:               {who}")
    console.print(
        "  Naming authority:  "
        f"{naming_authority or old.identity.naming_authority or '(none)'}"
        f" (from {source})"
    )
    values = _amend_changes(site, old.identity.store_type, set_values or [], [], [])
    for field, value in values.items():
        console.print(f"  Set {field}: {value!r}")
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
        )
    except ValueError as exc:
        console.print(f"[red]❌ {exc}[/red]")
        raise typer.Exit(1) from None
    console.print(f"[green]✓ Migrated[/green] (snapshot {snapshot_id[:12]})")


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
) -> dict[str, object]:
    """The changes of an amendment, with receiver and VOD analysis entries
    taken from the settings."""
    import yaml

    from canvod.config import load_config
    from canvod.store_metadata.collectors import collect_receiver
    from canvod.store_metadata.schema import RepositoryReceiver

    changes: dict[str, object] = {}
    for item in set_values:
        field, sep, value = item.partition("=")
        if not sep:
            console.print(f"[red]❌ --set takes field.path=value, not {item!r}[/red]")
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
        receiver = collect_receiver(site_cfg.receivers[name])
        if store_type == "vod_store":
            # A VOD store reads the hardware from the GNSS store's entries.
            receiver = receiver.model_copy(
                update={"receiver_hardware": None, "antenna": None}
            )
        changes[f"instruments.receivers.{name}"] = receiver.model_dump(
            mode="json", include=set(RepositoryReceiver.model_fields)
        )
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
    from_file: Annotated[
        Path | None,
        typer.Option(
            "--from",
            metavar="<path>",
            help=(
                "YAML file with the keys reason, set (field paths and values), "
                "and the lists add_receivers and add_vod_analyses."
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

    path, store_type = _store_path(site, store)
    set_values = list(set_values or [])
    receivers = list(add_receiver or [])
    vod_analyses = list(add_vod_analysis or [])
    if from_file is not None:
        spec = yaml.safe_load(from_file.read_text()) or {}
        set_values += [
            f"{k}={yaml.safe_dump(v).strip()}"
            for k, v in (spec.get("set") or {}).items()
        ]
        receivers += list(spec.get("add_receivers") or [])
        vod_analyses += list(spec.get("add_vod_analyses") or [])
        reason = reason or spec.get("reason")
    if not reason:
        console.print(
            "[red]❌ An amendment needs --reason (or reason: in the --from file).[/red]"
        )
        raise typer.Exit(1)
    who = _who()

    changes = _amend_changes(site, store_type, set_values, receivers, vod_analyses)
    if not changes:
        console.print(
            "[red]❌ Nothing to change: use --set, --add-receiver, --add-vod-analysis or --from.[/red]"
        )
        raise typer.Exit(1)

    try:
        for field in changes:
            check_amendable(field)
    except ValueError as exc:
        console.print(f"[red]❌ {exc}[/red]")
        raise typer.Exit(1) from None

    current = read_repository_metadata(path)
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

    try:
        snapshot_id = amend_metadata(
            path, changes, reason=reason, who=who, config=load_config()
        )
    except ValueError as exc:
        console.print(f"[red]❌ {exc}[/red]")
        raise typer.Exit(1) from None
    console.print(f"[green]✓ Amended[/green] (snapshot {snapshot_id[:12]})")
