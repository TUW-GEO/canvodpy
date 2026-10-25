"""``canvodpy vod`` and ``canvodpy vod-reconcile``: VOD from an existing GNSS store.

Both commands call ``VodComputer.compute_days()``, the VOD phase run alone
(ADR 0021): one task per day in the worker pool reads the day's canopy and
reference observations from the GNSS store of the site and writes its VOD to
``{calculator}/{analysis_name}`` in the VOD store, one commit per unit of
days. Use them to compute VOD again, or for days that ``canvodpy run`` left
without VOD.
"""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any

import typer

from canvodpy.cli.options import CONFIG_DIR_OPTION, VodCalculatorChoice
from canvodpy.cli.theme import console

if TYPE_CHECKING:
    from canvodpy.orchestrator.vod_phase import VodUnitReport


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
            "--start",
            help=(
                "First day in YYYYDOY format, for example 2025001. Default: the "
                "first day of the GNSS store."
            ),
        ),
    ] = None,
    end: Annotated[
        str | None,
        typer.Option(
            "--end",
            help=(
                "Last day in YYYYDOY format, for example 2025007. Default: the "
                "last day of the GNSS store."
            ),
        ),
    ] = None,
    calculator: Annotated[
        VodCalculatorChoice,  # ty: ignore[invalid-type-form]
        typer.Option("--calculator", help="VOD calculator to use."),
    ] = VodCalculatorChoice["tau_omega"],
    config_dir: Annotated[Path | None, CONFIG_DIR_OPTION] = None,
) -> None:
    """Compute the VOD of a range of days from an existing GNSS store and write it.

    Without --start and --end, every day of the GNSS store. A day whose VOD
    the store holds from the same GNSS files is not computed again; a day
    without data in the canopy or the reference group is skipped and
    listed.
    """
    from canvodpy.api import Site
    from canvodpy.vod_computer import VodComputer

    start_dt = _to_datetime(start, end_of_day=False) if start else None
    end_dt = _to_datetime(end, end_of_day=True) if end else None

    site_obj = Site(site)
    if analysis not in site_obj.vod_analyses:
        console.print(
            f"[canvod.error]❌ Unknown VOD analysis:[/canvod.error] {analysis}"
        )
        console.print(f"  Available: {list(site_obj.vod_analyses)}")
        raise typer.Exit(1)

    vod_computer = VodComputer(site_obj, calculator=calculator)

    days = vod_computer.gnss_days(analysis, start=start_dt, end=end_dt)
    if not days:
        console.print(
            f"[canvod.warning]No GNSS data for {analysis} in this range.[/canvod.warning]"
        )
        raise typer.Exit(1)
    console.print(
        f"Computing VOD for [bold]{site}[/bold]/{analysis} (calculator={calculator}), "
        f"{len(days)} day(s)..."
    )
    _print_report(vod_computer.compute_days(days, [analysis]), analysis, calculator)


def _print_report(report: VodUnitReport, analysis: str, calculator: str) -> None:
    """Say which days were written, stored before, and missing."""
    written = report.written.get(analysis, [])
    stored = report.stored.get(analysis, [])
    console.print(
        f"[canvod.ok]✓[/canvod.ok] {len(written)} day(s) written to '{calculator}/{analysis}'"
        + (f", {len(stored)} already stored from the same GNSS files" if stored else "")
    )
    for day, reason in report.missing.get(analysis, []):
        console.print(
            f"[canvod.warning]  {_yyyydoy(day)}: no VOD, {reason}[/canvod.warning]"
        )


def _yyyydoy(day: Any) -> str:
    from canvod.utils.tools import YYYYDOY

    return YYYYDOY.from_date(day.astype(datetime.date)).to_str()


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
        console.print(
            f"[canvod.error]❌ Unknown VOD analysis:[/canvod.error] {analysis}"
        )
        console.print(f"  Available: {list(site_obj.vod_analyses)}")
        raise typer.Exit(1)

    gaps = find_vod_backfill_gaps(site_obj, analysis, calculator)
    if not gaps:
        console.print(
            f"[canvod.ok]✓[/canvod.ok] No VOD gaps for [bold]{site}[/bold]/{analysis} "
            f"(calculator={calculator})."
        )
        return

    ranges = _group_into_ranges(gaps)
    range_str = ", ".join(s if s == e else f"{s}-{e}" for s, e in ranges)
    console.print(
        f"[canvod.warning]{len(gaps)} date(s)[/canvod.warning] have RINEX data but no VOD for "
        f"[bold]{site}[/bold]/{analysis} (calculator={calculator}): {range_str}"
    )

    if not execute:
        console.print("Dry run: pass --execute to backfill.")
        return

    vod_computer = VodComputer(site_obj, calculator=calculator)
    days = [_to_datetime(day, end_of_day=False).date() for day in gaps]
    _print_report(vod_computer.compute_days(days, [analysis]), analysis, calculator)


if __name__ == "__main__":
    typer.run(vod)
