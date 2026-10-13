"""canvodpy stac: the STAC catalog of the stores (ADR 0015).

Thin wrappers around canvod-store-metadata's catalog functions. The
catalog is written beside the stores, at the data root
(``storage.stores_root_dir`` unless ``--root`` names another one).
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, NoReturn

import typer
from rich.console import Console
from rich.markup import escape

from canvodpy.cli.options import CONFIG_DIR_OPTION

stac_app = typer.Typer(
    name="stac",
    help="Write the STAC catalog of every store under the data root, or a release.",
    no_args_is_help=True,
)

console = Console()

ROOT_OPTION = typer.Option(
    "--root",
    help="Data root to catalog. Default: storage.stores_root_dir in the settings.",
    show_default=False,
)


def _data_root(root: Path | None) -> Path:
    if root is not None:
        return root
    from canvod.config import load_config

    return load_config().processing.storage.stores_root_dir


@stac_app.command("write")
def write(
    root: Annotated[Path | None, ROOT_OPTION] = None,
    config_dir: Annotated[Path | None, CONFIG_DIR_OPTION] = None,
) -> None:
    """Write the latest catalog of every store under the data root.

    If a store cannot be described, nothing is written: the command lists
    every such store with its reason and exits with code 1.
    """
    from canvod.store_metadata import write_catalog

    try:
        catalog = write_catalog(_data_root(root))
    except ValueError as error:
        _refused(error)
    console.print(f"[green]✓ Catalog written:[/green] {catalog}")


@stac_app.command("release")
def release(
    tag: Annotated[
        str, typer.Argument(help="Release tag, for example v2026.1; no '/'.")
    ],
    root: Annotated[Path | None, ROOT_OPTION] = None,
    config_dir: Annotated[Path | None, CONFIG_DIR_OPTION] = None,
) -> None:
    """Publish a release: tag every store under the data root and write its catalog.

    TAG becomes an Icechunk tag on the current main of every store, and
    releases/TAG/ gets the catalog of that tag, each asset pinned to the
    tag and its snapshot. A release catalog is never changed afterwards.
    Nothing is tagged if a store cannot be described or already has the
    tag; if every store has the tag but the catalog is missing, only the
    catalog is written.
    """
    from canvod.store_metadata import create_release

    try:
        catalog = create_release(_data_root(root), tag)
    except ValueError as error:
        _refused(error)
    console.print(f"[green]✓ Release {escape(tag)} written:[/green] {catalog}")


def _refused(error: ValueError) -> NoReturn:
    first, *rest = str(error).splitlines()
    console.print(f"[red]❌ {escape(first)}[/red]", soft_wrap=True)
    for line in rest:
        console.print(line, markup=False, highlight=False, soft_wrap=True)
    raise typer.Exit(1) from None
