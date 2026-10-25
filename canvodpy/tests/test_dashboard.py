"""The dashboard notebook: a smoke export with runs and without runs.

``marimo export html`` runs every cell of the notebook. If any cell
raises, marimo still writes the HTML but exits 1 and prints
``MarimoExceptionRaisedError``; so this test fails on a cell error by
asserting the exporter exits 0.
"""

import importlib.util
import io
import json
import os
import re
import shutil
import sqlite3
import statistics
import subprocess
import sys
import zipfile
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

import psutil
import pytest
from canvodpy.cli.dashboards.charts import (
    chart_categories,
    chart_palette,
    day_key,
    day_rows,
    split_days,
    stage_bars,
    stage_stats,
    store_rows,
    time_bars,
    time_line,
)
from canvodpy.cli.dashboards.comparison import build_comparison
from canvodpy.cli.dashboards.export import export_zip
from canvodpy.cli.dashboards.shutdown import RUN_VARIABLE, run_marker
from canvodpy.run_history import RunHistory, StageTiming, StoreSize

import canvodpy
from canvod.utils import testing


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
        # The on-disk size of the stores, measured by the background thread
        # against the data days the run had finished.
        history.record_store_size(
            rid1, "GNSS store", day="2025001", bytes=2_000_000_000, walk_seconds=0.01
        )
        history.record_store_size(
            rid1, "VOD store", day="2025001", bytes=800_000_000, walk_seconds=0.02
        )
        history.record_store_size(
            rid1, "GNSS store", day="2025002", bytes=2_400_000_000, walk_seconds=0.01
        )
        history.record_store_size(
            rid1, "VOD store", day="2025002", bytes=900_000_000, walk_seconds=0.03
        )
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


def _cell_outputs(log_dir: Path, monkeypatch, run_marker: str | None) -> str:
    """The notebook's cell outputs as HTML, without its source code."""
    monkeypatch.setenv("CANVODPY_PERF_LOG_DIR", str(log_dir))
    if run_marker is None:
        monkeypatch.delenv(RUN_VARIABLE, raising=False)
    else:
        monkeypatch.setenv(RUN_VARIABLE, run_marker)
    notebook = Path(canvodpy.__file__).parent / "cli" / "dashboards" / "performance.py"
    spec = importlib.util.spec_from_file_location("performance_notebook", notebook)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    outputs, _ = module.app.run()
    return "\n".join(getattr(output, "text", "") for output in outputs)


def _ended_run_marker() -> str:
    """The marker of a run that has ended."""
    run = subprocess.Popen([sys.executable, "-c", "pass"])
    marker = f"{run.pid} {psutil.Process(run.pid).create_time()!r}"
    run.wait()
    return marker


def test_dashboard_offers_the_shutdown_after_the_run(
    tmp_path: Path, monkeypatch
) -> None:
    outputs = _cell_outputs(tmp_path, monkeypatch, _ended_run_marker())

    assert "The run has finished." in outputs
    assert "Shut the dashboard down" in outputs


def test_dashboard_offers_the_shutdown_during_the_run(
    tmp_path: Path, monkeypatch
) -> None:
    outputs = _cell_outputs(tmp_path, monkeypatch, run_marker())

    assert "The run is still going." in outputs
    assert "Shut the dashboard down" in outputs


def test_dashboard_without_a_run_has_no_shutdown(tmp_path: Path, monkeypatch) -> None:
    # Started by `canvodpy dashboard`: it stops with Ctrl+C in its terminal.
    outputs = _cell_outputs(tmp_path, monkeypatch, None)

    assert "Shut the dashboard down" not in outputs


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


def test_dashboard_download_one_run(tmp_path: Path) -> None:
    # The run page's zip: the README, one CSV per table with rows, and a run
    # history that holds every record of that run and nothing of the others,
    # which opens like a log folder.
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    _seed(log_dir)
    rid = "fangorn-20261014-100000"
    rows = [{"Stage": "reading", "Seconds": 3.2}, {"Stage": "writing", "Seconds": 3.2}]
    data = export_zip(
        log_dir,
        [rid],
        {
            "time_per_stage": ("the Time per stage chart", rows),
            "free_disk": ("the Free disk chart", []),
        },
        title="test",
    )

    unzipped = tmp_path / "unzipped"
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        assert sorted(zf.namelist()) == [
            "README.txt",
            "run_history.sqlite",
            "time_per_stage.csv",
        ]
        zf.extractall(unzipped)

    assert (unzipped / "time_per_stage.csv").read_text().splitlines() == [
        "Stage,Seconds",
        "reading,3.2",
        "writing,3.2",
    ]
    readme = (unzipped / "README.txt").read_text()
    assert rid in readme
    assert canvodpy.__version__ in readme

    with (
        RunHistory.open(log_dir, read_only=True) as original,
        RunHistory.open(unzipped, read_only=True) as copy,
    ):
        assert [run.run_id for run in copy.runs()] == [rid]
        assert copy.run(rid) == original.run(rid)
        assert copy.receiver_days(rid) == original.receiver_days(rid)
        assert copy.stage_timings(rid) == original.stage_timings(rid)
        assert copy.resource_samples(rid) == original.resource_samples(rid)
        assert copy.problems(rid) == original.problems(rid)
        assert copy.store_sizes(rid) == original.store_sizes(rid)


def test_dashboard_download_comparison(tmp_path: Path) -> None:
    # The comparison's zip holds the run history of the compared runs only:
    # the finished runs with a label.
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    _seed(log_dir)
    with RunHistory.open(log_dir, read_only=True) as history:
        comparison = build_comparison(history)
    assert sorted(comparison.run_ids) == [
        "isengard-20261014-123000",
        "isengard-20261014-133000",
        "isengard-20261014-140000",
    ]
    data = export_zip(
        log_dir,
        comparison.run_ids,
        {"timing_per_stage": ("the timing table", comparison.stage_rows)},
        title="test",
    )
    unzipped = tmp_path / "unzipped"
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        zf.extractall(unzipped)
    with RunHistory.open(unzipped, read_only=True) as copy:
        assert sorted(run.run_id for run in copy.runs()) == sorted(comparison.run_ids)


# The anonymized example run history in the test data: nine finished runs
# of one site, seven days of two receivers with 1 to 126 workers, labeled
# pilot-w001 ... pilot-w126 and pilot-warmup. The demo notebook shows it.
EXAMPLE = (
    Path(__file__).resolve().parents[2]
    / "packages/canvod-readers/tests/test_data/valid/run_history"
)
needs_example = pytest.mark.skipif(
    not (EXAMPLE / "run_history.sqlite").exists(),
    reason="the test data has no example run history",
)


def _example_copy(tmp_path: Path) -> Path:
    """A copy of the example log folder, so no test writes to the test data."""
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    shutil.copy(EXAMPLE / "run_history.sqlite", log_dir / "run_history.sqlite")
    return log_dir


@needs_example
def test_example_history_names_no_person_machine_or_place() -> None:
    # Every text value of every table: no home folder, no e-mail but the
    # persona's; the runs carry the persona, its site and the example machine.
    path = EXAMPLE / "run_history.sqlite"
    spec = importlib.util.spec_from_file_location(
        "anonymize_run_history",
        Path(__file__).resolve().parents[2] / "scripts/anonymize_run_history.py",
    )
    anonymizer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(anonymizer)
    with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as db:
        tables = [
            row[0]
            for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        ]
        texts = [
            value
            for table in tables
            for row in db.execute(f"SELECT * FROM {table}")
            for value in row
            if isinstance(value, str)
        ]
        runs = db.execute("SELECT site, host, settings, machine FROM runs").fetchall()
        file_index = db.execute("SELECT count(*) FROM file_index").fetchone()[0]

    joined = "\n".join(texts)
    assert not re.search(r"/(home|Users)/", joined)
    emails = set(re.findall(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", joined))
    assert emails <= {testing.PERSON_EMAIL}
    assert file_index == 0
    for site, host, settings, machine in runs:
        assert site == testing.SITE_KEY
        assert host == "example-host"
        metadata = json.loads(settings)["processing"]["metadata"]
        assert metadata["author"] == testing.PERSON_NAME
        assert metadata["orcid"] == testing.PERSON_ORCID
        assert json.loads(settings)["processing"]["references"]["funding"] == []
        site_settings = json.loads(settings)["sites"]["sites"][testing.SITE_KEY]
        assert site_settings["latitude"] == testing.LATITUDE
        machine = json.loads(machine)
        for key, value in anonymizer.EXAMPLE_MACHINE.items():
            assert machine[key] == value, key
        for disk in machine["disks"].values():
            assert disk["total"] == anonymizer.EXAMPLE_DISK_TOTAL
            assert disk["filesystem"] == anonymizer.EXAMPLE_FILESYSTEM


@needs_example
def test_dashboard_exports_the_example_history(tmp_path: Path) -> None:
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    result = _export(_example_copy(tmp_path), app_dir)
    assert result.returncode == 0, result.stderr + result.stdout


@needs_example
def test_example_comparison_has_one_group_per_worker_count(tmp_path: Path) -> None:
    with RunHistory.open(_example_copy(tmp_path), read_only=True) as history:
        comparison = build_comparison(history)
    labels = sorted(row["Label"] for row in comparison.group_rows)
    assert labels == [
        "pilot-w001",
        "pilot-w002",
        "pilot-w004",
        "pilot-w008",
        "pilot-w016",
        "pilot-w032",
        "pilot-w064",
        "pilot-w126",
        "pilot-warmup",
    ]
    assert all(row["Runs"] == 1 for row in comparison.group_rows)


def _lightness(color: str) -> float:
    """Relative luminance of a "#RRGGBB" color (WCAG)."""
    channels = [int(color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [
        c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


@pytest.mark.parametrize("count", [2, 3, 8, 12])
def test_ordered_colors_get_lighter_along_the_labels(count: int) -> None:
    colors = chart_palette(count)
    assert len(colors) == len(set(colors)) == count
    lightness = [_lightness(color) for color in colors]
    assert lightness[0] < lightness[-1]
    assert lightness == sorted(lightness)


def test_unordered_colors_are_the_four_then_the_ordered_ones() -> None:
    four = chart_categories(4)
    assert chart_categories(2) == four[:2]
    assert len(set(four)) == 4
    assert chart_categories(5) == chart_palette(5)


def test_linear_time_axis_starts_at_zero_and_keeps_every_row() -> None:
    rows = [{"Seconds": 0.0}, {"Seconds": 3.0}]
    kept, encoding = time_bars("y", "Seconds", "Time (s)", rows, "linear")
    assert kept == rows
    assert set(encoding) == {"y"}
    assert encoding["y"].to_dict()["scale"] == {"type": "linear", "zero": True}


def test_log_time_axis_spans_whole_decades_and_drops_zero() -> None:
    # A log axis has no zero: the row without time is left out, the axis
    # runs from the decade below the shortest time to the one above the
    # longest, and the bars start at its bottom.
    rows = [{"Seconds": 0.0}, {"Seconds": 0.4}, {"Seconds": 60.0}]
    kept, encoding = time_bars("x", "Seconds", "Time (s)", rows, "log")
    assert kept == rows[1:]
    assert encoding["x"].to_dict()["scale"] == {"type": "log", "domain": [0.1, 100]}
    assert encoding["x2"].to_dict() == {"datum": 0.1}


def test_stage_bars_show_every_value_next_to_its_bar() -> None:
    # On a linear axis a stage far shorter than the longest gets a bar too
    # thin to see (0.05 s next to 38.5 s); its value still shows as text.
    rows = [
        {"Stage": "reading", "Median (s)": 38.5},
        {"Stage": "planning", "Median (s)": 0.05},
    ]
    kept, time = time_bars("x", "Median (s)", "Median (s)", rows, "linear")
    spec = stage_bars(
        kept, time, "Median (s)", "Median (s)", ".2f", ["reading", "planning"], "#000"
    ).to_dict()

    bars, values = spec["layer"]
    assert bars["mark"]["type"] == "bar"
    assert values["mark"]["type"] == "text"
    assert values["encoding"]["text"] == {
        "field": "Median (s)",
        "format": ".2f",
        "type": "quantitative",
    }
    # Both on the same time axis, so a value sits at the end of its bar.
    assert bars["encoding"]["x"] == values["encoding"]["x"]
    assert bars["encoding"]["x"]["scale"] == {"type": "linear", "zero": True}


def test_line_time_axis_has_no_baseline_and_keeps_zero_on_linear() -> None:
    # A line has no x2/y2 baseline (a bar does), and a linear axis starts at
    # zero and keeps every row.
    rows = [{"Seconds": 0.0}, {"Seconds": 3.0}]
    kept, encoding = time_line("y", "Seconds", "Time (s)", rows, "linear")
    assert kept == rows
    assert set(encoding) == {"y"}
    assert encoding["y"].to_dict()["scale"] == {"type": "linear", "zero": True}


def test_line_log_time_axis_drops_zero_and_spans_decades() -> None:
    # As for the bars: a log axis leaves the zero row out and runs between
    # the decades around the shortest and longest time.
    rows = [{"Seconds": 0.0}, {"Seconds": 0.4}, {"Seconds": 60.0}]
    kept, encoding = time_line("x", "Seconds", "Time (s)", rows, "log")
    assert kept == rows[1:]
    assert encoding["x"].to_dict()["scale"] == {"type": "log", "domain": [0.1, 100]}
    assert "x2" not in encoding


def test_line_time_axis_keeps_the_data_order() -> None:
    # A line connects the points in the order they come in, so the rows must
    # not be reordered.
    rows = [{"Seconds": 3.0}, {"Seconds": 1.0}, {"Seconds": 2.0}]
    kept, encoding = time_line("x", "Seconds", "Time (s)", rows, "linear")
    assert kept == rows


def test_stage_stats_total_and_per_day_median() -> None:
    # The median is over the stage's per-day seconds, where the per-day
    # totals can differ from the mean; a stage that names no day takes the
    # median of its records. A unit of days (a record whose day names
    # several days joined by commas) is split evenly over its days.
    timings = [
        StageTiming(
            datetime.now(UTC), "reading", 1.0, "ok", receiver="c1", day="2025001", pid=1
        ),
        StageTiming(
            datetime.now(UTC), "reading", 2.0, "ok", receiver="c1", day="2025002", pid=1
        ),
        StageTiming(
            datetime.now(UTC),
            "reading",
            10.0,
            "ok",
            receiver="c1",
            day="2025003,2025004,2025005,2025006,2025007",
            pid=1,
        ),
        StageTiming(
            datetime.now(UTC),
            "day_block_growth",
            3.0,
            "ok",
            receiver=None,
            day=None,
            pid=1,
        ),
        StageTiming(
            datetime.now(UTC),
            "day_block_growth",
            9.0,
            "ok",
            receiver=None,
            day=None,
            pid=1,
        ),
    ]
    rows = {row["Stage"]: row for row in stage_stats(timings)}
    # per-day totals are [1, 2, 2, 2, 2, 2, 2]; median 2.0, mean 13/7.
    # The 10 s of the unit are 2 s per day, so the median is 2.0, equal to
    # the mean here but per day, not per unit.
    assert rows["reading"]["Total (s)"] == 13.0
    assert rows["reading"]["Median (s)"] == 2.0
    # A stage that names no day takes the median of its records.
    assert rows["day_block_growth"]["Median (s)"] == 6.0
    # Rows are sorted by total, high to low.
    assert [row["Stage"] for row in stage_stats(timings)] == [
        "reading",
        "day_block_growth",
    ]


def test_split_days_splits_a_unit_evenly_over_its_days() -> None:
    # A record of a unit of days names its days joined by commas; its
    # seconds are split evenly, so a unit is not one long point.
    assert split_days("2025168,2025169", 4.0) == [
        ("2025168", 2.0),
        ("2025169", 2.0),
    ]
    assert split_days("2025168", 3.0) == [("2025168", 3.0)]
    # A record without a day yields nothing (time per day groups by day).
    assert split_days(None, 3.0) == []
    assert split_days("", 3.0) == []


def test_store_rows_one_row_per_store_per_day_plus_total() -> None:
    # One row per (day, store) and a Total row per day, the sum of the stores
    # recorded that day, ordered by day.
    sizes = [
        StoreSize("GNSS store", "2025001", datetime.now(UTC), 2000),
        StoreSize("VOD store", "2025001", datetime.now(UTC), 500),
        StoreSize("GNSS store", "2025002", datetime.now(UTC), 3000),
    ]
    first, second = "2025-01-01", "2025-01-02"
    assert store_rows(sizes) == [
        {"Day": "2025001", "Date": first, "Store": "GNSS store", "Size (bytes)": 2000},
        {"Day": "2025001", "Date": first, "Store": "VOD store", "Size (bytes)": 500},
        {"Day": "2025001", "Date": first, "Store": "Total", "Size (bytes)": 2500},
        {"Day": "2025002", "Date": second, "Store": "GNSS store", "Size (bytes)": 3000},
        {"Day": "2025002", "Date": second, "Store": "Total", "Size (bytes)": 3000},
    ]


def test_an_iso_day_counts_as_its_yyyydoy_day() -> None:
    # Runs before the fix recorded the VOD phase's days as ISO dates.
    assert day_key("2025-06-18") == "2025169"
    assert day_key("2024-12-31") == "2024366"
    assert day_key("2025169") == "2025169"
    assert day_key("not a day") == "not a day"
    assert split_days("2025-06-17,2025-06-18", 4.0) == [
        ("2025168", 2.0),
        ("2025169", 2.0),
    ]


def test_day_rows_join_iso_and_yyyydoy_records_of_a_day() -> None:
    def timing(stage: str, day: str, seconds: float) -> StageTiming:
        return StageTiming(datetime.now(UTC), stage, seconds, "ok", None, day, None)

    timings = [
        timing("writing", "2025169,2025170", 4.0),
        timing("vod_calc", "2025-06-18", 1.0),
        timing("vod_calc", "2025170", 1.5),
    ]
    assert day_rows(timings) == [
        {"Day": "2025169", "Date": "2025-06-18", "Seconds": 3.0},
        {"Day": "2025170", "Date": "2025-06-19", "Seconds": 3.5},
    ]


def test_store_size_record_and_older_history(tmp_path: Path) -> None:
    # The record upserts on (run, store, day) so a later measure of the same
    # day replaces the earlier one, and keeps how long the walk took.
    log_dir = tmp_path / "logs"
    rid = "fangorn-20261014-100000"
    with RunHistory.open(log_dir) as history:
        history.start_run(
            rid,
            site="fangorn",
            settings={},
            canvodpy_version="1.0.0",
            commit="abc1234",
            machine={},
            workers=1,
            started_at=datetime(2026, 10, 14, 10, 0, 0, tzinfo=UTC),
        )
        history.record_store_size(
            rid, "GNSS store", day="2025001", bytes=1000, walk_seconds=0.5
        )
        history.record_store_size(
            rid, "GNSS store", day="2025001", bytes=2000, walk_seconds=0.7
        )
        history.record_store_size(
            rid, "VOD store", day="2025001", bytes=500, walk_seconds=0.3
        )
        sizes = history.store_sizes(rid)
        assert [
            (size.store, size.day, size.bytes, size.walk_seconds) for size in sizes
        ] == [
            ("GNSS store", "2025001", 2000, 0.7),
            ("VOD store", "2025001", 500, 0.3),
        ]

    # An older run history (no store_sizes table) still opens and reports none.
    old = tmp_path / "old"
    old.mkdir()
    path = old / "run_history.sqlite"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE runs (run_id TEXT PRIMARY KEY)")
    db.execute("PRAGMA user_version = 2")
    db.commit()
    db.close()
    with RunHistory.open(old, read_only=True) as history:
        assert history.store_sizes("anything") == []
