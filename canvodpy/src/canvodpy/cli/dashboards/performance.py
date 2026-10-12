import marimo

__generated_with = "0.23.13"
app = marimo.App(
    width="medium",
    app_title="canvodpy: Performance Dashboard",
    css_file="canvod_nordic.css",
)


@app.cell
def _():
    import marimo as mo

    return (mo,)


@app.cell
def _(mo):
    mo.md(
        """
# canvodpy — Performance Dashboard

Reads `stage_timing` events from `machine/performance*.json` (see
`canvodpy.logging.stage_timer` / `docs/guides/diagnostics.md`).
Not full telemetry — this is a lightweight, always-on, file-based
view of how a pipeline run spent its time. Works while a run is
still in progress (partial data) or after it's finished.

**Site** is parsed from `run_id` (`{site}-{YYYYMMDD-HHMMSS}`, set by
`canvodpy run` and by `site.pipeline()`): multiple sites' logs in the
same directory show up as separate rows and can be filtered below.
Events logged outside a run carry no `run_id` and show up as
"(no run ID)".
**VOD model** comes from the `calculator` field emitted on
`vod_calc`/`vod_store` events — different `--vod-calculator` runs
are distinguishable the same way.
"""
    )
    return


@app.cell
def _(mo):
    import os
    from pathlib import Path

    def _default_log_dir() -> Path:
        # `canvodpy dashboard` and `canvodpy run --dashboard` always set it.
        env_dir = os.environ.get("CANVODPY_PERF_LOG_DIR")
        if env_dir:
            return Path(env_dir).expanduser()
        from canvod.config import load_config

        return load_config().processing.logging.get_log_dir()

    log_dir = _default_log_dir()
    machine_dir = log_dir / "machine"

    mo.md(f"**Log directory:** `{machine_dir}`")
    return (machine_dir,)


@app.cell
def _(mo):
    # Auto-refreshing timer: re-runs every cell that references `refresh`
    # on the chosen interval, so the dashboard tracks a live run without
    # a manual click. The widget also exposes a manual refresh action.
    # Long options (30m-24h) matter for the "runs may take days or run
    # forever" case -- a dashboard left open
    # against an unattended multi-day backfill shouldn't have to poll
    # every few seconds to eventually catch up.
    refresh = mo.ui.refresh(
        options=["2s", "5s", "10s", "30s", "1m", "5m", "30m", "1h", "2h", "6h", "24h"],
        default_interval="10s",
    )
    refresh
    return (refresh,)


@app.cell
def _(machine_dir, mo, refresh):
    import json

    import polars as pl

    _ = refresh  # re-run this cell when the button is clicked

    _STAGE_SCHEMA = {
        "run_id": pl.Utf8,
        "stage": pl.Utf8,
        "receiver": pl.Utf8,
        "date_key": pl.Utf8,
        "duration_seconds": pl.Float64,
        "status": pl.Utf8,
        "timestamp": pl.Utf8,
        # VOD-only fields: populated on "vod_calc"/"vod_store" events,
        # null for the RINEX-side reading/validating/augmenting/writing
        # events (see cli/run.py and orchestrator/processor.py).
        "calculator": pl.Utf8,
        "analysis": pl.Utf8,
    }

    def _read_stage_events(paths: list) -> pl.DataFrame:
        """Read stage_timing events from one or more performance*.json files.

        Line-by-line json.loads rather than pl.read_ndjson: a file being
        actively appended to by a live run may have an incomplete trailing
        line at read time, which would otherwise fail the whole read.
        """
        rows = []
        for path in paths:
            try:
                text = path.read_text()
            except OSError:
                continue
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue  # partial trailing line from a live writer
                if event.get("event") != "stage_timing":
                    continue
                rows.append({key: event.get(key) for key in _STAGE_SCHEMA})

        if not rows:
            return pl.DataFrame(schema=_STAGE_SCHEMA)
        return pl.DataFrame(rows, schema=_STAGE_SCHEMA)

    # `performance*.json*` (trailing `*`), not `performance*.json`: the perf
    # log uses a size-triggered RotatingFileHandler (50MB, backupCount now
    # 60 -- was 10; see logging_config.py), so a run of any real length
    # rotates the main process's file to `performance.json.1`, `.2`, ...
    # -- names that don't end in `.json` and were silently invisible to the
    # old pattern. On a ~15h overnight run, `performance.json.1` alone held
    # 82% of the main process's *total* logged lines (150,842/184,763) but
    # only ~0.4% of the `stage_timing` events this cell reads specifically
    # (most `stage_timing` events come from per-PID worker files, which
    # never rotated this run) -- still a real bug, just smaller in this
    # dimension than the raw file sizes suggest (confirmed against a real
    # backfill's logs, 2026-07-15).
    perf_files = sorted(machine_dir.glob("performance*.json*"))
    events = _read_stage_events(perf_files)

    # `site` is not logged directly -- it's the prefix of run_id
    # (`{site}-{YYYYMMDD-HHMMSS}`, see cli/run.py). `unit` unifies the
    # RINEX-side "receiver" and the VOD-side "analysis" fields into one
    # column so per-stage grouping/coloring works across both without
    # conflating them. Applied unconditionally (incl. on the empty
    # DataFrame) so every downstream cell can rely on both columns existing.
    events = events.with_columns(
        pl.col("run_id")
        .str.extract(r"^(.*)-\d{8}-\d{6}$", 1)
        .fill_null(pl.col("run_id"))
        .fill_null("(no run ID)")
        .alias("site"),
        pl.coalesce([pl.col("receiver"), pl.col("analysis")]).alias("unit"),
    )

    if events.is_empty():
        summary = mo.callout(
            mo.md(
                f"No `stage_timing` events found yet under `{machine_dir}`. "
                "Run `canvodpy run ...` first, or wait for the next "
                "auto-refresh once one has started writing."
            ),
            kind="warn",
        )
    else:
        summary = mo.md(
            f"**{len(events)}** stage_timing events across "
            f"**{events['run_id'].n_unique()}** run(s), "
            f"**{events['site'].n_unique()}** site(s), "
            f"**{events['stage'].n_unique()}** distinct stages, "
            f"**{events['calculator'].n_unique()}** VOD model(s)."
        )
    summary
    return events, pl


@app.cell
def _(events, mo):
    _sites = sorted(events["site"].drop_nulls().unique().to_list())
    _models = sorted(events["calculator"].drop_nulls().unique().to_list())

    site_filter = mo.ui.multiselect(
        options=_sites, value=_sites, label="Site(s)", full_width=False
    )
    model_filter = mo.ui.multiselect(
        options=_models,
        value=_models,
        label="VOD model(s): n/a rows (RINEX stages) always included",
        full_width=False,
    )
    mo.hstack([site_filter, model_filter], justify="start", gap=2)
    return model_filter, site_filter


@app.cell
def _(events, model_filter, pl, site_filter):
    if events.is_empty():
        filtered = events
    else:
        filtered = events.filter(
            pl.col("site").is_in(site_filter.value)
            & (
                pl.col("calculator").is_in(model_filter.value)
                | pl.col("calculator").is_null()
            )
        )
    return (filtered,)


@app.cell
def _(filtered, mo, pl):
    mo.md(
        """
## Stage duration over time

One panel per stage — trace each receiver or VOD analysis (color) across
days to spot regressions per stage, not just totals. Rows facet by site
when more than one site is present.
"""
    )

    if filtered.is_empty():
        trend_chart = mo.md("_No data yet._")
    else:
        trend_data = (
            filtered.filter(
                pl.col("date_key").is_not_null() & pl.col("unit").is_not_null()
            )
            .group_by(["site", "stage", "unit", "date_key"])
            .agg(pl.col("duration_seconds").sum().alias("duration_seconds"))
            .sort("date_key")
        )
        if trend_data.is_empty():
            trend_chart = mo.md(
                "_No stage_timing events carry receiver/analysis context yet._"
            )
        else:
            import altair as _alt

            _n_sites = trend_data["site"].n_unique()
            _base = (
                _alt.Chart(trend_data.to_pandas())
                .mark_line(point=True)
                .encode(  # ty: ignore[unresolved-attribute] -- altair's stubs lose the concrete Chart type across this chain
                    x=_alt.X("date_key:N", title="Day (YYYYDOY)"),
                    y=_alt.Y("duration_seconds:Q", title="Duration (s)"),
                    color=_alt.Color("unit:N", title="Receiver / analysis"),
                    tooltip=["site", "stage", "unit", "date_key", "duration_seconds"],
                )
                .properties(width=220, height=180)
            )
            _facet_kwargs = {"column": _alt.Column("stage:N", title="Stage")}
            if _n_sites > 1:
                _facet_kwargs["row"] = _alt.Row("site:N", title="Site")
            # Faceted charts aren't wrapped in mo.ui.altair_chart (selection
            # bindings don't apply cleanly to facets) -- rendered directly.
            trend_chart = _base.facet(**_facet_kwargs).resolve_scale(y="independent")

    trend_chart
    return


@app.cell
def _(filtered, mo, pl):
    mo.md("## Total elapsed time per day")

    if filtered.is_empty():
        agg_chart = mo.md("_No data yet._")
    else:
        by_unit = (
            filtered.filter(
                pl.col("date_key").is_not_null() & pl.col("unit").is_not_null()
            )
            .group_by(["site", "unit", "date_key"])
            .agg(pl.col("duration_seconds").sum().alias("total_seconds"))
            .sort(["date_key", "site", "unit"])
        )
        if by_unit.is_empty():
            agg_chart = mo.md("_No receiver/analysis-tagged events yet._")
        else:
            import altair as _alt

            _n_sites = by_unit["site"].n_unique()
            _base = (
                _alt.Chart(by_unit.to_pandas())
                .mark_bar()
                .encode(  # ty: ignore[unresolved-attribute] -- altair's stubs lose the concrete Chart type across this chain
                    x=_alt.X("date_key:N", title="Day (YYYYDOY)"),
                    y=_alt.Y("total_seconds:Q", title="Total time (s)"),
                    color=_alt.Color("unit:N", title="Receiver / analysis"),
                    tooltip=["site", "unit", "date_key", "total_seconds"],
                )
                .properties(width=650, height=300)
            )
            if _n_sites > 1:
                agg_chart = _base.facet(row=_alt.Row("site:N", title="Site"))
            else:
                agg_chart = mo.ui.altair_chart(_base)

    agg_chart
    return


@app.cell
def _(filtered, mo, pl):
    mo.md("## Exact figures: duration (s) per site × stage × receiver/analysis")

    if filtered.is_empty():
        stats_table = mo.md("_No data yet._")
    else:
        stats = (
            filtered.filter(pl.col("unit").is_not_null())
            .group_by(["site", "stage", "unit"])
            .agg(
                pl.col("duration_seconds").mean().round(2).alias("mean_s"),
                pl.col("duration_seconds").median().round(2).alias("median_s"),
                pl.col("duration_seconds").max().round(2).alias("max_s"),
                pl.col("duration_seconds").sum().round(1).alias("total_s"),
                pl.len().alias("n"),
            )
            .sort(["site", "stage", "unit"])
        )
        stats_table = mo.ui.table(stats.to_pandas(), selection=None)

    stats_table
    return


if __name__ == "__main__":
    app.run()
