"""``canvodpy vod`` and ``canvodpy vod-reconcile``: VOD from an existing GNSS store.

Both commands call ``VodComputer.compute_bulk()``. It reads the canopy and
reference observations from the GNSS store of the site, not during a
pipeline run, and writes the result to ``{calculator}/{analysis_name}`` in
the VOD store. Use them to compute VOD again, or for dates that
``canvodpy run`` left without VOD.
"""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from canvodpy.cli.options import CONFIG_DIR_OPTION, VodCalculatorChoice

console = Console()


def _to_datetime(yyyydoy: str, *, end_of_day: bool) -> datetime.datetime:
    from canvod.utils.tools import YYYYDOY

    date_obj = YYYYDOY.from_str(yyyydoy).date
    assert date_obj is not None
    return datetime.datetime.combine(
        date_obj, datetime.time.max if end_of_day else datetime.time.min
    )


def vod(
    site: Annotated[
        str,
        typer.Option(
            "--site",
            help="Site name, as defined under sites: in canvod-settings.yaml",
        ),
    ],
    analysis: Annotated[
        str,
        typer.Option(
            "--analysis", help="VOD analysis name, as defined in site.vod_analyses"
        ),
    ],
    start: Annotated[
        str | None,
        typer.Option(
            "--start", help="Start date in YYYYDOY format, for example 2025001."
        ),
    ] = None,
    end: Annotated[
        str | None,
        typer.Option("--end", help="End date in YYYYDOY format, for example 2025007."),
    ] = None,
    calculator: Annotated[
        VodCalculatorChoice,  # ty: ignore[invalid-type-form]
        typer.Option("--calculator", help="VOD calculator to use."),
    ] = VodCalculatorChoice["tau_omega"],
    config_dir: Annotated[Path | None, CONFIG_DIR_OPTION] = None,
) -> None:
    """Compute VOD in bulk from an existing GNSS store and write the result."""
    from canvodpy.api import Site
    from canvodpy.vod_computer import VodComputer

    start_dt = _to_datetime(start, end_of_day=False) if start else None
    end_dt = _to_datetime(end, end_of_day=True) if end else None

    site_obj = Site(site)
    if analysis not in site_obj.vod_analyses:
        console.print(f"[red]❌ Unknown VOD analysis:[/red] {analysis}")
        console.print(f"  Available: {list(site_obj.vod_analyses)}")
        raise typer.Exit(1)

    vod_computer = VodComputer(site_obj, calculator=calculator)

    console.print(
        f"Computing VOD for [bold]{site}[/bold]/{analysis} (calculator={calculator})..."
    )
    vod_ds = vod_computer.compute_bulk(analysis, start=start_dt, end=end_dt)

    n_valid = int((~vod_ds["VOD"].isnull()).sum()) if "VOD" in vod_ds else 0
    n_total = vod_ds["VOD"].size if "VOD" in vod_ds else 0
    pct = 100 * n_valid / n_total if n_total else 0
    console.print(
        f"[green]✓[/green] {n_valid}/{n_total} valid VOD values ({pct:.0f}%) "
        f"written to '{calculator}/{analysis}'"
    )


def vod_reconcile(
    site: Annotated[
        str,
        typer.Option(
            "--site",
            help="Site name, as defined under sites: in canvod-settings.yaml",
        ),
    ],
    analysis: Annotated[
        str,
        typer.Option(
            "--analysis", help="VOD analysis name, as defined in site.vod_analyses"
        ),
    ],
    calculator: Annotated[
        VodCalculatorChoice,  # ty: ignore[invalid-type-form]
        typer.Option("--calculator", help="VOD calculator to use."),
    ] = VodCalculatorChoice["tau_omega"],
    execute: Annotated[
        bool,
        typer.Option(
            "--execute",
            help="Compute the VOD of the dates found. Without this flag, the command only reports them.",
        ),
    ] = False,
    config_dir: Annotated[Path | None, CONFIG_DIR_OPTION] = None,
) -> None:
    """List the dates that have observations but no VOD, and compute it with --execute.

    canvodpy run continues after the last date in the GNSS store. A date
    whose observations reached the GNSS store but whose VOD was never
    written, for example because a run stopped while it wrote the VOD
    store, is therefore never processed again. This command lists those
    dates. With --execute, it computes their VOD the same way as
    canvodpy vod. Without --execute, it only reports and writes nothing.
    """
    from canvodpy.api import Site
    from canvodpy.orchestrator.vod_reconcile import (
        _group_into_ranges,
        find_vod_backfill_gaps,
    )
    from canvodpy.vod_computer import VodComputer

    site_obj = Site(site)
    if analysis not in site_obj.vod_analyses:
        console.print(f"[red]❌ Unknown VOD analysis:[/red] {analysis}")
        console.print(f"  Available: {list(site_obj.vod_analyses)}")
        raise typer.Exit(1)

    gaps = find_vod_backfill_gaps(site_obj, analysis, calculator)
    if not gaps:
        console.print(
            f"[green]✓[/green] No VOD gaps for [bold]{site}[/bold]/{analysis} "
            f"(calculator={calculator})."
        )
        return

    ranges = _group_into_ranges(gaps)
    range_str = ", ".join(s if s == e else f"{s}-{e}" for s, e in ranges)
    console.print(
        f"[yellow]{len(gaps)} date(s)[/yellow] have RINEX data but no VOD for "
        f"[bold]{site}[/bold]/{analysis} (calculator={calculator}): {range_str}"
    )

    if not execute:
        console.print("Dry run: pass --execute to backfill.")
        return

    vod_computer = VodComputer(site_obj, calculator=calculator)
    for start_str, end_str in ranges:
        start_dt = _to_datetime(start_str, end_of_day=False)
        end_dt = _to_datetime(end_str, end_of_day=True)
        console.print(f"Backfilling {start_str}-{end_str}...")
        vod_computer.compute_bulk(analysis, start=start_dt, end=end_dt)

    console.print(f"[green]✓[/green] Backfill complete for {len(ranges)} range(s).")


if __name__ == "__main__":
    typer.run(vod)
