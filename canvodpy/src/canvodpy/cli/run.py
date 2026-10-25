"""canvodpy CLI: process GNSS observations and compute VOD.

Usage
-----
    # Process a specific range
    uv run canvodpy run --site ExampleSite --start 2025001 --end 2025007

    # Process the days from the last stored day up to the latest files
    uv run canvodpy run --site ExampleSite --update-to-latest

    # One site per run; several sites in a shell loop
    for site in ExampleSite OtherSite; do
        uv run canvodpy run --site "$site" --update-to-latest
    done

    # Cron: run daily, picks up new data
    # 0 3 * * * cd /path/to/canvodpy && uv run canvodpy run --site ExampleSite --update-to-latest

    # Observation ingestion only, no VOD
    uv run canvodpy run --site ExampleSite --start 2025001 --no-vod

    # Preview what would be processed
    uv run canvodpy run --site ExampleSite --update-to-latest --dry-run

    # Write the STAC catalog of the data root once the run's data is committed
    uv run canvodpy run --site ExampleSite --update-to-latest --write-catalog

    # Launch the performance dashboard alongside the run (reachable at
    # http://<host>:<port>; its own marimo startup output is redirected to
    # <log_dir>/machine/dashboard.log so it doesn't clutter run's progress)
    uv run canvodpy run --site ExampleSite --update-to-latest --dashboard --dashboard-host 0.0.0.0

    # The same, but stop the dashboard when the run ends (by default it
    # stays up to show the finished run until its button shuts it down)
    uv run canvodpy run --site ExampleSite --update-to-latest --dashboard --dashboard-stop-at-end

Exit codes
----------
    0  every receiver-day was written or skipped, or nothing was new
    1  the run stopped: an error in the options or the settings, or a crash
    3  the run finished, but at least one receiver-day failed
"""

from __future__ import annotations

import enum
import os
import socket
import subprocess
import sys
import time
from collections.abc import Callable, Generator
from contextlib import contextmanager
from datetime import datetime
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Annotated

import structlog
import typer

from canvod.config.models import reference_store_group
from canvod.store_metadata import (
    StorageUnreachableError,
    missing_store_settings,
    missing_store_settings_message,
    store_exists,
)
from canvod.utils.logging import (
    new_run_id,
    reset_run_id,
    reset_run_stats,
    set_run_id,
)
from canvodpy.cli.options import CONFIG_DIR_OPTION, VodCalculatorChoice
from canvodpy.logging import emit_run_summary

if TYPE_CHECKING:
    from canvod.config import CanvodConfig
    from canvodpy.api import Site

log = structlog.get_logger(__name__)


def _pick_free_port(host: str) -> int:
    """Ask the OS for a free port, bound to the same host the dashboard will use.

    Binding the discovery socket to ``host`` (rather than all interfaces)
    guarantees the returned port is actually free on the interface the
    dashboard will bind to next -- discovering on a different interface
    (e.g. loopback) could return a port already taken on ``host``.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return s.getsockname()[1]


def _start_dashboard(log_dir: Path, host: str, port: int) -> subprocess.Popen:
    """Spawn the marimo performance dashboard as a detached subprocess.

    Its stdout/stderr go to a log file, not the terminal — the whole point
    is that ``canvodpy run``'s own progress output stays the only thing
    visible in the foreground. The subprocess outlives this command unless
    --dashboard-stop-at-end is set, so the dashboard stays up for reviewing
    the finished run; its button shuts it down.
    """
    from canvodpy.cli.dashboards.shutdown import RUN_VARIABLE, run_marker
    from canvodpy.cli.perf_dashboard import _NOTEBOOK_PATH

    env = os.environ.copy()
    env["CANVODPY_PERF_LOG_DIR"] = str(log_dir)
    env[RUN_VARIABLE] = run_marker()
    machine_dir = log_dir / "machine"
    machine_dir.mkdir(parents=True, exist_ok=True)
    dash_log = machine_dir / "dashboard.log"

    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "marimo",
            "run",
            "--no-sandbox",
            str(_NOTEBOOK_PATH),
            "--host",
            host,
            "--port",
            str(port),
            "--headless",
        ],
        env=env,
        stdout=open(dash_log, "w"),
        stderr=subprocess.STDOUT,
    )
    print(f"Dashboard: http://{host}:{port}  (output: {dash_log})")
    return process


class EphemerisSourceChoice(enum.StrEnum):
    final = "final"
    broadcast = "broadcast"


def _today_yyyydoy() -> str:
    now = datetime.now()
    return f"{now.year}{now.timetuple().tm_yday:03d}"


def _site_groups(site) -> list[str]:
    """List receiver-group names as used in the Icechunk store.

    Canopy receivers write under their own name (``canopy_01``); each
    reference/canopy pair writes under ``{reference}_{canopy}``.
    """
    canopy_names = [
        name
        for name, cfg in site.active_receivers.items()
        if cfg.get("type") == "canopy"
    ]
    pair_names = [
        reference_store_group(ref, canopy)
        for ref, canopy in site._site.get_reference_canopy_pairs()
    ]
    return canopy_names + pair_names


def _resolve_date_range(
    args, site, emit: Callable[[str], None]
) -> tuple[str, str] | None:
    """The run's first and last day (``YYYYDOY``); None when nothing is new.

    With ``--start`` the dates are given (``--end`` defaults to today).
    With ``--update-to-latest`` the run finds them
    (:meth:`canvodpy.api.Pipeline.update_range`) and says through ``emit``
    which it chose, or that no receiver has new files.

    Raises
    ------
    NothingStoredError
        With ``--update-to-latest``, if nothing is stored for the site yet.
    """
    if not args.update_to_latest:
        return args.start, args.end or _today_yyyydoy()
    on_discovery_start, on_discovery_end = _discovery_callbacks(emit)
    with site.pipeline(
        dry_run=True,
        on_discovery_start=on_discovery_start,
        on_discovery_end=on_discovery_end,
    ) as pipeline:
        dates = pipeline.update_range()
    if dates is None:
        emit("update: no receiver has new files")
        return None
    emit(f"update: {dates[0]} to {dates[1]}")
    return dates


def _first_ten(items: list[str]) -> str:
    """The first ten items, comma-separated, and how many more there are."""
    shown = ", ".join(items[:10])
    more = len(items) - 10
    return f"{shown} and {more} more" if more > 0 else shown


def _print_incomplete_day(
    emit: Callable[[str], None], receiver: str, day: str, found: int, expected: int
) -> None:
    """Say through ``emit`` that a receiver-day misses files (#387)."""
    emit(f"  incomplete: {receiver} has {found} of {expected} files on {day}")


def _print_days_without_vod(
    emit: Callable[[str], None], receiver: str, days: list[str]
) -> None:
    """Say through ``emit`` which days get no VOD as ``receiver`` has no files."""
    noun = "day" if len(days) == 1 else "days"
    emit(f"  no VOD on {len(days)} {noun}, {receiver} has no files: {_first_ten(days)}")


def _report_vod_unit(unit, reporter) -> int:
    """Say what the VOD phase did with a unit's days; return the VOD days written.

    Per analysis, the days written, and each day without VOD with the
    reason. A failed VOD phase is said with the days it leaves without
    VOD; ``canvodpy vod-reconcile`` fills them later.
    """
    days = sorted(unit.days)
    if unit.vod_error is not None:
        reporter.log(
            f"  VOD {days[0]}..{days[-1]}: FAILED: {unit.vod_error} (the log "
            "says why; 'canvodpy vod-reconcile' computes the days later)"
        )
        return 0
    report = unit.vod
    for analysis, written in report.written.items():
        reporter.log(f"  VOD {analysis}: {len(written)} days written")
    for analysis, stored in report.stored.items():
        reporter.log(f"  VOD {analysis}: {len(stored)} days already stored")
    for analysis, missing in report.missing.items():
        for day, reason in missing:
            reporter.log(f"  VOD {analysis}: no VOD on {day}: {reason}")
    return sum(len(written) for written in report.written.values())


#: Exit code of a run that finished with failed receiver-days (#334). 2 is taken: typer exits with 2 on a usage error.
EXIT_DAYS_FAILED = 3


def _report_failed_days(failed: list[tuple[str, str, str]]) -> None:
    """Name the failed receiver-days of a run, on stderr."""
    noun = "receiver-day" if len(failed) == 1 else "receiver-days"
    days = ", ".join(" ".join(day) for day in failed)
    print(
        f"{len(failed)} {noun} failed: {days}. The log says why (human/errors.log).",
        file=sys.stderr,
    )


def _discovery_callbacks(
    emit: Callable[[str], None],
) -> tuple[Callable[[str, Path], None], Callable[[str, int, int, float], None]]:
    """Build the two discovery callbacks that report through ``emit``.

    ``emit`` writes one line (``print`` for a dry-run, ``reporter.log`` for a
    real run), so the CLI owns the display and the library stays quiet. The
    count words are singular when there is one file or one day.
    """

    def on_start(receiver_name: str, folder: Path) -> None:
        emit(
            f"  Finding files of receiver {receiver_name} in {folder} "
            f"(can take minutes on a network drive)..."
        )

    def on_end(receiver_name: str, n_files: int, n_days: int, seconds: float) -> None:
        file_word = "file" if n_files == 1 else "files"
        day_word = "day" if n_days == 1 else "days"
        emit(
            f"  Found {n_files} {file_word} on {n_days} {day_word} for receiver "
            f"{receiver_name} ({seconds:.1f} s)."
        )

    return on_start, on_end


def _main_impl(args: SimpleNamespace) -> int:
    from pathlib import Path

    from canvod.config import load_config
    from canvod.config.loader import ConfigValidationError, format_validation_error

    config_file: Path | None = None
    if args.config is not None:
        config_file = Path(args.config)
        if not config_file.exists():
            print(
                f"Error: overlay config file not found: {config_file}", file=sys.stderr
            )
            return 1
        os.environ["CANVOD_CONFIG_FILE"] = str(config_file.expanduser().resolve())

    try:
        config = load_config(config_file=config_file)
    except ConfigValidationError as e:
        print(format_validation_error(e), file=sys.stderr)
        return 1
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    # Before any work: a run writes log files, so it needs the log folder.
    from canvod.config.models.logging import LogDirNotSetError

    try:
        config.processing.logging.get_log_dir()
    except LogDirNotSetError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if args.ephemeris_source is not None:
        config.processing.params.ephemeris_source = args.ephemeris_source

    from canvodpy.cli.banner import show_banner

    show_banner()  # interactive terminals only, as the progress display

    from canvodpy.api import Site, _passed

    site_name: str = args.site
    site = Site(site_name)
    dates = _resolve_date_range(args, site, print)
    if dates is None:
        return 0
    start, end = dates

    if args.dry_run:
        on_discovery_start, on_discovery_end = _discovery_callbacks(print)
        with site.pipeline(
            n_workers=args.workers,
            **_passed(days_per_batch=args.days_per_batch),
            dry_run=True,
            on_discovery_start=on_discovery_start,
            on_discovery_end=on_discovery_end,
            on_incomplete_day=partial(_print_incomplete_day, print),
            on_days_without_vod=partial(_print_days_without_vod, print),
        ) as pipeline:
            plan = pipeline.preview(start=start, end=end)
            print(f"Dry-run plan for {site_name}:")
            for k, v in plan.items():
                print(f"  {k}: {v}")
        return 0

    with _dashboard_for_run(args, config.processing.logging.get_log_dir()):
        return _process_days(args, config, site, start, end)


@contextmanager
def _dashboard_for_run(args: SimpleNamespace, log_dir: Path) -> Generator[None]:
    """The dashboard of --dashboard, for the length of the run.

    It stays up after the run to show it, until its button shuts it down;
    with --dashboard-stop-at-end it stops when the run ends, also when the
    run fails or is stopped with Ctrl-C.
    """
    if not args.dashboard:
        yield
        return
    dashboard = _start_dashboard(
        log_dir,
        args.dashboard_host,
        args.dashboard_port or _pick_free_port(args.dashboard_host),
    )
    try:
        yield
    finally:
        if args.dashboard_stop_at_end:
            dashboard.terminate()
            dashboard.wait(timeout=5)
            print("Dashboard stopped (--dashboard-stop-at-end).")
        elif dashboard.poll() is None:
            print(
                "The dashboard is still running, to show the finished run. "
                "Shut it down with its button."
            )


def _process_days(
    args: SimpleNamespace, config: CanvodConfig, site: Site, start: str, end: str
) -> int:
    """Process the site's receiver-days from start to end, with their VOD."""
    from canvodpy.api import _passed
    from canvodpy.cli.dashboard import day_count, make_reporter
    from canvodpy.vod_computer import VodComputer

    site_name: str = args.site

    total = day_count(start, end)
    rows = [(site_name, group, total) for group in _site_groups(site)]

    total_days = 0
    total_vod = 0
    failed_days: list[tuple[str, str, str]] = []
    t_total = time.perf_counter()

    from canvodpy.orchestrator.resources import PipelineRunLock

    # Marks this process as an active pipeline run for the duration of the
    # real write loop below (not the dry-run preview above, which returns
    # before this point) -- lets `canvodpy store maintain-due` (a
    # cron-safe, unattended Icechunk maintenance entry point) skip itself
    # instead of racing an in-progress write. Same-host only; see
    # PipelineRunLock's docstring for the network-mounted-store caveat.
    with PipelineRunLock(), make_reporter(rows) as reporter:
        # One run_id per run, which is one site: this keeps correlation
        # with Icechunk commits (per-site store) clean.
        run_id = new_run_id(site_name)
        run_id_token = set_run_id(run_id)
        last_good_date_key: str | None = None
        stage = "site_init"
        site_days = 0
        site_vod = 0

        try:
            reporter.set_current_site(site_name, start, end)
            reporter.print_header(site_name, start, end, config, args)
            # First-run/remote-machine visibility: worker-pool startup,
            # the satellite catalog, and store opening all happen here,
            # silently, before the first per-day progress line -- without
            # this it looks hung.
            reporter.log(
                "  Initializing (worker pool, satellite catalog, store) "
                "-- may take a while on a cold cache or first run..."
            )

            # Resolve VOD analysis pairs for this site
            vod_analyses = site.vod_analyses if not args.no_vod else {}

            # A first run whose new VOD store is missing settings is
            # refused before processing; the write would refuse every
            # day at the end. With --no-vod the VOD store is not checked.
            _refuse_new_vod_store_missing_settings(site, config, vod_analyses)

            if vod_analyses:
                reporter.log(f"  VOD analyses: {list(vod_analyses.keys())}")

                # Loud, read-only, non-blocking gap check: a prior run's RINEX ingestion can
                # complete cleanly while its VOD-store write fails
                # afterward, and resume logic only looks at the RINEX
                # store, so that gap is otherwise silently permanent.
                # Reports here so a human notices; does NOT
                # auto-backfill -- auto-retrying inside every future
                # run would silently re-absorb a persistent failure
                # instead of stopping loudly. Run `canvodpy
                # vod-reconcile --execute` explicitly to backfill.
                from canvodpy.orchestrator.vod_reconcile import (
                    find_vod_backfill_gaps,
                )

                for analysis_name in vod_analyses:
                    try:
                        gaps = find_vod_backfill_gaps(
                            site, analysis_name, args.vod_calculator
                        )
                    except Exception:
                        log.warning(
                            "vod_gap_check_failed",
                            site=site_name,
                            analysis=analysis_name,
                            exc_info=True,
                        )
                        continue
                    if gaps:
                        reporter.log(
                            f"  ⚠ {len(gaps)} date(s) have RINEX data "
                            f"but no VOD for '{analysis_name}' "
                            f"({gaps[0]}..{gaps[-1]}) -- run 'canvodpy "
                            f"vod-reconcile --site {site_name} --analysis "
                            f"{analysis_name} --execute' to backfill"
                        )

            vod_computer = VodComputer(site, calculator=args.vod_calculator)
            # Before any processing: a VOD group fed by data preprocessed
            # differently would refuse every day at the write.
            stage = "preprocessing_check"
            vod_computer.check_gnss_hash()

            def _on_group_written(group_name: str, _site_name: str = site_name) -> None:
                reporter.advance(_site_name, group_name)

            # Say what the warm-up is doing: before a receiver's files are
            # found and after. A network drive can make this the slowest
            # quiet part of a run, so the user sees it is working.
            on_discovery_start, on_discovery_end = _discovery_callbacks(reporter.log)
            stage = "pipeline_process"
            with site.pipeline(
                n_workers=args.workers,
                **_passed(days_per_batch=args.days_per_batch),
                dry_run=False,
                on_group_written=_on_group_written,
                label=args.label,
                on_discovery_start=on_discovery_start,
                on_discovery_end=on_discovery_end,
                on_incomplete_day=partial(_print_incomplete_day, reporter.log),
                on_days_without_vod=partial(_print_days_without_vod, reporter.log),
            ) as pipeline:
                # The GNSS phase stores a unit of days, then the VOD
                # phase computes their VOD in the same worker pool
                # (ADR 0021); nothing is read back for VOD.
                for unit in pipeline.run(
                    start,
                    end,
                    vod_analyses=list(vod_analyses),
                    calculator=args.vod_calculator,
                ):
                    for date_key, groups in unit.days.items():
                        total_days += 1
                        site_days += 1
                        reporter.on_day_start(date_key)
                        reporter.on_groups(groups)
                        last_good_date_key = date_key
                    if vod_analyses:
                        site_vod += _report_vod_unit(unit, reporter)
                    reporter.on_timing(unit.gnss_seconds, unit.vod_seconds)
                total_vod += site_vod

            failed_days.extend(
                (site_name, receiver, day)
                for receiver, day in pipeline.failed_receiver_days
            )
            emit_run_summary(site=site_name, days=site_days, vod_results=site_vod)
        except Exception:
            # See module docstring / logging/run_context.py: this runs
            # unattended on remote machines, so the log at the moment of
            # failure is the only forensic evidence that will exist.
            log.error(
                "run_crashed",
                site=site_name,
                stage=stage,
                last_good_date_key=last_good_date_key,
                exc_info=True,
            )
            emit_run_summary(
                site=site_name,
                days=site_days,
                vod_results=site_vod,
                crashed=True,
            )
            raise
        finally:
            reset_run_stats(run_id)
            reset_run_id(run_id_token)

        dt_total = time.perf_counter() - t_total
        reporter.on_done(total_days, total_vod, dt_total)

    if failed_days:
        _report_failed_days(failed_days)
        return EXIT_DAYS_FAILED
    return 0


def _refuse_new_vod_store_missing_settings(site, config, vod_analyses) -> None:
    """Refuse a first run before processing if a new VOD store's settings are missing.

    A store records its site description, publisher, license and naming
    authority when it is created. A run that computes VOD for a site whose
    VOD store does not exist yet must not process and only then fail at the
    VOD write: this checks the settings up front. An existing store is never
    checked; with ``--no-vod`` (an empty ``vod_analyses``) the VOD store is
    not checked at all.

    Raises
    ------
    ValueError
        If the new VOD store is missing one of the settings, naming them all.
    """
    if not vod_analyses:
        return  # --no-vod: the VOD store is not written this run
    if store_exists(site.vod_store_path):
        return  # not a first run: the store's metadata is already written
    missing = missing_store_settings(
        site.name, config.sites.sites.get(site.name), config
    )
    if not missing:
        return
    raise ValueError(missing_store_settings_message(missing, store_label="VOD store"))


def run(
    site: Annotated[
        list[str],
        typer.Option(
            "--site",
            help=(
                "Site name, as defined under sites: in canvod-settings.yaml, "
                "for example ExampleSite. One site per run: for several "
                "sites, run canvodpy once per site, for example in a shell "
                "loop."
            ),
        ),
    ],
    start: Annotated[
        str | None,
        typer.Option(
            "--start",
            help=(
                "Start date in YYYYDOY format, for example 2025001. Needed "
                "unless --update-to-latest is given."
            ),
        ),
    ] = None,
    end: Annotated[
        str | None,
        typer.Option(
            "--end",
            help="End date in YYYYDOY format, for example 2025007. If omitted, processes up to today.",
        ),
    ] = None,
    update_to_latest: Annotated[
        bool,
        typer.Option(
            "--update-to-latest",
            help=(
                "Process the days from the last stored day up to the latest "
                "day with files, instead of --start and --end. Starts on the "
                "earliest last stored day among the receivers with new files "
                "(after that day, or on it but not stored yet), so a retired "
                "receiver doesn't hold it back."
            ),
        ),
    ] = False,
    no_vod: Annotated[
        bool,
        typer.Option(
            "--no-vod/--vod",
            help="Skip the VOD calculation: only write the observations to the GNSS store.",
        ),
    ] = False,
    label: Annotated[
        str | None,
        typer.Option(
            "--label",
            help=(
                "Free-text label of the run, stored in the run history, for "
                "example to group the repetitions of a benchmark."
            ),
        ),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run/--no-dry-run",
            help="Preview processing plan without executing.",
        ),
    ] = False,
    workers: Annotated[
        int | None,
        typer.Option(
            "--workers",
            help=(
                "Number of worker processes. Default: from the resource "
                "settings in canvod-settings.yaml."
            ),
        ),
    ] = None,
    days_per_batch: Annotated[
        int | None,
        typer.Option(
            "--days-per-batch",
            hidden=True,
            help=(
                "Deprecated, removed in v2.0.0: the run sizes its units of "
                "days from the memory budget. Only caps the days per unit."
            ),
        ),
    ] = None,
    config_dir: Annotated[Path | None, CONFIG_DIR_OPTION] = None,
    config: Annotated[
        str | None,
        typer.Option(
            "--config",
            help="Settings file whose values replace those of canvod-settings.yaml.",
        ),
    ] = None,
    ephemeris_source: Annotated[
        EphemerisSourceChoice | None,
        typer.Option(
            "--ephemeris-source",
            help=(
                "Where the satellite orbits and clocks come from: final "
                "uses the SP3 and CLK products of an analysis center, "
                "broadcast uses the SatVisibility blocks of the SBF files. "
                "Default: from canvod-settings.yaml."
            ),
        ),
    ] = None,
    vod_calculator: Annotated[
        VodCalculatorChoice,  # ty: ignore[invalid-type-form]
        typer.Option("--vod-calculator", help="VOD calculator to use."),
    ] = VodCalculatorChoice["tau_omega"],
    write_catalog: Annotated[
        bool,
        typer.Option(
            "--write-catalog",
            help=(
                "After the run, write the latest STAC catalog of every "
                "store under the data root, as `canvodpy stac write` does."
            ),
        ),
    ] = False,
    dashboard: Annotated[
        bool,
        typer.Option(
            "--dashboard",
            help=(
                "Start the marimo performance dashboard next to this run, "
                "in a process of its own. Its startup messages go to a log "
                "file, not to this terminal."
            ),
        ),
    ] = False,
    dashboard_host: Annotated[
        str,
        typer.Option("--dashboard-host", help="Host for --dashboard to bind to."),
    ] = "127.0.0.1",
    dashboard_port: Annotated[
        int | None,
        typer.Option(
            "--dashboard-port",
            help="Port for --dashboard to bind to. Default: a free port that the operating system picks.",
        ),
    ] = None,
    dashboard_stop_at_end: Annotated[
        bool,
        typer.Option(
            "--dashboard-stop-at-end",
            help=(
                "Stop the dashboard of --dashboard when the run ends. "
                "Default: it stays up to show the finished run until you "
                "shut it down with its button."
            ),
        ),
    ] = False,
) -> None:
    """Process GNSS observations into Icechunk stores and compute VOD.

    Exits with 0 when every receiver-day is written or skipped, 3 when the
    run finished but a receiver-day failed (the log says why), and 1 when
    the run stopped.
    """
    if len(site) > 1:
        print(
            "Error: one site per run, got "
            f"{', '.join(site)}. Run canvodpy once per site, for example: "
            f'for site in {" ".join(site)}; do canvodpy run --site "$site" '
            "...; done",
            file=sys.stderr,
        )
        raise typer.Exit(code=1)
    if dashboard_stop_at_end and not dashboard:
        print("Error: --dashboard-stop-at-end needs --dashboard.", file=sys.stderr)
        raise typer.Exit(code=1)
    from canvodpy.orchestrator.run_dates import NothingStoredError, check_run_dates

    try:
        check_run_dates(start, end, update_to_latest=update_to_latest)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        raise typer.Exit(code=1) from None
    args = SimpleNamespace(
        site=site[0],
        start=start,
        end=end,
        update_to_latest=update_to_latest,
        no_vod=no_vod,
        label=label,
        dry_run=dry_run,
        workers=workers,
        days_per_batch=days_per_batch,
        config=config,
        ephemeris_source=ephemeris_source.value if ephemeris_source else None,
        vod_calculator=vod_calculator.value,
        dashboard=dashboard,
        dashboard_host=dashboard_host,
        dashboard_port=dashboard_port,
        dashboard_stop_at_end=dashboard_stop_at_end,
    )
    from canvod.config.models import PreprocessingMismatchError
    from canvod.store.prepare import (
        EpochTimeSystemError,
        GroupCoordinatesMismatchError,
        GroupVariablesMismatchError,
    )
    from canvodpy.orchestrator.discovery import DiscoveryError
    from canvodpy.orchestrator.memory_budget import MemoryBudgetError

    try:
        code = _main_impl(args)
    except DiscoveryError as e:
        # The receiver data cannot be assigned unambiguously; the message
        # says what to change, a traceback would only hide it.
        print(
            f"Error: {e}\n\nRun 'canvodpy config validate' to check all "
            f"receivers at once.",
            file=sys.stderr,
        )
        code = 1
    except (
        PreprocessingMismatchError,
        GroupVariablesMismatchError,
        GroupCoordinatesMismatchError,
        EpochTimeSystemError,
    ) as e:
        # Every later day would be refused the same way: stop, and say
        # what to change.
        print(f"Error: {e}", file=sys.stderr)
        code = 1
    except NothingStoredError as e:
        # --update-to-latest needs a stored day to start after.
        print(f"Error: {e}", file=sys.stderr)
        code = 1
    except MemoryBudgetError as e:
        # Not even one worker fits: the message says how much memory the
        # run needs.
        print(f"Error: {e}", file=sys.stderr)
        code = 1
    except StorageUnreachableError as e:
        # The stores' storage (S3) can't be reached: every day would fail.
        # The message names what to check, never the credentials.
        print(f"Error: {e}", file=sys.stderr)
        code = 1
    if code in (0, EXIT_DAYS_FAILED) and write_catalog and not dry_run:
        # The days that were written are committed: catalog them. A failed
        # catalog (1) wins over failed days (3).
        catalog_code = _write_catalog(config)
        code = catalog_code or code
    raise typer.Exit(code=code)


def _write_catalog(config: str | None) -> int:
    """Write the latest catalog of the data root, after a successful run."""
    from canvod.config import load_config
    from canvod.store_metadata import write_catalog

    settings = load_config(config_file=Path(config) if config else None)
    try:
        catalog = write_catalog(settings.processing.storage.stores_root_dir)
    except ValueError as e:
        # The run's commits stand; only the catalog is missing.
        print(
            f"Error: {e}\n\nThe run's data is committed; only the catalog is "
            f"missing. Fix these stores, then run 'canvodpy stac write'.",
            file=sys.stderr,
        )
        return 1
    print(f"Catalog written: {catalog}")
    return 0


if __name__ == "__main__":
    typer.run(run)
