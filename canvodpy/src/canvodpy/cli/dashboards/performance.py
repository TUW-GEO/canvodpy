# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "canvodpy",
#     "marimo",
#     "altair",
# ]
#
# [tool.marimo.display]
# theme = "dark"
# ///
import marimo

__generated_with = "0.25.1"
app = marimo.App(
    width="medium",
    app_title="canvodpy: Run dashboard",
    css_file="canvod_nordic.css",
)


@app.cell
def _():
    from datetime import UTC, datetime, timedelta

    import marimo as mo

    def format_duration(seconds):
        """Short human text for a number of seconds, or 'n/a'."""
        if seconds is None:
            return "n/a"
        if seconds < 60:
            return f"{seconds:.0f} s"
        minutes, remainder = divmod(int(seconds), 60)
        if minutes < 60:
            return f"{minutes} m {remainder} s"
        hours, minutes = divmod(minutes, 60)
        if hours < 24:
            return f"{hours} h {minutes} m"
        days, hours = divmod(hours, 24)
        return f"{days} d {hours} h"

    def eta_text(eta_seconds):
        """Human text for an ETA; an estimate, never a fact."""
        if eta_seconds is None:
            return "none (only for a running run with a finished receiver-day)."
        finish = datetime.now(UTC) + timedelta(seconds=eta_seconds)
        return (
            f"done about {finish.strftime('%H:%M')} UTC "
            f"({format_duration(eta_seconds)} left). This is an estimate."
        )

    def status_text(status):
        """Human text for a run's status."""
        return {
            "running": "Running",
            "finished": "Finished",
            "failed": "Failed",
            "interrupted": "Interrupted",
            "unknown": "Unknown (started on another machine)",
        }[status]

    def elapsed_seconds(run, last_activity):
        """Seconds the run has taken, from its records.

        Finished and failed runs run to their end. A running run counts up
        to now. An interrupted or unknown run has no end record, so it
        counts only to the last activity the run history saw; this keeps
        its throughput from falling while the dashboard is open.
        """
        now = datetime.now(UTC)
        if run.ended_at is not None and run.status in ("finished", "failed"):
            return max((run.ended_at - run.started_at).total_seconds(), 0.0)
        if run.status in ("interrupted", "unknown") and last_activity is not None:
            return max((last_activity - run.started_at).total_seconds(), 0.0)
        return max((now - run.started_at).total_seconds(), 0.0)

    def last_step_text(last_step):
        """Human text for the newest recorded stage of a run."""
        if last_step is None:
            return "none recorded yet."
        base = f"**{last_step['stage']}**"
        where = ", ".join(p for p in (last_step["receiver"], last_step["day"]) if p)
        if where:
            base += f" ({where})"
        seconds_ago = last_step["seconds_ago"]
        if seconds_ago < 60:
            ago = "just now"
        else:
            minutes = int(seconds_ago) // 60
            ago = f"{minutes} min ago" if minutes < 60 else f"{minutes // 60} h ago"
        return f"{base}, {ago}."

    def site_overview_rows(history, runs):
        """One row per site: its last run and that run's progress."""
        seen = set()
        rows = []
        for run in runs:
            if run.site in seen:
                continue
            seen.add(run.site)
            progress = history.progress(run.run_id)
            planned = sum(p.planned for p in progress)
            written = sum(p.written for p in progress)
            skipped = sum(p.skipped for p in progress)
            failed = sum(p.failed for p in progress)
            rows.append(
                {
                    "Site": run.site,
                    "Run": run.run_id,
                    "Status": status_text(run.status),
                    "Started (UTC)": run.started_at.strftime("%Y-%m-%d %H:%M"),
                    "Ended (UTC)": (
                        run.ended_at.strftime("%Y-%m-%d %H:%M") if run.ended_at else ""
                    ),
                    "Planned": planned,
                    "Written": written,
                    "Skipped": skipped,
                    "Failed": failed,
                    "Not yet done": planned - (written + skipped + failed),
                }
            )
        return rows

    def chart_data(run, days, timings, samples, store_sizes):
        """The data every chart shows, from the run history records only.

        Returns a dict of row lists, each a list of dicts, one per chart:
        ``stage``, ``day``, ``store``, ``resources``, ``disk`` and
        ``throughput``. A chart has no entry when the run history holds no
        records for it.
        """
        charts = {}

        # Time per stage: each stage's total and per-day median, by total.
        if timings:
            charts["stage"] = stage_stats(timings)

        # Time per day: the stage seconds of a data day, summed; a record
        # of a unit of days is split evenly over the days it names.
        if day_seconds := day_rows(timings):
            charts["day"] = day_seconds

        # Store size per day: the on-disk size of each store, measured in
        # the background; a "Total" row adds the stores of a day.
        if store_sizes:
            charts["store"] = store_rows(store_sizes)

        # CPU and memory over time, one row per sample and metric.
        resources = []
        for sample in samples:
            if sample.cpu_percent is not None:
                resources.append(
                    {
                        "Time": sample.sampled_at,
                        "Metric": "CPU (%)",
                        "Percent": sample.cpu_percent,
                    }
                )
            if sample.memory_percent is not None:
                resources.append(
                    {
                        "Time": sample.sampled_at,
                        "Metric": "Memory (%)",
                        "Percent": sample.memory_percent,
                    }
                )
        if resources:
            charts["resources"] = resources

        # Free disk over time, one row per sample and folder, in GB.
        disk = []
        for sample in samples:
            for folder, bytes_free in sample.free_disk.items():
                disk.append(
                    {
                        "Time": sample.sampled_at,
                        "Folder": folder,
                        "Free disk (GB)": bytes_free / 1e9,
                    }
                )
        if disk:
            charts["disk"] = disk

        # Throughput over time: the receiver-days finished, cumulative.
        finished_at = sorted(
            day.finished_at
            for day in days
            if day.result is not None and day.finished_at is not None
        )
        if finished_at:
            charts["throughput"] = [
                {
                    "Elapsed (h)": (at - run.started_at).total_seconds() / 3600,
                    "Receiver-days finished": count,
                }
                for count, at in enumerate(finished_at, start=1)
            ]

        return charts

    def build_run_view(run, progress, days, timings, problems, samples, store_sizes):
        """Everything the run page shows, computed from the run history only."""
        now = datetime.now(UTC)
        finished = [d for d in days if d.result is not None]
        pending = [d for d in days if d.result is None]
        activity = [d.finished_at for d in days if d.finished_at is not None]
        activity += [t.recorded_at for t in timings]
        last_activity = max(activity) if activity else None
        elapsed = elapsed_seconds(run, last_activity)
        hours = elapsed / 3600 if elapsed else 0.0

        eta_seconds = None
        if run.status == "running" and finished and hours > 0:
            mean_per_finished = elapsed / len(finished)
            if pending:
                eta_seconds = mean_per_finished * len(pending)

        days_per_hour = len(finished) / hours if hours else None
        bytes_total = sum(d.bytes_added or 0 for d in finished)
        bytes_per_hour = bytes_total / hours if hours else None

        last_step = None
        if timings:
            last = timings[-1]
            last_step = {
                "stage": last.stage,
                "receiver": last.receiver,
                "day": last.day,
                "seconds_ago": (now - last.recorded_at).total_seconds(),
            }

        progress_rows = [
            {
                "Receiver": p.receiver,
                "Planned": p.planned,
                "Written": p.written,
                "Skipped": p.skipped,
                "Failed": p.failed,
                "Not yet done": p.planned - (p.written + p.skipped + p.failed),
                "Bytes added": p.bytes_added,
            }
            for p in progress
        ]

        problem_rows = [
            {
                "Time (UTC)": problem.recorded_at.strftime("%Y-%m-%d %H:%M"),
                "Level": problem.level,
                "Message": problem.message,
                "Receiver": problem.receiver or "",
                "Day": problem.day or "",
            }
            for problem in problems
        ]

        return {
            "run": run,
            "progress_rows": progress_rows,
            "finished": len(finished),
            "pending": len(pending),
            "eta_seconds": eta_seconds,
            "days_per_hour": days_per_hour,
            "bytes_per_hour": bytes_per_hour,
            "last_step": last_step,
            "problem_rows": problem_rows,
            "charts": chart_data(run, days, timings, samples, store_sizes),
        }

    def chart_style(chart):
        """Make a chart follow the marimo theme: a transparent frame."""
        return chart.properties(background="transparent").configure_view(stroke=None)

    from canvodpy.cli.dashboards.charts import (
        chart_categories,
        chart_palette,
        day_rows,
        stage_stats,
        store_rows,
        time_bars,
        time_line,
    )

    def comparison_view(log_dir, scale_type):
        """The compare-by-label items, or a message when there is nothing.

        The grouping and the statistics live in
        :func:`canvodpy.cli.dashboards.comparison.build_comparison`; here
        the run history is opened and the result rendered.
        """
        import altair as alt

        from canvodpy.cli.dashboards.comparison import build_comparison
        from canvodpy.cli.dashboards.export import export_zip
        from canvodpy.run_history import (
            NetworkDriveError,
            RunHistory,
            RunHistoryError,
            RunHistoryVersionError,
        )

        def _charts(rows, labels):
            """One grouped bar chart: per stage, one bar per label side by
            side. Up to four labels get the colors of
            :func:`chart_categories`; more, such as a series of worker
            counts, get colors from dark to light in the sorted order of the
            labels."""
            scale = alt.Scale(range=chart_categories(len(labels)))
            rows, time_encoding = time_bars(
                "y", "Median (s)", "Median time (s)", rows, scale_type
            )
            return [
                mo.ui.altair_chart(
                    chart_style(
                        alt.Chart({"values": rows})  # type: ignore
                        .mark_bar()
                        .encode(
                            x=alt.X("Stage:N", axis=alt.Axis(title="Stage")),
                            xOffset=alt.XOffset("Label:N", sort="ascending"),
                            **time_encoding,
                            color=alt.Color(
                                "Label:N",
                                sort="ascending",
                                scale=scale,
                                legend=alt.Legend(orient="bottom", columns=4),
                            ),
                            tooltip=["Stage:N", "Label:N", "Median (s):Q"],
                        )
                        .properties(width="container")
                    )
                )
            ]

        intro = mo.md(
            "A run gets an optional `--label` when it starts "
            "(`canvodpy run --label <text>`). Runs with the same label are "
            "grouped and compared. Only **finished** runs are compared, and "
            "a run without a label is left out. Each group shows the median "
            "time per stage and in total, with the spread from the minimum "
            "to the maximum. A stage's time is summed over the run's "
            "receivers and days (across its worker processes); the **Total** "
            "is the run's wall time, so the stage times can add up to more "
            "than the total."
        )

        items = [mo.md("## Compare runs by label")]
        if log_dir is None:
            items.append(mo.md("_No log folder to compare._"))
            return items

        try:
            with RunHistory.open(log_dir, read_only=True) as history:
                comparison = build_comparison(history)
        except FileNotFoundError:
            items.append(mo.md("_No run has been recorded in this folder yet._"))
            return items
        except (NetworkDriveError, RunHistoryVersionError, RunHistoryError) as error:
            items.append(mo.md(f"_{error}_"))
            return items

        items.append(intro)
        if not comparison.group_rows:
            items.append(mo.md("_No finished labeled runs to compare yet._"))
            return items

        items.append(
            mo.ui.table(comparison.group_rows, selection=None, label="Run groups")
        )
        if comparison.any_differs:
            items.append(
                mo.callout(
                    mo.md(
                        "A group whose machine, workers, version or settings "
                        "differ is not a set of repetitions of the same run."
                    ),
                    kind="warn",
                )
            )
        labels = [row["Label"] for row in comparison.group_rows]
        items.append(mo.md("### Median time per stage"))
        items.extend(_charts(comparison.chart_rows, labels))
        items.append(
            mo.ui.table(
                comparison.stage_rows,
                selection=None,
                label="Timing per stage and in total",
            )
        )
        items.append(
            mo.download(
                data=lambda: export_zip(
                    log_dir,
                    comparison.run_ids,
                    {
                        "run_groups": (
                            "the Run groups table",
                            comparison.group_rows,
                        ),
                        "timing_per_stage": (
                            "the Timing per stage and in total table",
                            comparison.stage_rows,
                        ),
                        "median_time_per_stage": (
                            "the data of the Median time per stage chart",
                            comparison.chart_rows,
                        ),
                    },
                    title="canvodpy run dashboard: Compare runs by label",
                ),
                filename="canvodpy_compare_runs.zip",
                mimetype="application/zip",
                label="Download the data of this comparison",
            )
        )
        return items

    return (
        mo,
        format_duration,
        eta_text,
        status_text,
        site_overview_rows,
        last_step_text,
        build_run_view,
        chart_style,
        chart_palette,
        chart_categories,
        time_bars,
        time_line,
        comparison_view,
    )


@app.cell
def _(mo):
    from importlib.resources import files

    logos = files("canvodpy.cli.dashboards")
    bright_svg = logos.joinpath("canvodpy_logo_bright_mode.svg").read_text(
        encoding="utf-8"
    )
    dark_svg = logos.joinpath("canvodpy_logo_dark_mode.svg").read_text(encoding="utf-8")
    mo.hstack(
        [
            mo.Html(
                f'<div class="canvodpy-logo">'
                f'<div class="canvodpy-logo-bright">{bright_svg}</div>'
                f'<div class="canvodpy-logo-dark">{dark_svg}</div>'
                "</div>"
            ),
            mo.md("## Run Dashboard"),
        ],
        justify="start",
        align="center",
        gap=2,
    )


@app.cell
def _(mo):
    import os
    from pathlib import Path

    from canvod.config import load_config
    from canvod.config.models.logging import LogDirNotSetError

    def _resolve_log_dir():
        # Order: --logs-dir on the marimo command line (after `--`), then the
        # variable `canvodpy dashboard` / `canvodpy run --dashboard` set, then
        # the settings file.
        args = mo.cli_args()
        if args.get("logs-dir"):
            return Path(args["logs-dir"]).expanduser()
        env = os.environ.get("CANVODPY_PERF_LOG_DIR")
        if env:
            return Path(env).expanduser()
        return load_config().processing.logging.get_log_dir()

    log_dir = None
    log_dir_problem = None
    try:
        log_dir = _resolve_log_dir()
    except LogDirNotSetError:
        log_dir_problem = (
            "No log folder is set. Pass it on the command line with "
            "`--logs-dir <folder>` after `--`, or set "
            "`processing.logging.log_dir` in `canvod-settings.yaml`."
        )
    except Exception as error:
        log_dir_problem = (
            "Could not read the log folder from the settings file. Pass it with "
            f"`--logs-dir <folder>` after `--`. ({type(error).__name__}: {error})"
        )

    mo.md(f"**Log directory:** `{log_dir}`" if log_dir is not None else "")
    return log_dir, log_dir_problem


@app.cell
def _(mo):
    # Auto-refresh: re-runs the cells that read `refresh` on the chosen
    # interval, so the notebook follows a live run. A long interval suits a
    # multi-day run; the widget also has a manual refresh.
    refresh = mo.ui.refresh(
        options=["2s", "5s", "10s", "30s", "1m", "5m", "30m", "1h", "2h", "6h", "24h"],
        default_interval="10s",
    )
    refresh
    return (refresh,)


@app.cell
def _(mo):
    # The button that shuts the dashboard down; shown only when
    # `canvodpy run --dashboard` started it.
    shutdown_button = mo.ui.run_button(label="Shut the dashboard down", kind="danger")
    return (shutdown_button,)


@app.cell
def _(mo, refresh, shutdown_button):
    import os as _os

    from canvodpy.cli.dashboards.shutdown import run_going, shut_down

    _ = refresh  # notice when the run ends
    _going = run_going(_os.environ)
    if _going is None:
        _output = None  # started by `canvodpy dashboard`: stopped with Ctrl+C
    elif shutdown_button.value:
        shut_down()
        _output = mo.callout(
            mo.md("The dashboard is shutting down. You can close this tab."),
            kind="info",
        )
    elif _going:
        _output = mo.hstack(
            [
                mo.md(
                    "The run is still going. Shutting the dashboard down "
                    "does not stop the run."
                ),
                shutdown_button,
            ],
            justify="space-between",
            align="center",
        )
    else:
        _output = mo.callout(
            mo.hstack(
                [mo.md("**The run has finished.**"), shutdown_button],
                justify="space-between",
                align="center",
            ),
            kind="success",
        )
    _output
    return


@app.cell
def _(mo):
    # Linear or logarithmic time axes, for every chart that shows a
    # duration: the stage and day charts and the comparison.
    time_axis = mo.ui.radio(
        options=["linear", "log"], value="linear", label="Time axis", inline=True
    )
    return (time_axis,)


@app.cell
def _(log_dir, log_dir_problem, refresh, site_overview_rows):
    from canvodpy.run_history import (
        NetworkDriveError,
        RunHistory,
        RunHistoryError,
        RunHistoryVersionError,
    )

    _ = refresh  # re-read the run history on refresh

    runs = []
    overview = []
    problem = log_dir_problem

    if log_dir is not None:
        try:
            with RunHistory.open(log_dir, read_only=True) as history:
                runs = history.runs()
                overview = site_overview_rows(history, runs)
        except FileNotFoundError:
            problem = (
                f"No run has been recorded in `{log_dir}` yet. "
                "Run `canvodpy run ...` first."
            )
        except (NetworkDriveError, RunHistoryVersionError, RunHistoryError) as error:
            problem = str(error)

    return runs, overview, problem, RunHistory


@app.cell
def _(log_dir, mo, overview, problem, runs):
    if problem is not None:
        banner_items = [mo.callout(mo.md(problem), kind="warn")]
    elif runs:
        banner_items = [
            mo.md(
                f"**{len(runs)}** run(s), **{len(overview)}** site(s) in `{log_dir}`. "
                "Reads the run history, not the log files."
            )
        ]
    else:
        banner_items = [
            mo.callout(
                mo.md(f"No run has been recorded in `{log_dir}` yet."), kind="warn"
            )
        ]
    mo.vstack(banner_items)
    return


@app.cell
def _(mo, overview):
    if not overview:
        overview_items = [mo.md("_No runs to show yet._")]
    else:
        overview_items = [
            mo.md("## Site overview"),
            mo.ui.table(overview, selection=None, label="Sites"),
        ]
    mo.vstack(overview_items)
    return


@app.cell
def _(mo):
    chosen_get, chosen_set = mo.state(None)
    return (chosen_get, chosen_set)


@app.cell
def _(chosen_get, chosen_set, mo, runs):
    selected = None
    if runs:
        labels = {f"{run.site} · {run.run_id}": run.run_id for run in runs}
        value = chosen_get()
        if value not in labels.values():
            value = next(iter(labels))
        selected = mo.ui.dropdown(
            options=labels,
            value=value,
            label="Run",
            full_width=False,
            on_change=chosen_set,
        )
    selected


@app.cell
def _(RunHistory, build_run_view, log_dir, refresh, selected):
    _ = refresh  # re-read the selected run's detail on refresh

    chosen = selected.value if selected is not None else None

    run_view = None
    if chosen is not None and log_dir is not None:
        try:
            with RunHistory.open(log_dir, read_only=True) as rh:
                run = rh.run(chosen)
                progress = rh.progress(chosen)
                days = rh.receiver_days(chosen)
                timings = rh.stage_timings(chosen)
                problems = rh.problems(chosen)
                samples = rh.resource_samples(chosen)
                store_sizes = rh.store_sizes(chosen)
            run_view = build_run_view(
                run, progress, days, timings, problems, samples, store_sizes
            )
        except KeyError:
            run_view = None

    return (run_view,)


@app.cell
def _(mo, run_view, status_text):
    if run_view is None:
        header_items = [mo.md("_Select a run._")]
    else:
        run_record = run_view["run"]
        header_md = mo.md(
            f"## Run: {run_record.run_id}\n\n"
            f"**Site:** {run_record.site}  ·  **Status:** {status_text(run_record.status)}  ·  "
            f"**Label:** {run_record.label or 'none'}\n\n"
            f"**Started (UTC):** {run_record.started_at.strftime('%Y-%m-%d %H:%M')}  ·  "
            f"**Ended (UTC):** {run_record.ended_at.strftime('%Y-%m-%d %H:%M') if run_record.ended_at else 'running'}\n\n"
            f"**canvodpy:** {run_record.canvodpy_version}"
            + (f" ({run_record.commit})" if run_record.commit else "")
            + f"  ·  **Workers:** {run_record.workers or 'n/a'}"
        )
        # Folded by default: long, and rarely needed while a run goes.
        details = mo.accordion(
            {
                "Settings": mo.json(run_record.settings),
                "Machine": mo.json(run_record.machine),
            },
            multiple=True,
        )
        header_items = [header_md, details]
    mo.vstack(header_items)
    return


@app.cell
def _(log_dir, mo, run_view):
    from canvodpy.cli.dashboards.export import export_zip

    if run_view is None or log_dir is None:
        download_items = [mo.md("")]
    else:
        run_id = run_view["run"].run_id
        charts = run_view["charts"]
        tables = {
            "progress": ("the Progress table", run_view["progress_rows"]),
            "warnings_and_errors": (
                "the Warnings and errors table",
                run_view["problem_rows"],
            ),
            "time_per_stage": (
                "the data of the Time per stage chart (median and total)",
                charts.get("stage", []),
            ),
            "time_per_day": (
                "the data of the Time per day chart",
                charts.get("day", []),
            ),
            "store_size": (
                "the data of the Store size on disk chart",
                charts.get("store", []),
            ),
            "cpu_and_memory": (
                "the data of the CPU and memory chart",
                charts.get("resources", []),
            ),
            "free_disk": (
                "the data of the Free disk chart",
                charts.get("disk", []),
            ),
            "throughput_over_time": (
                "the data of the Throughput over time chart",
                charts.get("throughput", []),
            ),
        }
        download_items = [
            mo.download(
                data=lambda: export_zip(
                    log_dir,
                    [run_id],
                    tables,
                    title=f"canvodpy run dashboard: run {run_id}",
                ),
                filename=f"canvodpy_run_{run_id}.zip",
                mimetype="application/zip",
                label="Download the data of this run",
            )
        ]
    mo.vstack(download_items)
    return


@app.cell
def _(mo, run_view):
    if run_view is None:
        progress_items = [mo.md("")]
    else:
        progress_items = [
            mo.md(
                f"### Progress ({run_view['finished']} finished, "
                f"{run_view['pending']} not yet done)"
            ),
            mo.ui.table(
                run_view["progress_rows"], selection=None, label="Receiver-days"
            ),
        ]
    mo.vstack(progress_items)
    return


@app.cell
def _(eta_text, last_step_text, mo, run_view):
    if run_view is None:
        timing_items = [mo.md("")]
    else:
        dp_hour = run_view["days_per_hour"]
        bp_hour = run_view["bytes_per_hour"]
        if dp_hour is None or bp_hour is None:
            throughput_md = mo.md("**Throughput:** no receiver-day has finished yet.")
        else:
            suffix = (
                " (over the run so far)" if run_view["run"].status == "running" else ""
            )
            throughput_md = mo.md(
                f"**Throughput:** {dp_hour:.2f} receiver-days per hour, "
                f"{bp_hour / 1e6:.1f} MB per hour{suffix}"
            )
        timing_items = [
            mo.md(f"**Estimate:** {eta_text(run_view['eta_seconds'])}"),
            mo.md(f"**Last finished step:** {last_step_text(run_view['last_step'])}"),
            throughput_md,
        ]
    mo.vstack(timing_items)
    return


@app.cell
def _(mo, run_view):
    if run_view is None:
        problem_items = [mo.md("")]
    else:
        if run_view["problem_rows"]:
            body = mo.ui.table(
                run_view["problem_rows"], selection=None, label="Problems"
            )
        else:
            body = mo.md("_None recorded._")
        problem_items = [
            mo.md(f"### Warnings and errors ({len(run_view['problem_rows'])})"),
            body,
        ]
    mo.vstack(problem_items)
    return


@app.cell
def _(
    chart_categories,
    chart_palette,
    chart_style,
    mo,
    run_view,
    time_axis,
    time_bars,
    time_line,
):
    import altair as alt

    run_charts = run_view["charts"] if run_view is not None else {}
    chart_items = [mo.md("### Charts"), time_axis]
    # A data day on a date axis: the labels thin out to fit the width, so a
    # year of days stays readable. UTC, so a date never shifts by a day.
    date_axis = alt.X(
        "utcyearmonthdate(Date):T",
        axis=alt.Axis(title="Day", format="%Y-%m-%d", labelOverlap=True),
    )
    date_tooltip = alt.Tooltip(
        "utcyearmonthdate(Date):T", title="Date", format="%Y-%m-%d"
    )
    if not run_charts:
        chart_items.append(mo.md("_No chart data for this run yet._"))
    else:
        chart_series = chart_palette()

        if "stage" in run_charts:
            chart_items.append(
                mo.md(
                    "**Time per stage.** On the left, the **median** of a stage's "
                    "per-day seconds (Median per day); on the right, the "
                    "**total** seconds of each stage (Total). The median is over "
                    "the stage's per-day seconds (a day's seconds added up for "
                    "that stage; a stage that names no day takes the median of its "
                    "records; a unit of days is split evenly over its days). "
                    "Receivers run in parallel, so these are not wall time."
                )
            )
            stage_rows = run_charts["stage"]
            stage_order = [row["Stage"] for row in stage_rows]
            median_rows, median_time = time_bars(
                "x", "Median (s)", "Median per day (s)", stage_rows, time_axis.value
            )
            total_rows, total_time = time_bars(
                "x", "Total (s)", "Total (s)", stage_rows, time_axis.value
            )
            median_chart = chart_style(
                alt.Chart({"values": median_rows})  # type: ignore
                .mark_bar(color=chart_series[0])
                .encode(
                    y=alt.Y("Stage:N", sort=stage_order, axis=alt.Axis(title="Stage")),
                    **median_time,
                    tooltip=[
                        "Stage:N",
                        alt.Tooltip(
                            "Median (s):Q", title="Median per day (s)", format=".2f"
                        ),
                    ],
                )
            )
            total_chart = chart_style(
                alt.Chart({"values": total_rows})  # type: ignore
                .mark_bar(color=chart_series[0])
                .encode(
                    y=alt.Y("Stage:N", sort=stage_order, axis=alt.Axis(title="Stage")),
                    **total_time,
                    tooltip=[
                        "Stage:N",
                        alt.Tooltip("Total (s):Q", title="Total (s)", format=".1f"),
                    ],
                )
            )
            chart_items.append(mo.hstack([median_chart, total_chart]))

        if "day" in run_charts:
            chart_items.append(
                mo.md(
                    "**Time per day.** The stage seconds of a data day, added up; "
                    "a run that works in units of days splits a unit's record "
                    "evenly over its days. Receivers run in parallel, so this is "
                    "not wall time. A day's time is final only after its unit's "
                    "VOD phase: until then it still rises, since a unit's "
                    "writing record is split over its days when the unit "
                    "commits, and its VOD runs during the next unit."
                )
            )
            day_points, day_time = time_line(
                "y", "Seconds", "Time (s)", run_charts["day"], time_axis.value
            )
            chart_items.append(
                mo.ui.altair_chart(
                    chart_style(
                        alt.Chart({"values": day_points})  # type: ignore
                        .mark_line(point=True, color=chart_series[0])
                        .encode(
                            x=date_axis,
                            **day_time,
                            tooltip=[
                                alt.Tooltip("Day:N", title="Day (YYYYDOY)"),
                                date_tooltip,
                                alt.Tooltip("Seconds:Q", format=".1f"),
                            ],
                        )
                        .properties(width="container")
                    )
                )
            )

        if "store" in run_charts:
            chart_items.append(
                mo.md(
                    "**Store size on disk.** The on-disk size of each store, "
                    "measured in the background when the run finished a new data "
                    "day (never inside a stage or a commit; how long the walk took "
                    "is recorded too). The **Total** line adds the stores of a day."
                )
            )
            store_data = run_charts["store"]
            byte_values = [row["Size (bytes)"] for row in store_data]
            store_unit = "GB" if max(byte_values) >= 1e9 else "MB"
            store_scale = 1e9 if store_unit == "GB" else 1e6
            store_display = [
                {**row, "Size": row["Size (bytes)"] / store_scale} for row in store_data
            ]
            store_count = len({row["Store"] for row in store_data})
            chart_items.append(
                mo.ui.altair_chart(
                    chart_style(
                        alt.Chart({"values": store_display})  # type: ignore
                        .mark_line(point=True)
                        .encode(
                            x=date_axis,
                            y=alt.Y(
                                "Size:Q",
                                axis=alt.Axis(title=f"Store size ({store_unit})"),
                                scale=alt.Scale(zero=False),
                            ),
                            color=alt.Color("Store:N").scale(
                                range=chart_categories(store_count)
                            ),
                            tooltip=[
                                alt.Tooltip("Day:N", title="Day (YYYYDOY)"),
                                date_tooltip,
                                "Store:N",
                                alt.Tooltip(
                                    "Size:Q", title=f"Size ({store_unit})", format=".2f"
                                ),
                            ],
                        )
                        .properties(width="container")
                    )
                )
            )
        elif run_charts:
            chart_items.append(mo.md("_This run recorded no store sizes._"))

        if "resources" in run_charts:
            chart_items.append(
                mo.md("**CPU and memory.** Percent used, sampled during the run.")
            )
            chart_items.append(
                mo.ui.altair_chart(
                    chart_style(
                        alt.Chart({"values": run_charts["resources"]})  # type: ignore
                        .mark_line(point=True)
                        .encode(
                            x=alt.X("Time:T", axis=alt.Axis(title="Time (UTC)")),
                            y=alt.Y(
                                "Percent:Q", axis=alt.Axis(title="Percent used (%)")
                            ),
                            color=alt.Color("Metric:N").scale(
                                range=chart_categories(2)
                            ),
                            tooltip=[
                                alt.Tooltip(
                                    "Time:T",
                                    title="Time (UTC)",
                                    format="%Y-%m-%d %H:%M:%S",
                                ),
                                "Metric:N",
                                alt.Tooltip("Percent:Q", format=".1f"),
                            ],
                        )
                    )
                )
            )

        if "disk" in run_charts:
            chart_items.append(
                mo.md(
                    "**Free disk.** Free space of each folder, sampled during the "
                    "run. Folders on the same disk have the same free space, so "
                    "their lines lie on top of each other; hover for the folder."
                )
            )
            chart_items.append(
                mo.ui.altair_chart(
                    chart_style(
                        alt.Chart({"values": run_charts["disk"]})  # type: ignore
                        .mark_line(point=True)
                        .encode(
                            x=alt.X("Time:T", axis=alt.Axis(title="Time (UTC)")),
                            y=alt.Y(
                                "Free disk (GB):Q",
                                axis=alt.Axis(title="Free disk (GB)"),
                                scale=alt.Scale(zero=False),
                            ),
                            tooltip=[
                                "Folder:N",
                                alt.Tooltip(
                                    "Time:T",
                                    title="Time (UTC)",
                                    format="%Y-%m-%d %H:%M:%S",
                                ),
                                alt.Tooltip("Free disk (GB):Q", format=".1f"),
                            ],
                            color=alt.Color("Folder:N").scale(
                                range=chart_categories(
                                    len({row["Folder"] for row in run_charts["disk"]})
                                )
                            ),
                        )
                    )
                )
            )

        if "throughput" in run_charts:
            chart_items.append(
                mo.md(
                    "**Throughput over time.** Receiver-days finished, cumulative "
                    "from the run start."
                )
            )
            chart_items.append(
                mo.ui.altair_chart(
                    chart_style(
                        alt.Chart({"values": run_charts["throughput"]})  # type: ignore
                        .mark_line(point=True, color=chart_series[0])
                        .encode(
                            x=alt.X(
                                "Elapsed (h):Q",
                                axis=alt.Axis(title="Elapsed since start (h)"),
                            ),
                            y=alt.Y(
                                "Receiver-days finished:Q",
                                axis=alt.Axis(title="Receiver-days finished"),
                            ),
                            tooltip=[
                                alt.Tooltip("Elapsed (h):Q", format=".2f"),
                                "Receiver-days finished:Q",
                            ],
                        )
                    )
                )
            )

    mo.vstack(chart_items)
    return


@app.cell
def _(comparison_view, log_dir, mo, refresh, time_axis):
    _ = refresh  # re-read the comparison on refresh
    mo.vstack([time_axis, *comparison_view(log_dir, time_axis.value)])
    return


if __name__ == "__main__":
    app.run()
