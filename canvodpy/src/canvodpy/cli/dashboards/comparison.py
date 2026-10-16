"""The compare-by-label computation of the run dashboard.

The grouping and the statistics live here, outside the marimo notebook
(`performance.py`), so a test can call :func:`build_comparison` directly
instead of reading the exported HTML. The notebook opens the run history
and renders what :func:`build_comparison` returns.

The grouping and the statistics are plain Python over the
:class:`canvodpy.run_history.RunHistory` queries: no SQL here, and no
marimo.
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass
from typing import Any

from canvodpy.run_history import RunHistory


@dataclass(frozen=True)
class RunComparison:
    """The data of the compare-by-label view.

    ``group_rows``: one row per label, with ``Runs`` and the machine,
    workers, version and settings of the group (or ``"differs"`` when the
    group is not uniform).

    ``stage_rows``: one row per label and stage, and one ``"Total"`` row
    per label.

    ``chart_rows``: one row per label and stage, for the median bar chart.

    ``any_differs``: whether any group is not uniform, so the notebook
    can warn that such runs are not repetitions of the same thing.
    """

    group_rows: list[dict[str, Any]]
    stage_rows: list[dict[str, Any]]
    chart_rows: list[dict[str, Any]]
    any_differs: bool


def _json_key(value: Any) -> str:
    return json.dumps(value, sort_keys=True)


def _shared(values: list[Any], render: Any) -> Any:
    """The one shared value of a group, or ``"differs"`` when not uniform."""
    unique = {str(value) for value in values}
    if len(unique) == 1:
        return render(values[0])
    return "differs"


def build_comparison(history: RunHistory) -> RunComparison:
    """Group the finished runs by label and compute the per-stage statistics.

    A run without a label, or not finished, is left out. Per stage a
    run's time is the sum over its receivers and days (across its worker
    processes), and the median and the min-to-max spread are over the
    group's runs that recorded that stage. The ``"Total"`` row is the
    run's wall time (``ended_at - started_at``), not the sum of its stage
    seconds: the stages are recorded by the worker processes in parallel,
    so their sum overstates the time a run really took.
    """
    all_runs = history.runs()
    labels = sorted(
        {run.label for run in all_runs if run.status == "finished" and run.label}
    )

    group_rows: list[dict[str, Any]] = []
    stage_rows: list[dict[str, Any]] = []
    chart_rows: list[dict[str, Any]] = []
    any_differs = False

    for label in labels:
        group = [run for run in history.runs(label=label) if run.status == "finished"]
        group.sort(key=lambda run: run.run_id)

        machine = _shared([run.machine for run in group], _json_key)
        workers = _shared(
            [run.workers for run in group],
            lambda value: "n/a" if value is None else str(value),
        )
        version = _shared(
            [
                f"{run.canvodpy_version} ({run.commit})"
                if run.commit
                else run.canvodpy_version
                for run in group
            ],
            lambda value: value,
        )
        settings = _shared([run.settings for run in group], _json_key)
        group_differs = any(
            value == "differs" for value in (machine, workers, version, settings)
        )
        any_differs = any_differs or group_differs
        group_rows.append(
            {
                "Label": label,
                "Runs": len(group),
                "Machine": machine,
                "Workers": workers,
                "Version": version,
                "Settings": settings,
            }
        )

        # Per stage the sum over a run's receivers and days; the total is
        # the run's wall time.
        stage_seconds: dict[str, list[float]] = {}
        wall_times: list[float] = []
        for run in group:
            per_run: dict[str, float] = {}
            for timing in history.stage_timings(run.run_id):
                per_run[timing.stage] = per_run.get(timing.stage, 0.0) + (
                    timing.seconds or 0.0
                )
            for stage, seconds in per_run.items():
                stage_seconds.setdefault(stage, []).append(seconds)
            # A finished run always ended.
            ended = run.ended_at
            if ended is not None:
                wall_times.append((ended - run.started_at).total_seconds())

        for stage in sorted(stage_seconds):
            seconds = sorted(stage_seconds[stage])
            stage_rows.append(
                {
                    "Label": label,
                    "Stage": stage,
                    "Runs": len(seconds),
                    "Median (s)": round(statistics.median(seconds), 1),
                    "Min (s)": round(seconds[0], 1),
                    "Max (s)": round(seconds[-1], 1),
                }
            )
            chart_rows.append(
                {
                    "Label": label,
                    "Stage": stage,
                    "Median (s)": statistics.median(seconds),
                }
            )
        if wall_times:
            walls = sorted(wall_times)
            stage_rows.append(
                {
                    "Label": label,
                    "Stage": "Total",
                    "Runs": len(walls),
                    "Median (s)": round(statistics.median(walls), 1),
                    "Min (s)": round(walls[0], 1),
                    "Max (s)": round(walls[-1], 1),
                }
            )

    return RunComparison(group_rows, stage_rows, chart_rows, any_differs)
