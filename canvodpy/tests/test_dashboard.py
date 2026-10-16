"""The dashboard notebook: a smoke export with runs and without runs.

``marimo export html`` runs every cell of the notebook. If any cell
raises, marimo still writes the HTML but exits 1 and prints
``MarimoExceptionRaisedError``; so this test fails on a cell error by
asserting the exporter exits 0.
"""

import os
import statistics
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from canvodpy.cli.dashboards.comparison import build_comparison
from canvodpy.run_history import RunHistory

import canvodpy


def _seed(log_dir: Path) -> dict[str, list[float]]:
    """Build a small run history through the public API only (no SQL here).

    Five runs: one finished and one failed without a label, and three
    finished with the label "benchmark 2" (one of them on a different
    machine with different workers and settings). Receiver-days with each
    result, stage timings, resource samples, and one warning and one
    error.

    Returns the wall time (seconds) of each finished run of the labeled
    group, by label, so the comparison test can compute the expected
    median and spread. The start and end times are passed explicitly (the
    seeded run IDs name the minute, and the newest run stays the default
    in the picker).
    """
    # The finished runs of the labeled group: run ID, start, end. The end
    # minus the start is the wall time the test checks.
    with RunHistory.open(log_dir) as history:
        rid1 = "fangorn-20261014-100000"
        history.start_run(
            rid1,
            site="fangorn",
            settings={"processing": {"n_max_threads": 4}},
            canvodpy_version="1.0.0",
            commit="abc1234",
            machine={"cpu": "test CPU", "cores": 8},
            workers=4,
            started_at=datetime(2026, 10, 14, 10, 0, 0, tzinfo=UTC),
        )
        history.plan_receiver_days(
            rid1,
            [
                ("canopy_01", "2025001"),
                ("canopy_01", "2025002"),
                ("reference_01", "2025001"),
            ],
        )
        history.finish_receiver_day(
            rid1, "canopy_01", "2025001", "written", bytes_added=1000
        )
        history.finish_receiver_day(
            rid1, "canopy_01", "2025002", "written", bytes_added=1200
        )
        history.finish_receiver_day(rid1, "reference_01", "2025001", "skipped")
        history.record_stage(rid1, "reading", 1.5, receiver="canopy_01", day="2025001")
        history.record_stage(rid1, "reading", 1.7, receiver="canopy_01", day="2025002")
        history.record_stage(rid1, "writing", 3.2, receiver="canopy_01", day="2025001")
        history.record_resources(
            rid1, cpu_percent=50.0, memory_percent=20.0, free_disk={"/stores": 10}
        )
        history.record_resources(
            rid1, cpu_percent=70.0, memory_percent=25.0, free_disk={"/stores": 9}
        )
        history.record_problem(
            rid1,
            "warning",
            "3 files not processed",
            receiver="canopy_01",
            day="2025001",
        )
        history.end_run(
            rid1, "finished", ended_at=datetime(2026, 10, 14, 10, 0, 10, tzinfo=UTC)
        )

        rid2 = "fangorn-20261014-120000"
        history.start_run(
            rid2,
            site="fangorn",
            settings={"processing": {"n_max_threads": 2}},
            canvodpy_version="1.0.0",
            commit="abc1234",
            machine={"cpu": "test CPU", "cores": 8},
            workers=2,
            started_at=datetime(2026, 10, 14, 12, 0, 0, tzinfo=UTC),
        )
        history.plan_receiver_days(
            rid2, [("canopy_01", "2025001"), ("reference_01", "2025001")]
        )
        history.finish_receiver_day(rid2, "canopy_01", "2025001", "failed")
        history.record_problem(
            rid2, "error", "no valid observations", receiver="canopy_01", day="2025001"
        )
        history.end_run(
            rid2,
            "failed",
            error="ValueError: no valid observations",
            ended_at=datetime(2026, 10, 14, 12, 0, 3, tzinfo=UTC),
        )

        rid3 = "isengard-20261014-140000"
        history.start_run(
            rid3,
            site="isengard",
            settings={"processing": {"n_max_threads": 8}},
            canvodpy_version="1.0.0",
            commit="abc1234",
            machine={"cpu": "test CPU", "cores": 16},
            workers=8,
            label="benchmark 2",
            started_at=datetime(2026, 10, 14, 14, 0, 0, tzinfo=UTC),
        )
        history.plan_receiver_days(
            rid3,
            [
                ("canopy_01", "2025001"),
                ("canopy_01", "2025002"),
                ("reference_01", "2025001"),
                ("reference_01", "2025002"),
            ],
        )
        history.finish_receiver_day(
            rid3, "canopy_01", "2025001", "written", bytes_added=1500
        )
        history.finish_receiver_day(
            rid3, "reference_01", "2025001", "written", bytes_added=0
        )
        history.record_stage(rid3, "reading", 2.0, receiver="canopy_01", day="2025001")
        history.record_stage(rid3, "reading", 2.5, receiver="canopy_01", day="2025002")
        history.record_stage(rid3, "writing", 4.0, receiver="canopy_01", day="2025001")
        history.record_stage(rid3, "writing", 4.5, receiver="canopy_01", day="2025002")
        history.record_resources(
            rid3, cpu_percent=40.0, memory_percent=30.0, free_disk={"/stores": 20}
        )
        history.record_resources(
            rid3, cpu_percent=60.0, memory_percent=35.0, free_disk={"/stores": 19}
        )
        history.end_run(
            rid3, "finished", ended_at=datetime(2026, 10, 14, 14, 0, 32, tzinfo=UTC)
        )

        # Two more runs with the same label, so the comparison has a group
        # of three. rid4 looks like rid3; rid5 runs on another machine with
        # more workers, so the group's machine, workers and settings differ.
        rid4 = "isengard-20261014-133000"
        history.start_run(
            rid4,
            site="isengard",
            settings={"processing": {"n_max_threads": 8}},
            canvodpy_version="1.0.0",
            commit="abc1234",
            machine={"cpu": "test CPU", "cores": 16},
            workers=8,
            label="benchmark 2",
            started_at=datetime(2026, 10, 14, 13, 30, 0, tzinfo=UTC),
        )
        history.plan_receiver_days(
            rid4, [("canopy_01", "2025001"), ("reference_01", "2025001")]
        )
        history.finish_receiver_day(
            rid4, "canopy_01", "2025001", "written", bytes_added=1300
        )
        history.record_stage(rid4, "reading", 1.6, receiver="canopy_01", day="2025001")
        history.record_stage(rid4, "writing", 3.0, receiver="canopy_01", day="2025001")
        history.end_run(
            rid4, "finished", ended_at=datetime(2026, 10, 14, 13, 30, 6, tzinfo=UTC)
        )

        rid5 = "isengard-20261014-123000"
        history.start_run(
            rid5,
            site="isengard",
            settings={"processing": {"n_max_threads": 16}},
            canvodpy_version="1.0.0",
            commit="abc1234",
            machine={"cpu": "other CPU", "cores": 32},
            workers=16,
            label="benchmark 2",
            started_at=datetime(2026, 10, 14, 12, 30, 0, tzinfo=UTC),
        )
        history.plan_receiver_days(
            rid5, [("canopy_01", "2025001"), ("reference_01", "2025001")]
        )
        history.finish_receiver_day(
            rid5, "canopy_01", "2025001", "written", bytes_added=1800
        )
        history.record_stage(rid5, "reading", 2.4, receiver="canopy_01", day="2025001")
        history.record_stage(rid5, "writing", 3.6, receiver="canopy_01", day="2025001")
        history.end_run(
            rid5, "finished", ended_at=datetime(2026, 10, 14, 12, 30, 9, tzinfo=UTC)
        )

    # Wall time of each finished run of the labeled group (end minus start).
    return {"benchmark 2": [32.0, 6.0, 9.0]}


def _export(
    log_dir: Path, app_dir: Path, *, via_cli_arg: bool = False
) -> subprocess.CompletedProcess:
    import shutil

    # Run on a copy of the notebook so marimo's session state never lands in
    # the repository. The notebook reads its style sheet next to the notebook
    # and the logos from the installed canvodpy package, so only the notebook
    # and the style sheet need copying.
    source = Path(canvodpy.__file__).parent / "cli" / "dashboards"
    for name in ("performance.py", "canvod_nordic.css"):
        shutil.copy(source / name, app_dir / name)

    out = app_dir / "dashboard_out.html"
    env = {**os.environ}
    cmd = [
        sys.executable,
        "-m",
        "marimo",
        "export",
        "html",
        str(app_dir / "performance.py"),
        "-o",
        str(out),
        "--no-sandbox",
    ]
    if via_cli_arg:
        # No environment variable: the log folder comes from --logs-dir after
        # `--`, the first of the three sources the notebook checks.
        cmd += ["--", "--logs-dir", str(log_dir)]
    else:
        env["CANVODPY_PERF_LOG_DIR"] = str(log_dir)
    return subprocess.run(
        cmd,
        cwd=app_dir,
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )


def test_dashboard_exports_with_run_history(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    _seed(log_dir)
    result = _export(log_dir, app_dir)
    assert result.returncode == 0, result.stderr + result.stdout


def test_dashboard_exports_without_run_history(tmp_path: Path) -> None:
    # An empty log folder: the notebook shows a plain message, no error.
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    result = _export(log_dir, app_dir)
    assert result.returncode == 0, result.stderr + result.stdout


def test_dashboard_export_via_cli_logs_dir(tmp_path: Path) -> None:
    # The log folder comes from `-- --logs-dir <folder>`, the first of the
    # three sources the notebook checks (CLI arg, then environment, then the
    # settings file). The notebook must not read the environment here.
    log_dir = tmp_path / "logs"
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    _seed(log_dir)
    result = _export(log_dir, app_dir, via_cli_arg=True)
    assert result.returncode == 0, result.stderr + result.stdout


def test_dashboard_compare_runs(tmp_path: Path) -> None:
    # The comparison, checked on the data, not the export. The seeded group
    # "benchmark 2" has three finished runs on two machines, so its machine,
    # workers and settings differ; the Total row is the runs' wall time
    # (ended minus started), not the sum of the stage seconds.
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    walls = _seed(log_dir)
    with RunHistory.open(log_dir, read_only=True) as history:
        comparison = build_comparison(history)

    group = next(row for row in comparison.group_rows if row["Label"] == "benchmark 2")
    assert group["Runs"] == 3
    assert group["Machine"] == "differs"
    assert group["Workers"] == "differs"
    assert group["Version"] == "1.0.0 (abc1234)"
    assert group["Settings"] == "differs"
    assert comparison.any_differs

    # A stage row is the sum of that stage's seconds over the run's
    # receivers and days, and the median is over the group's runs that
    # recorded it.
    reading = next(
        row
        for row in comparison.stage_rows
        if row["Label"] == "benchmark 2" and row["Stage"] == "reading"
    )
    assert reading["Runs"] == 3
    assert reading["Min (s)"] == 1.6
    assert reading["Median (s)"] == 2.4
    assert reading["Max (s)"] == 4.5

    # The Total row is the wall time of the seeded runs (not the ~13 s of
    # their stage seconds): the median and the spread are of the runs' end
    # minus start.
    total = next(
        row
        for row in comparison.stage_rows
        if row["Label"] == "benchmark 2" and row["Stage"] == "Total"
    )
    expected = sorted(walls["benchmark 2"])
    assert total["Runs"] == 3
    assert total["Min (s)"] == round(expected[0], 1)
    assert total["Median (s)"] == round(statistics.median(expected), 1)
    assert total["Max (s)"] == round(expected[-1], 1)
