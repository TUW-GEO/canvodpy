#!/usr/bin/env python3
"""Danger Zone — destructive cleanup operations with TUI confirmation.

Usage:
    uv run python scripts/danger_zone.py <command> [options]

Commands:
    delete-logs             Delete all log files
    delete-aux              Delete downloaded auxiliary data and Zarr caches
    delete-store            Delete an Icechunk store (rinex or vod)
    delete-all-stores       Delete ALL Icechunk stores for a site
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table
from rich.text import Text

console = Console()

SKULL = "[bold red]☠[/]"
WARNING = "[bold yellow]⚠[/]"


def _banner(title: str, paths: list[tuple[str, Path]], extra: str = "") -> None:
    """Display a danger zone banner with affected paths."""
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="dim")
    table.add_column()
    total_size = 0
    for label, path in paths:
        if path.exists():
            size = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
            total_size += size
            size_str = _human_size(size)
            table.add_row(label, f"[green]{path}[/]  ({size_str})")
        else:
            table.add_row(label, f"[dim]{path}  (does not exist)[/dim]")

    body = Text()
    content = table

    panel = Panel(
        content,
        title=f"{SKULL}  {title}  {SKULL}",
        subtitle=f"Total: {_human_size(total_size)}" if total_size else None,
        border_style="bold red",
        padding=(1, 2),
    )
    console.print()
    console.print(panel)
    if extra:
        console.print(f"  {extra}")
    console.print()


def _human_size(nbytes: int) -> str:
    size = float(nbytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(size) < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PB"


def _confirm(action: str) -> bool:
    """Require the user to type the action name to confirm."""
    console.print(
        f"  Type [bold red]{action}[/] to confirm, or anything else to cancel:"
    )
    answer = Prompt.ask("  ", default="")
    if answer.strip() == action:
        return True
    console.print("  [green]Cancelled.[/]")
    return False


def _delete_paths(paths: list[tuple[str, Path]]) -> None:
    """Delete directories/files and report results."""
    for label, path in paths:
        if not path.exists():
            console.print(f"  [dim]Skipped (not found): {path}[/]")
            continue
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        console.print(f"  [red]Deleted:[/] {path}")
    console.print()


def _load_config():
    from canvod.config import load_config

    return load_config()


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_delete_logs(_args: argparse.Namespace) -> None:
    config = _load_config()
    log_cfg = config.processing.logging
    log_dir = log_cfg.get_log_dir()

    paths = [("Log directory", log_dir)]
    _banner(
        "DELETE ALL LOGS", paths, f"{WARNING}  This removes all canvodpy log files."
    )

    if not log_dir.exists():
        console.print("  [dim]Nothing to delete — log directory does not exist.[/]")
        return

    if _confirm("DELETE"):
        _delete_paths(paths)
        console.print("  [green]Logs deleted.[/]")


def cmd_delete_aux(_args: argparse.Namespace) -> None:
    config = _load_config()
    aux_dir = config.processing.storage.get_aux_data_dir()

    # Find Zarr caches and raw SP3/CLK files
    zarr_dirs = sorted(aux_dir.glob("aux_*.zarr")) if aux_dir.exists() else []
    sp3_dirs = sorted(aux_dir.glob("*SP3*")) if aux_dir.exists() else []
    clk_dirs = sorted(aux_dir.glob("*CLK*")) if aux_dir.exists() else []
    all_aux = zarr_dirs + sp3_dirs + clk_dirs

    paths = [("Aux data directory", aux_dir)]
    detail = f"  Contains {len(zarr_dirs)} Zarr cache(s), {len(sp3_dirs)} SP3, {len(clk_dirs)} CLK file(s)"

    _banner(
        "DELETE AUXILIARY DATA",
        paths,
        f"{WARNING}  SP3/CLK files will need to be re-downloaded.\n{detail}",
    )

    if not aux_dir.exists() or not all_aux:
        console.print("  [dim]Nothing to delete.[/]")
        return

    if _confirm("DELETE"):
        for p in all_aux:
            if p.is_dir():
                shutil.rmtree(p)
            else:
                p.unlink()
            console.print(f"  [red]Deleted:[/] {p.name}")
        console.print(f"\n  [green]Deleted {len(all_aux)} item(s).[/]")


def cmd_delete_store(args: argparse.Namespace) -> None:
    config = _load_config()
    storage = config.processing.storage
    site = args.site
    store_type = args.store

    if store_type == "rinex":
        store_path = storage.get_gnss_store_path(site)
    elif store_type == "vod":
        store_path = storage.get_vod_store_path(site)
    else:
        console.print(
            f"  [red]Unknown store type: {store_type}. Use 'rinex' or 'vod'.[/]"
        )
        sys.exit(1)

    paths = [(f"{store_type.upper()} store ({site})", store_path)]
    _banner(
        f"DELETE {store_type.upper()} STORE",
        paths,
        f"{WARNING}  This permanently destroys the {store_type} Icechunk store for site '{site}'.\n"
        f"  All processed data will be lost. Re-processing from raw files will be required.",
    )

    if not store_path.exists():
        console.print("  [dim]Nothing to delete — store does not exist.[/]")
        return

    if _confirm("DELETE"):
        _delete_paths(paths)
        console.print(f"  [green]{store_type.upper()} store for '{site}' deleted.[/]")


def cmd_delete_all_stores(args: argparse.Namespace) -> None:
    config = _load_config()
    storage = config.processing.storage
    site = args.site

    rinex_path = storage.get_gnss_store_path(site)
    vod_path = storage.get_vod_store_path(site)

    paths = [
        (f"GNSS store ({site})", rinex_path),
        (f"VOD store ({site})", vod_path),
    ]
    _banner(
        f"DELETE ALL STORES FOR '{site.upper()}'",
        paths,
        f"{WARNING}  This permanently destroys ALL Icechunk stores for site '{site}'.\n"
        f"  All processed RINEX data and VOD products will be lost.",
    )

    existing = [(label, p) for label, p in paths if p.exists()]
    if not existing:
        console.print("  [dim]Nothing to delete — no stores exist.[/]")
        return

    if _confirm("DELETE"):
        _delete_paths(existing)
        console.print(f"  [green]All stores for '{site}' deleted.[/]")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Danger Zone — destructive cleanup operations",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("delete-logs", help="Delete all log files")
    sub.add_parser("delete-aux", help="Delete auxiliary data (SP3, CLK, Zarr caches)")

    p_store = sub.add_parser("delete-store", help="Delete a specific Icechunk store")
    p_store.add_argument("site", help="Site name (e.g. examplesite)")
    p_store.add_argument("store", choices=["rinex", "vod"], help="Store type")

    p_all = sub.add_parser("delete-all-stores", help="Delete ALL stores for a site")
    p_all.add_argument("site", help="Site name (e.g. examplesite)")

    args = parser.parse_args()

    dispatch = {
        "delete-logs": cmd_delete_logs,
        "delete-aux": cmd_delete_aux,
        "delete-store": cmd_delete_store,
        "delete-all-stores": cmd_delete_all_stores,
    }
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
