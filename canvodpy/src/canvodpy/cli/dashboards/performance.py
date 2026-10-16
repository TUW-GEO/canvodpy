# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "canvodpy",
#     "marimo",
#     "altair",
# ]
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
        finish = datetime.now() + timedelta(seconds=eta_seconds)
        return (
            f"done about {finish.strftime('%H:%M')} "
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

    def elapsed_seconds(run):
        """Seconds the run has taken, from its records."""
        now = datetime.now(UTC)
        if run.ended_at is not None and run.status in ("finished", "failed"):
            return max((run.ended_at - run.started_at).total_seconds(), 0.0)
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
                    "Started": run.started_at.strftime("%Y-%m-%d %H:%M"),
                    "Ended": (
                        run.ended_at.strftime("%Y-%m-%d %H:%M") if run.ended_at else ""
                    ),
                    "Planned": planned,
                    "Written": written,
                    "Skipped": skipped,
                    "Failed": failed,
                    "Missing": planned - (written + skipped + failed),
                }
            )
        return rows

    def build_run_view(run, progress, days, timings, problems):
        """Everything the run page shows, computed from the run history only."""
        now = datetime.now(UTC)
        finished = [d for d in days if d.result is not None]
        pending = [d for d in days if d.result is None]
        elapsed = elapsed_seconds(run)
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
                "Missing": p.planned - (p.written + p.skipped + p.failed),
                "Bytes added": p.bytes_added,
            }
            for p in progress
        ]

        problem_rows = [
            {
                "Time": problem.recorded_at.strftime("%Y-%m-%d %H:%M"),
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
        }

    return (
        mo,
        format_duration,
        eta_text,
        status_text,
        site_overview_rows,
        last_step_text,
        build_run_view,
    )


@app.cell
def _(mo):
    import pathlib

    logo_dir = pathlib.Path(__file__).resolve().parent
    bright_svg = (logo_dir / "canvodpy_logo_bright_mode.svg").read_text()
    dark_svg = (logo_dir / "canvodpy_logo_dark_mode.svg").read_text()
    mo.md("## canvodpy — Run dashboard")
    mo.Html(
        f'<div class="canvodpy-logo">'
        f'<div class="canvodpy-logo-bright">{bright_svg}</div>'
        f'<div class="canvodpy-logo-dark">{dark_svg}</div>'
        "</div>"
    )
    return


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
def _(mo, runs):
    selected = None
    if runs:
        labels = {f"{run.site} · {run.run_id}": run.run_id for run in runs}
        selected = mo.ui.dropdown(
            options=labels, value=next(iter(labels)), label="Run", full_width=False
        )
    return (selected,)


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
            run_view = build_run_view(run, progress, days, timings, problems)
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
            f"**Started:** {run_record.started_at.strftime('%Y-%m-%d %H:%M')}  ·  "
            f"**Ended:** {run_record.ended_at.strftime('%Y-%m-%d %H:%M') if run_record.ended_at else 'running'}\n\n"
            f"**canvodpy:** {run_record.canvodpy_version}"
            + (f" ({run_record.commit})" if run_record.commit else "")
            + f"  ·  **Workers:** {run_record.workers or 'n/a'}"
        )
        settings_block = mo.vstack(
            [mo.md("**Settings**"), mo.json(run_record.settings)]
        )
        machine_block = mo.vstack([mo.md("**Machine**"), mo.json(run_record.machine)])
        header_items = [header_md, settings_block, machine_block]
    mo.vstack(header_items)
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


if __name__ == "__main__":
    app.run()
