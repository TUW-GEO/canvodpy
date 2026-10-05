"""canvodpy store — inspect Icechunk stores from the terminal.

Thin CLI wrappers around canvod-store's existing MyIcechunkStore methods
(print_tree, print_history, plot_commit_graph, print_ops_log,
get_store_stats) — which themselves delegate to icechunk v2's native
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
    help="Inspect Icechunk stores: list sites, show tree/stats, view commit history.",
    no_args_is_help=True,
)

console = Console()

_STORE_KINDS = ("gnss", "vod")


def _open_store(site_name: str, store_kind: str):
    """Resolve a site + store kind (gnss/vod) to an opened MyIcechunkStore.

    Exits cleanly with an actionable message if the site is unknown or the
    store hasn't been created yet — matches the rest of the CLI's error
    style (config.py, doctor.py), not a raw traceback.
    """
    from canvod.config import load_config
    from canvod.store import MyIcechunkStore

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
        str, typer.Option("--store", help="Which store: gnss or vod")
    ] = "gnss",
    branch: Annotated[str, typer.Option("--branch", help="Branch to inspect")] = "main",
    group: Annotated[
        str | None,
        typer.Option(
            "--group",
            help="Drill into one group's full content (dataset + metadata table)",
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

    console.print(f"\n[bold]{site}[/bold] — {store} store")
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
    plain-text xarray Dataset repr + metadata table, in a rich.Tree —
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
        pass  # not every group has a metadata table — fine, just skip it

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
        str, typer.Option("--store", help="Which store: gnss or vod")
    ] = "gnss",
    branch: Annotated[
        str | None,
        typer.Option(
            "--branch", help="Restrict to one branch's linear history (default: all)"
        ),
    ] = None,
    ops: Annotated[
        bool,
        typer.Option(
            "--ops", help="Show the operations audit trail instead of the commit graph"
        ),
    ] = False,
    limit: Annotated[int, typer.Option("--limit", help="Max entries for --ops")] = 50,
    config_dir: Annotated[Path | None, CONFIG_DIR_OPTION] = None,
) -> None:
    """Show commit history as a graph (or the ops audit trail with --ops)."""
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
        str, typer.Option("--store", help="Which store: gnss or vod")
    ] = "gnss",
    expire_days: Annotated[
        int,
        typer.Option(
            "--expire-days",
            help="Snapshot retention window in days (weeks-to-months, not hours)",
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
                "Actually run expiration/GC. Without this flag, only a "
                "dry-run garbage-collect report is shown -- nothing is "
                "deleted or expired."
            ),
        ),
    ] = False,
    config_dir: Annotated[Path | None, CONFIG_DIR_OPTION] = None,
) -> None:
    """Run store maintenance (expiration + garbage collection).

    Defaults to a **dry run**: reports what garbage collection would delete
    and how many ancestry entries are older than the cutoff, without
    touching anything. Pass --execute to actually expire snapshots and
    (optionally) run garbage collection for real.

    This is an administrative operation -- never safe to run casually
    alongside an active pipeline run on the same store. See
    dev/perf_degradation_findings_2026_07_15.md for the full rationale
    (expiration/GC concurrency caveats, why the default cadence is weeks-
    to-months, and the retention-scheme design this command supports).
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
            f"\n[bold]{site}[/bold] — {store} store — [yellow]DRY RUN[/yellow] "
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
        typer.Option("--all-sites", help="Run for every site in canvod-settings.yaml"),
    ] = False,
    store: Annotated[
        str,
        typer.Option("--store", help="Which store(s): gnss, vod, or both"),
    ] = "both",
    config_dir: Annotated[Path | None, CONFIG_DIR_OPTION] = None,
) -> None:
    """Non-interactive maintenance: runs only what's actually due, or nothing.

    Cron/systemd-timer-safe counterpart to ``maintain`` -- never prompts,
    always exits 0 on a normal "nothing to do" outcome. `maintain` itself
    can't be scheduled unattended: its --execute path requires an
    interactive confirmation. This command instead reads
    ``processing.storage.maintenance`` from canvod-settings.yaml and does
    nothing unless all of the following hold:

    \b
    - maintenance.enabled or maintenance.manifests_enabled is true (both
      default false -- inert until a deployment has validated `maintain
      --store ...` (dry run) against its real store first, see
      dev/perf_degradation_findings_2026_07_15.md)
    - no `canvodpy run` is currently active on this host

    Expiration/GC are gated on maintenance.enabled specifically, and are
    due when the store's own ops log shows expiration/GC genuinely due
    per maintenance.expire_interval_days / .gc_delay_days. Manifest
    compaction (rewrite_manifests()) is gated independently by
    maintenance.manifests_enabled -- it's a different risk profile (an
    ordinary commit, no history rewrite or physical deletion) and has no
    ops-log entry of its own to check, so due-ness is measured directly
    from the store's current on-disk manifest count vs
    maintenance.manifest_count_threshold instead of a time interval. A
    deployment can enable either independently of the other.

    While maintenance.dry_run_until_confirmed is true (the default), a due
    store is only ever reported, never actually touched -- flip it to
    false per-deployment once satisfied with the reports.
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
