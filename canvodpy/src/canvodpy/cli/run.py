"""canvodpy CLI: process GNSS observations and compute VOD.

Usage
-----
    # Process a specific range
    uv run canvodpy run --site ExampleSite --start 2025001 --end 2025007

    # Process new data only (auto-detect start from store, end = today)
    uv run canvodpy run --site ExampleSite

    # Multiple sites in one invocation (processed sequentially) — repeat the flag
    uv run canvodpy run --site ExampleSite --site OtherSite

    # Cron: run daily, picks up new data automatically
    # 0 3 * * * cd /path/to/canvodpy && uv run canvodpy run --site ExampleSite

    # Observation ingestion only, no VOD
    uv run canvodpy run --site ExampleSite --no-vod

    # Preview what would be processed
    uv run canvodpy run --site ExampleSite --dry-run

    # Write the STAC catalog of the data root once the run's data is committed
    uv run canvodpy run --site ExampleSite --write-catalog

    # Launch the performance dashboard alongside the run (reachable at
    # http://<host>:<port>; its own marimo startup output is redirected to
    # <log_dir>/machine/dashboard.log so it doesn't clutter run's progress)
    uv run canvodpy run --site ExampleSite --dashboard --dashboard-host 0.0.0.0
"""

from __future__ import annotations

import enum
import os
import socket
import subprocess
import sys
import time
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated

import numpy as np
import structlog
import typer
import xarray as xr

from canvod.config.models import reference_store_group
from canvod.store_metadata import store_exists
from canvod.utils.logging import (
    new_run_id,
    record_stage_timing,
    reset_run_id,
    reset_run_stats,
    set_run_id,
)
from canvodpy.cli.options import CONFIG_DIR_OPTION, VodCalculatorChoice
from canvodpy.logging import emit_run_summary
from canvodpy.orchestrator.resources import ResourceSampler
from canvodpy.orchestrator.store_retry import call_with_store_retries

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


def _start_dashboard(log_dir: Path, host: str, port: int) -> None:
    """Spawn the marimo performance dashboard as a detached subprocess.

    Its stdout/stderr go to a log file, not the terminal — the whole point
    is that ``canvodpy run``'s own progress output stays the only thing
    visible in the foreground. The subprocess outlives this command (no
    wait/terminate), so the dashboard stays up for reviewing the finished
    run.
    """
    from canvodpy.cli.perf_dashboard import _NOTEBOOK_PATH

    env = os.environ.copy()
    env["CANVODPY_PERF_LOG_DIR"] = str(log_dir)
    machine_dir = log_dir / "machine"
    machine_dir.mkdir(parents=True, exist_ok=True)
    dash_log = machine_dir / "dashboard.log"

    subprocess.Popen(
        [
            sys.executable,
            "-m",
            "marimo",
            "run",
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


class EphemerisSourceChoice(enum.StrEnum):
    final = "final"
    broadcast = "broadcast"


def _last_processed_date(store) -> str | None:
    """Query the store's metadata tables for the latest processed epoch.

    Returns YYYYDOY string or None if the store is empty.
    """
    try:
        groups = store.list_groups()
    except Exception:
        return None

    if not groups:
        return None

    latest_epoch = None
    with store.readonly_session() as session:
        for group in groups:
            try:
                df = store.read_metadata_table(session, group)
                if df.is_empty():
                    continue
                group_max = df["end"].max()
                if latest_epoch is None or group_max > latest_epoch:
                    latest_epoch = group_max
            except Exception:
                continue

    if latest_epoch is None:
        return None

    # Convert polars datetime to YYYYDOY
    if hasattr(latest_epoch, "to_pydatetime"):
        dt = latest_epoch  # polars Datetime
    else:
        dt = latest_epoch

    # polars returns python datetime
    import polars as pl

    if isinstance(latest_epoch, pl.Series):
        latest_epoch = latest_epoch.item()

    if hasattr(latest_epoch, "timetuple"):
        tt = latest_epoch.timetuple()
        return f"{tt.tm_year}{tt.tm_yday:03d}"

    # numpy datetime64 fallback
    ts = (latest_epoch - np.datetime64("1970-01-01T00:00:00")) / np.timedelta64(1, "s")
    dt = datetime.fromtimestamp(float(ts), tz=UTC).replace(tzinfo=None)
    return f"{dt.year}{dt.timetuple().tm_yday:03d}"


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


def _resolve_date_range(args, site) -> tuple[str, str]:
    """Resolve start/end from args, store state, and today's date."""
    # End date: explicit or today
    end = args.end or _today_yyyydoy()

    # Start date: explicit, or resume from store
    if args.start:
        start = args.start
    else:
        last = (
            _last_processed_date(site.gnss_store)
            if store_exists(site.gnss_store_path)
            else None
        )
        if last is not None:
            # Start from the day after the last processed date
            # (the skip strategy handles overlap, but this avoids
            #  scanning days we know are complete)
            start = last  # include last day too — skip handles duplicates
            print(f"  resuming from store (last processed: {last})")
        else:
            # Empty store: start from earliest available data
            start = "2000001"
            print("  empty store, scanning all available data")

    return start, end


def _compute_vod_for_day(
    vod_computer,
    datasets: dict[str, xr.Dataset],
    vod_analyses: dict,
    date_key: str,
    reporter=None,
) -> dict[str, xr.Dataset]:
    """Compute VOD for all configured analysis pairs, without writing.

    Each analysis goes through ``VodComputer.compute_day`` (the same code as
    ``site.vod`` in Python). Terminal-only behavior: an analysis whose
    receiver groups are missing is skipped, and a failing analysis is
    logged and reported instead of stopping the run. The caller writes the
    results with ``VodComputer.write_day``.

    Parameters
    ----------
    vod_computer
        ``VodComputer`` for the site and the selected calculator.
    datasets
        ``{group_name: ds}`` dict as yielded by ``process_range``.
        Group names: ``canopy_01``, ``reference_01_canopy_01``, etc.
    vod_analyses
        VOD analysis configs from ``site.vod_analyses``.
    date_key
        YYYYDOY string for logging.

    Returns
    -------
    dict mapping analysis name to its VOD dataset.
    """
    results: dict[str, xr.Dataset] = {}

    for analysis_name in vod_analyses:
        t0 = time.perf_counter()
        try:
            vod_ds = vod_computer.compute_day(datasets, analysis_name, write=False)
        except KeyError as e:
            log.warning(
                "vod_skipped",
                analysis=analysis_name,
                reason=str(e),
                date=date_key,
            )
            continue
        except Exception as e:
            log.error(
                "vod_failed",
                analysis=analysis_name,
                date=date_key,
                error=str(e),
            )
            if reporter:
                reporter.on_vod_failed(analysis_name, str(e))
            else:
                print(f"  VOD {analysis_name}: FAILED: {e}")
            continue

        dt = time.perf_counter() - t0
        record_stage_timing(
            "vod_calc",
            dt,
            date_key=date_key,
            calculator=vod_computer.calculator_name,
            analysis=analysis_name,
        )
        n_valid = int((~vod_ds["VOD"].isnull()).sum())
        n_total = vod_ds["VOD"].size
        if reporter:
            reporter.on_vod_result(analysis_name, n_valid, n_total, dt)
        else:
            pct = 100 * n_valid / n_total if n_total else 0
            print(
                f"  VOD {analysis_name}: {n_valid}/{n_total} valid ({pct:.0f}%)  {dt:.1f}s"
            )
        results[analysis_name] = vod_ds

    return results


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

    from canvodpy.api import Site
    from canvodpy.vod_computer import VodComputer

    site_names: list[str] = args.site

    if args.dry_run:
        for site_name in site_names:
            site = Site(site_name)
            start, end = _resolve_date_range(args, site)
            with site.pipeline(
                n_workers=args.workers,
                days_per_batch=args.days_per_batch,
                dry_run=True,
            ) as pipeline:
                plan = pipeline.preview(start=start, end=end)
                print(f"Dry-run plan for {site_name}:")
                for k, v in plan.items():
                    print(f"  {k}: {v}")
        return 0

    if args.dashboard:
        _start_dashboard(
            config.processing.logging.get_log_dir(),
            args.dashboard_host,
            args.dashboard_port or _pick_free_port(args.dashboard_host),
        )

    from canvodpy.cli.dashboard import day_count, make_reporter

    # Resolve every site upfront: date range + receiver-group rows, so a
    # multi-site run shows the full picture from the start.
    site_infos: list[tuple[str, Site, str, str]] = []
    rows: list[tuple[str, str, int]] = []
    for site_name in site_names:
        site = Site(site_name)
        start, end = _resolve_date_range(args, site)
        total = day_count(start, end)
        for group in _site_groups(site):
            rows.append((site_name, group, total))
        site_infos.append((site_name, site, start, end))

    total_days = 0
    total_vod = 0
    t_total = time.perf_counter()

    from canvodpy.orchestrator.resources import PipelineRunLock

    # Marks this process as an active pipeline run for the duration of the
    # real write loop below (not the dry-run preview above, which returns
    # before this point) -- lets `canvodpy store maintain-due` (a
    # cron-safe, unattended Icechunk maintenance entry point) skip itself
    # instead of racing an in-progress write. Same-host only; see
    # PipelineRunLock's docstring for the network-mounted-store caveat.
    with PipelineRunLock(), make_reporter(rows) as reporter:
        for site_name, site, start, end in site_infos:
            # One run_id per site: failures are site-scoped, and this keeps
            # correlation with Icechunk commits (also per-site-store) clean.
            run_id = new_run_id(site_name)
            run_id_token = set_run_id(run_id)
            last_good_date_key: str | None = None
            stage = "site_init"
            site_days = 0
            site_vod = 0

            # Continuous memory/CPU/disk-I/O visibility for the whole
            # site run (perf-degradation investigation, 2026-07-14) --
            # complements the once-per-batch MemoryMonitor snapshot with
            # samples covering time spent outside batch boundaries too.
            resource_sampler = ResourceSampler()
            resource_sampler.start()

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
                vod_computer.check_preprocessing(list(vod_analyses))

                def _on_group_written(
                    group_name: str, _site_name: str = site_name
                ) -> None:
                    reporter.advance(_site_name, group_name)

                stage = "pipeline_process"
                with site.pipeline(
                    n_workers=args.workers,
                    days_per_batch=args.days_per_batch,
                    dry_run=False,
                    on_group_written=_on_group_written,
                ) as pipeline:
                    gen = pipeline.process_range(start=start, end=end)
                    while True:
                        t_pipeline = time.perf_counter()
                        try:
                            date_key, datasets = next(gen)
                        except StopIteration:
                            break
                        dt_pipeline = time.perf_counter() - t_pipeline

                        total_days += 1
                        site_days += 1
                        reporter.on_day_start(date_key)
                        reporter.on_datasets(datasets)

                        dt_vod = 0.0
                        dt_vod_store = 0.0
                        if vod_analyses:
                            stage = "vod_calc"
                            t_vod = time.perf_counter()
                            vod_results = _compute_vod_for_day(
                                vod_computer,
                                datasets,
                                vod_analyses,
                                date_key,
                                reporter,
                            )
                            dt_vod = time.perf_counter() - t_vod

                            stage = "vod_store"
                            t_vod_store = time.perf_counter()
                            if vod_results:
                                # VodComputer.write_day: one commit for all
                                # of today's analysis pairs, then the VOD
                                # store metadata. Retried as one unit: the
                                # batch write is all-or-nothing (fail-fast,
                                # no partial merge -- see
                                # write_or_append_vod_groups_batch), so a
                                # retry after a transient error is safe --
                                # any pre-pass commit for a brand-new group
                                # that already landed is dedup-visible and
                                # won't be re-attempted.
                                batch_results = call_with_store_retries(
                                    partial(
                                        vod_computer.write_day,
                                        datasets,
                                        vod_results,
                                    ),
                                    logger=log,
                                    date=date_key,
                                    op="vod_write_batch",
                                )
                                for analysis_name in vod_results:
                                    group_name = (
                                        f"{args.vod_calculator}/{analysis_name}"
                                    )
                                    group_result = batch_results.get(group_name)
                                    record_stage_timing(
                                        "vod_store",
                                        group_result.duration_seconds
                                        if group_result is not None
                                        else 0.0,
                                        date_key=date_key,
                                        calculator=args.vod_calculator,
                                        analysis=analysis_name,
                                    )
                            dt_vod_store = time.perf_counter() - t_vod_store
                            total_vod += len(vod_results)
                            site_vod += len(vod_results)

                        reporter.on_timing(dt_pipeline, dt_vod, dt_vod_store)
                        last_good_date_key = date_key
                        stage = "pipeline_process"

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
                resource_sampler.stop()
                reset_run_stats(run_id)
                reset_run_id(run_id_token)

        dt_total = time.perf_counter() - t_total
        reporter.on_done(total_days, total_vod, dt_total)

    return 0


def run(
    site: Annotated[
        list[str],
        typer.Option(
            "--site",
            help=(
                "Site name, as defined under sites: in canvod-settings.yaml, "
                "for example ExampleSite. Repeat the option for several "
                "sites, which run one after the other."
            ),
        ),
    ],
    start: Annotated[
        str | None,
        typer.Option(
            "--start",
            help=(
                "Start date in YYYYDOY format, for example 2025001. If omitted, "
                "resumes from the last processed date in the store."
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
    no_vod: Annotated[
        bool,
        typer.Option(
            "--no-vod/--vod",
            help="Skip the VOD calculation: only write the observations to the GNSS store.",
        ),
    ] = False,
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
            help=(
                "Number of days that the workers process together. Default: "
                "processing.params.days_per_batch in canvod-settings.yaml."
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
) -> None:
    """Process GNSS observations into Icechunk stores and compute VOD."""
    args = SimpleNamespace(
        site=site,
        start=start,
        end=end,
        no_vod=no_vod,
        dry_run=dry_run,
        workers=workers,
        days_per_batch=days_per_batch,
        config=config,
        ephemeris_source=ephemeris_source.value if ephemeris_source else None,
        vod_calculator=vod_calculator.value,
        dashboard=dashboard,
        dashboard_host=dashboard_host,
        dashboard_port=dashboard_port,
    )
    from canvod.config.models import PreprocessingMismatchError
    from canvod.store.prepare import (
        EpochTimeSystemError,
        GroupCoordinatesMismatchError,
        GroupVariablesMismatchError,
    )
    from canvodpy.orchestrator.discovery import DiscoveryError

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
    if code == 0 and write_catalog and not dry_run:
        code = _write_catalog(config)
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
