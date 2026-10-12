"""canvodpy doctor: environment and configuration diagnostics.

Reports canvodpy's resolved version, Python/uv environment, where config
was resolved from and why (dev-checkout convenience vs. XDG default, see
canvod.config.loader.get_default_config_dir), whether bundled templates
are reachable, and whether the current canvod-settings.yaml (if any)
validates cleanly. Read-only — makes no changes to any file.

Run this first when something isn't working: it answers "what does my
install actually look like" in one command instead of several separate
manual checks.
"""

from __future__ import annotations

import importlib.metadata as metadata
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Annotated

from rich.console import Console

from canvodpy.cli.options import CONFIG_DIR_OPTION

console = Console()


def _uv_version() -> str | None:
    """Return `uv --version` output, or None if uv isn't on PATH."""
    uv = shutil.which("uv")
    if uv is None:
        return None
    try:
        result = subprocess.run(
            [uv, "--version"], capture_output=True, text=True, timeout=5
        )
        return result.stdout.strip() or None
    except Exception:
        return None


def _package_version(name: str) -> str:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return "unknown (not installed as a package)"


def _is_checkout_config(config_dir: Path) -> bool:
    from canvod.config.loader import find_monorepo_root

    try:
        return config_dir == find_monorepo_root() / "config"
    except RuntimeError:
        return False


def doctor(
    config_dir: Annotated[Path | None, CONFIG_DIR_OPTION] = None,
) -> None:
    """Report canvodpy's version, its environment, and its configuration directory."""
    from canvod.config.loader import (
        ConfigValidationError,
        format_validation_error,
        get_default_config_dir,
        get_template_dir,
        load_config,
    )

    console.print("\n[bold]canvodpy doctor[/bold]\n")

    # --- Versions -----------------------------------------------------------
    console.print(f"  canvodpy:      {_package_version('canvodpy')}")
    console.print(f"  canvod-config: {_package_version('canvod-config')}")
    console.print(f"  Python:        {sys.version.split()[0]} ({sys.executable})")
    uv_version = _uv_version()
    console.print(
        f"  uv:            {uv_version or '[yellow]not found on PATH[/yellow]'}"
    )

    # --- Config resolution ----------------------------------------------------
    console.print()
    config_dir = get_default_config_dir()
    if os.environ.get("CANVOD_CONFIG_DIR"):
        source = "--config-dir option or CANVOD_CONFIG_DIR environment variable"
    elif _is_checkout_config(config_dir):
        source = f"dev checkout at {config_dir.parent}"
    else:
        source = "XDG default (no monorepo checkout found)"

    console.print(f"  Config resolved to: {config_dir}")
    console.print(f"    (source: {source})")

    # --- Templates ------------------------------------------------------------
    template_dir = get_template_dir()
    template_ok = (
        template_dir.exists()
        and (template_dir / "canvod-settings.yaml.example").exists()
    )
    if template_ok:
        console.print(f"  Templates reachable: [green]✓[/green] {template_dir}")
    else:
        console.print(
            f"  Templates reachable: [red]❌ not found at {template_dir}[/red]"
        )
        console.print(
            "    This looks like a broken canvod-config install; reinstall it."
        )

    # --- canvod-settings.yaml ---------------------------------------------------
    settings_file = config_dir / "canvod-settings.yaml"
    if not settings_file.exists():
        console.print(
            f"  canvod-settings.yaml: [yellow]⊘ not found[/yellow] ({settings_file})"
        )
        console.print("    Run: canvodpy config init --interactive")
    else:
        try:
            load_config(config_dir)
        except ConfigValidationError as e:
            console.print(
                f"  canvod-settings.yaml: [red]❌ invalid[/red] ({settings_file})\n"
            )
            console.print(format_validation_error(e))
        except Exception as e:
            console.print(
                f"  canvod-settings.yaml: [red]❌ error loading[/red] ({settings_file})\n"
            )
            console.print(f"    {e}")
        else:
            console.print(
                f"  canvod-settings.yaml: [green]✓ valid[/green] ({settings_file})"
            )

    console.print()
