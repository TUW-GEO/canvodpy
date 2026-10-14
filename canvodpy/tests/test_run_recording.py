"""Every run records itself in the run history (#296, #297, ADR 0018).

A run from ``Site.pipeline()``, ``canvodpy run`` or a scheduler task
records its start (settings, version, machine, label), the receiver-days
it plans and finishes, the time of its stages, its warnings and errors,
and its end. Tests read
the run history only through its queries.
"""

from __future__ import annotations

import os

import pytest
import structlog
from canvodpy.run_history import RunHistory
from typer.testing import CliRunner

from canvod.utils import testing

DAY = "2025001"


def _history(config) -> RunHistory:
    return RunHistory.open(config.processing.logging.log_dir, read_only=True)


def _only_run(config, label: str | None = None):
    with _history(config) as history:
        runs = history.runs(site=testing.SITE_KEY, label=label)
        assert len(runs) == 1
        run = runs[0]
        return (
            run,
            history.receiver_days(run.run_id),
            history.problems(run.run_id),
        )


def _assert_finished_run(run, receiver_days, label: str) -> None:
    assert run.status == "finished"
    assert run.label == label
    assert run.error is None
    assert run.ended_at is not None
    assert run.canvodpy_version
    assert "processing" in run.settings
    assert run.machine["cpu_logical"] >= 1
    assert run.machine["disks"]
    assert receiver_days
    for receiver_day in receiver_days:
        assert receiver_day.day == DAY
        assert receiver_day.result == "written"
        assert receiver_day.bytes_added > 0


@pytest.mark.integration
def test_site_pipeline_records_its_run(rosalia_site) -> None:
    from canvodpy import Site

    config, _ = rosalia_site
    with Site(testing.SITE_KEY).pipeline(label="python-run") as pipeline:
        datasets = pipeline.process_date(DAY)

    run, receiver_days, _ = _only_run(config)
    _assert_finished_run(run, receiver_days, "python-run")
    assert {r.receiver for r in receiver_days} == set(datasets)

    # Stage timings (#297): from the main process and the worker processes.
    with _history(config) as history:
        timings = history.stage_timings(run.run_id)
    stages = {t.stage for t in timings}
    assert {"finding_files", "auxiliary_data", "reading", "writing"} <= stages
    main_stages = {t.stage for t in timings if t.pid == os.getpid()}
    worker_stages = {t.stage for t in timings if t.pid != os.getpid()}
    assert {"finding_files", "auxiliary_data", "writing"} <= main_stages
    assert "reading" in worker_stages
    assert all(t.seconds >= 0 for t in timings)
    assert any(t.day == DAY for t in timings)


@pytest.mark.integration
def test_canvodpy_run_records_its_run_with_label(rosalia_site) -> None:
    from canvodpy.cli.app import main_app

    config, _ = rosalia_site
    result = CliRunner().invoke(
        main_app,
        [
            "run",
            "--site",
            testing.SITE_KEY,
            "--start",
            DAY,
            "--end",
            DAY,
            "--no-vod",
            "--label",
            "cli-run",
        ],
    )
    assert result.exit_code == 0, result.output

    run, receiver_days, _ = _only_run(config)
    _assert_finished_run(run, receiver_days, "cli-run")


def test_a_run_that_raises_is_failed_with_its_error_and_problems(
    rosalia_site, monkeypatch
) -> None:
    from canvodpy.orchestrator.pipeline import PipelineOrchestrator

    from canvodpy import Site

    config, _ = rosalia_site

    def broken(self, **_kwargs):
        structlog.get_logger("canvodpy.test").warning(
            "aux_download_slow", receiver="canopy_01", date=DAY
        )
        raise RuntimeError("the disk is full")
        yield  # a generator, like the real one

    monkeypatch.setattr(PipelineOrchestrator, "process_by_date", broken)

    with (
        pytest.raises(RuntimeError, match="the disk is full"),
        Site(testing.SITE_KEY).pipeline(label="broken") as pipeline,
    ):
        pipeline.process_date(DAY)

    run, receiver_days, problems = _only_run(config)
    assert run.status == "failed"
    assert run.error == "RuntimeError: the disk is full"
    assert receiver_days == []
    assert [(p.level, p.message, p.receiver, p.day) for p in problems] == [
        ("warning", "aux download slow", "canopy_01", DAY)
    ]


def test_check_day_records_a_run(rosalia_site) -> None:
    from canvodpy.workflows.tasks import check_day

    config, _ = rosalia_site
    assert check_day(testing.SITE_KEY, DAY)["ready"]

    run, _, _ = _only_run(config)
    assert run.status == "finished"


def test_check_day_without_files_is_a_failed_run(rosalia_site) -> None:
    from canvodpy.workflows.tasks import check_day

    config, _ = rosalia_site
    with pytest.raises(RuntimeError, match="not yet available"):
        check_day(testing.SITE_KEY, "2025200")

    run, _, _ = _only_run(config)
    assert run.status == "failed"
    assert run.error.startswith("RuntimeError: GNSS files not yet available")


def test_runs_started_in_the_same_second_are_two_runs(tmp_path) -> None:
    from canvodpy.run_history import recorded_run

    from canvod.utils.logging import get_run_id, reset_run_id, set_run_id

    token = set_run_id("fangorn-20261014-120000")
    try:
        for _ in range(2):
            with recorded_run(
                testing.SITE_KEY, log_dir=tmp_path, settings={}, workers=1
            ) as run:
                assert get_run_id() == run.run_id
        assert get_run_id() == "fangorn-20261014-120000"
    finally:
        reset_run_id(token)

    with RunHistory.open(tmp_path, read_only=True) as history:
        assert sorted(r.run_id for r in history.runs()) == [
            "fangorn-20261014-120000",
            "fangorn-20261014-120000-2",
        ]
