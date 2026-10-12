"""Pipeline output reporters: plain (non-TTY) and Rich Live (TTY).

Usage
-----
    rows = [(site_name, group_name, total_days), ...]  # known upfront
    with make_reporter(rows) as r:
        r.set_current_site(site_name, start, end)
        r.print_header(site_name, start, end, config, args)
        r.on_day_start(date_key)
        r.on_datasets(datasets)
        r.on_vod_result(analysis, n_valid, n_total, dt)
        r.on_timing(dt_pipeline, dt_vod, dt_vod_store)
        r.advance(site_name, group_name)  # called from an on_group_written callback
        r.on_done(total_days, total_vod, dt_total)

Non-TTY (cron, CI, pipes): plain print() — identical to pre-dashboard output.
TTY: Rich Live display — one progress row per (site, receiver-group), known
upfront so a multi-site run shows every row from the start; per-day detail
scrolls above via live.console.print(). There is no aggregate "Overall" bar:
sites are processed sequentially, so the header panel's "current site" text
plus the per-row bars are the whole picture.
"""

from __future__ import annotations

import sys
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import xarray as xr
    from rich.live import Live
    from rich.progress import TaskID


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def day_count(start: str, end: str) -> int:
    """Estimate calendar days between two YYYYDOY strings (inclusive)."""
    parse = lambda s: datetime.strptime(s, "%Y%j")  # noqa: E731
    return max(1, (parse(end) - parse(start)).days + 1)


# ---------------------------------------------------------------------------
# Plain reporter — non-TTY, cron, CI
# ---------------------------------------------------------------------------


class PlainReporter:
    """Writes to stdout via print(). Behavior identical to pre-dashboard output."""

    def __init__(self, rows: list[tuple[str, str, int]]) -> None:
        self._rows = rows
        self._current_site = ""

    def log(self, msg: str) -> None:
        print(msg)

    def set_current_site(self, site: str, start: str, end: str) -> None:
        self._current_site = site
        print("=" * 72)
        print(f"canvodpy  site={site}  {start} .. {end}")
        print("=" * 72)

    def print_header(self, site: str, start: str, end: str, config, args=None) -> None:
        proc = config.processing.params
        storage = config.processing.storage
        print(f"  started        {datetime.now():%Y-%m-%d %H:%M:%S}")
        print(f"  ephemeris      {proc.ephemeris_source}")
        print(f"  keep_vars      {proc.keep_gnss_observables}")
        if args is not None:
            print(f"  days_per_batch {args.days_per_batch or proc.days_per_batch}")
        print(f"  resource_mode  {proc.resource_mode}")
        print(f"  store_strategy {storage.gnss_store_strategy}")
        if args is not None:
            print(f"  gnss_store     {storage.gnss_store_name or 'rinex'}")
            print(f"  vod_store      {storage.vod_store_name or 'vod'}")
            print(f"  vod            {'skip' if args.no_vod else 'enabled'}")
        print()

    def advance(self, site: str, group: str) -> None:
        pass  # no bar to advance in plain mode

    def on_day_start(self, date_key: str) -> None:
        print(f"\n--- {self._current_site}/{date_key} ---")

    def on_datasets(self, datasets: dict[str, xr.Dataset]) -> None:
        for group, ds in datasets.items():
            e = ds.sizes.get("epoch", 0)
            s = ds.sizes.get("sid", 0)
            print(f"  {group}: {e} epochs × {s} sids")

    def on_vod_result(
        self, analysis: str, n_valid: int, n_total: int, dt: float
    ) -> None:
        pct = 100 * n_valid / n_total if n_total else 0
        print(f"  VOD {analysis}: {n_valid}/{n_total} valid ({pct:.0f}%)  {dt:.1f}s")

    def on_vod_failed(self, analysis: str, error: str) -> None:
        print(f"  VOD {analysis}: FAILED: {error}")

    def on_timing(self, dt_pipeline: float, dt_vod: float, dt_vod_store: float) -> None:
        print(
            f"  pipeline={dt_pipeline:.1f}s"
            f"  vod={dt_vod:.1f}s"
            f"  vod_store={dt_vod_store:.1f}s"
        )

    def on_done(self, total_days: int, total_vod: int, dt_total: float) -> None:
        print()
        print("=" * 72)
        print(
            f"Done  {total_days} days  {total_vod} VOD analyses  {dt_total:.0f}s total"
        )
        print("=" * 72)

    def __enter__(self) -> PlainReporter:
        return self

    def __exit__(self, *_) -> None:
        pass


# ---------------------------------------------------------------------------
# Rich reporter — TTY
# ---------------------------------------------------------------------------


class RichReporter:
    """Rich Live display: header panel + one progress row per (site, group).

    Per-day detail lines are printed above the live region via
    live.console.print(), which Rich handles without flicker.
    """

    def __init__(self, rows: list[tuple[str, str, int]]) -> None:
        self._current_site = ""
        self._current_start = ""
        self._current_end = ""
        self._live: Live | None = None

        from rich.console import Console
        from rich.progress import (
            BarColumn,
            MofNCompleteColumn,
            Progress,
            SpinnerColumn,
            TaskID,  # noqa: F401
            TextColumn,
            TimeElapsedColumn,
            TimeRemainingColumn,
        )

        self._console = Console()
        self._progress = Progress(
            SpinnerColumn(),
            TextColumn("  [bold]{task.description}[/bold]"),
            BarColumn(
                bar_width=None, complete_style="green3", finished_style="dim green"
            ),
            MofNCompleteColumn(),
            TextColumn("[dim]days[/dim]"),
            TimeElapsedColumn(),
            TextColumn("[dim]eta[/dim]"),
            TimeRemainingColumn(),
            console=self._console,
        )
        self._task_ids: dict[tuple[str, str], TaskID] = {
            (site, group): self._progress.add_task(f"{site}/{group}", total=total)
            for site, group, total in rows
        }

    def _render(self):
        try:
            from rich.group import Group  # rich >= 12.0
        except ImportError:
            from rich.console import Group  # rich < 12.0
        from rich.panel import Panel

        site4 = self._current_site[:4].upper() if self._current_site else "----"
        content = f"─[◉]─  canvod · {site4} · {self._current_start}–{self._current_end}"
        return Group(
            Panel(content, border_style="dim green", padding=(0, 1)),
            self._progress,
        )

    @property
    def _live_obj(self) -> Live:
        assert self._live is not None, "must be used as a context manager"
        return self._live

    def __enter__(self) -> RichReporter:
        from rich.live import Live

        self._live = Live(
            self._render(),
            console=self._console,
            refresh_per_second=4,
        )
        self._live.start(refresh=True)
        return self

    def __exit__(self, *_) -> None:
        if self._live is not None:
            self._live.stop()

    def log(self, msg: str) -> None:
        self._live_obj.console.print(msg)

    def set_current_site(self, site: str, start: str, end: str) -> None:
        self._current_site = site
        self._current_start = start
        self._current_end = end
        self._live_obj.update(self._render())
        self._live_obj.console.print(f"\n[bold green]═══ {site} ═══[/bold green]")

    def print_header(self, site: str, start: str, end: str, config, args=None) -> None:
        proc = config.processing.params
        self._live_obj.console.print(
            f"[dim]  ephemeris={proc.ephemeris_source}"
            f"  resource_mode={proc.resource_mode}"
            f"  strategy={config.processing.storage.gnss_store_strategy}[/dim]"
        )

    def advance(self, site: str, group: str) -> None:
        task_id = self._task_ids.get((site, group))
        if task_id is not None:
            self._progress.advance(task_id)
            self._live_obj.update(self._render())

    def on_day_start(self, date_key: str) -> None:
        self._live_obj.console.print(
            f"\n[bold]─── {self._current_site}/{date_key}[/bold]"
        )

    def on_datasets(self, datasets: dict[str, xr.Dataset]) -> None:
        for group, ds in datasets.items():
            e = ds.sizes.get("epoch", 0)
            s = ds.sizes.get("sid", 0)
            self._live_obj.console.print(f"  [dim]{group}: {e}×{s}[/dim]")

    def on_vod_result(
        self, analysis: str, n_valid: int, n_total: int, dt: float
    ) -> None:
        pct = 100 * n_valid / n_total if n_total else 0
        self._live_obj.console.print(
            f"  [dim]VOD {analysis}: {n_valid}/{n_total} valid ({pct:.0f}%)  {dt:.1f}s[/dim]"
        )

    def on_vod_failed(self, analysis: str, error: str) -> None:
        self._live_obj.console.print(
            f"[yellow]  VOD {analysis}: FAILED: {error}[/yellow]"
        )

    def on_timing(self, dt_pipeline: float, dt_vod: float, dt_vod_store: float) -> None:
        self._live_obj.console.print(
            f"  [dim]pipeline={dt_pipeline:.1f}s"
            f"  vod={dt_vod:.1f}s"
            f"  vod_store={dt_vod_store:.1f}s[/dim]"
        )

    def on_done(self, total_days: int, total_vod: int, dt_total: float) -> None:
        self._live_obj.console.print()
        self._live_obj.console.print(
            f"[bold green]Done  {total_days} days  "
            f"{total_vod} VOD analyses  {dt_total:.0f}s total[/bold green]"
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def make_reporter(
    rows: list[tuple[str, str, int]],
    *,
    tty: bool | None = None,
) -> PlainReporter | RichReporter:
    """Return a RichReporter when running in a TTY, PlainReporter otherwise.

    Parameters
    ----------
    rows : list[tuple[str, str, int]]
        One entry per (site_name, receiver_group, total_days) — every row
        known upfront so a multi-site run shows the full picture from the
        start.
    """
    if tty is None:
        tty = sys.stdout.isatty()
    if tty:
        return RichReporter(rows)
    return PlainReporter(rows)
