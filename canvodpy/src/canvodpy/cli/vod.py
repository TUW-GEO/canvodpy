"""``canvodpy vod`` — compute VOD in bulk from an existing RINEX store.

Thin wrapper around ``VodComputer.compute_bulk()``: reads canopy/reference
data directly from the site's RINEX Icechunk store (rather than inline
during a pipeline run) and writes the result under
``{calculator}/{analysis_name}`` in the VOD store. For backfill/reprocessing
outside of ``canvodpy run`` — see dev/todo_later.md §29.
"""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from canvodpy.cli.options import CONFIG_DIR_OPTION

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
        typer.Option("--start", help="Start date in YYYYDOY format (e.g. 2025001)."),
    ] = None,
    end: Annotated[
        str | None,
        typer.Option("--end", help="End date in YYYYDOY format (e.g. 2025007)."),
    ] = None,
    calculator: Annotated[
        str,
        typer.Option("--calculator", help="VOD calculator to use."),
    ] = "tau_omega",
    config_dir: Annotated[Path | None, CONFIG_DIR_OPTION] = None,
) -> None:
    """Compute VOD in bulk from an existing RINEX store and write the result."""
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
        str,
        typer.Option("--calculator", help="VOD calculator to use."),
    ] = "tau_omega",
    execute: Annotated[
        bool,
        typer.Option(
            "--execute",
            help="Backfill the gaps found. Default is a dry-run report only.",
        ),
    ] = False,
    config_dir: Annotated[Path | None, CONFIG_DIR_OPTION] = None,
) -> None:
    """Find (and optionally backfill) RINEX-ingested-but-VOD-missing dates.

    ``canvodpy run`` only resumes from the RINEX store's latest date, so a
    date that got RINEX-ingested but never got its VOD computed (e.g. a
    run that crashed on the VOD-store write after RINEX ingestion already
    succeeded — dev/todo_later.md §43) is silently never revisited. This
    finds that gap and, with ``--execute``, backfills it via
    ``VodComputer.compute_bulk()`` — the same mechanism ``canvodpy vod``
    uses. Dry-run by default: never writes anything unless ``--execute``
    is passed.
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
        console.print("Dry run — pass --execute to backfill.")
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
