"""canvodpy stac: the STAC catalog of the stores (ADR 0015).

Thin wrappers around canvod-store-metadata's catalog functions. The
catalog is written beside the stores, at the data root
(``storage.stores_root_dir`` unless ``--root`` names another one).
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.markup import escape

from canvodpy.cli.options import CONFIG_DIR_OPTION

stac_app = typer.Typer(
    name="stac",
    help="Write the STAC catalog of every store under the data root.",
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
        first, *rest = str(error).splitlines()
        console.print(f"[red]❌ {escape(first)}[/red]", soft_wrap=True)
        for line in rest:
            console.print(line, markup=False, highlight=False, soft_wrap=True)
        raise typer.Exit(1) from None
    console.print(f"[green]✓ Catalog written:[/green] {catalog}")
