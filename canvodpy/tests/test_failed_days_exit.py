"""A run whose receiver-days fail says so (#334).

``canvodpy run`` exits with code 3 when a receiver-day failed,
``Site.pipeline()`` lists the failed receiver-days, and the Airflow task
``process_day`` raises, so the scheduler retries it.
"""

from __future__ import annotations

import pytest
from canvodpy.orchestrator.discovery import clear_discovery_cache
from canvodpy.orchestrator.pipeline import PipelineOrchestrator
from test_run_discovery_messages import _write_site
from typer.testing import CliRunner

import canvod.config.loader as loader_module
from canvod.utils import testing

DAY = "2025001"


@pytest.fixture
def site(tmp_path, monkeypatch):
    """The made-up test site with one day of files, settings in tmp_path."""
    monkeypatch.setenv("CANVOD_CONFIG_DIR", str(_write_site(tmp_path)))
    loader_module.load_config.cache_clear()
    clear_discovery_cache()
    yield
    loader_module.load_config.cache_clear()
    clear_discovery_cache()


def _one_failed_day(self, **_kwargs):
    """The run of DAY: canopy_01 fails, reference_01 is written."""
    self._finish_receiver_day("canopy_01", DAY, "failed")
    self._finish_receiver_day("reference_01", DAY, "written", bytes_added=1)
    yield {DAY: ("reference_01",)}


def _all_written(self, **_kwargs):
    self._finish_receiver_day("canopy_01", DAY, "written", bytes_added=1)
    self._finish_receiver_day("reference_01", DAY, "skipped")
    yield {DAY: ("canopy_01", "reference_01")}


def _cli_run():
    from canvodpy.cli.app import main_app

    return CliRunner().invoke(
        main_app,
        ["run", "--site", testing.SITE_KEY, "--start", DAY, "--end", DAY, "--no-vod"],
    )


def test_a_failed_receiver_day_makes_the_exit_code_3(site, monkeypatch) -> None:
    monkeypatch.setattr(PipelineOrchestrator, "store_by_unit", _one_failed_day)

    result = _cli_run()

    assert result.exit_code == 3, result.output
    assert f"1 receiver-day failed: {testing.SITE_KEY} canopy_01 {DAY}" in (
        " ".join(result.output.split())
    )


def test_written_and_skipped_days_exit_0(site, monkeypatch) -> None:
    monkeypatch.setattr(PipelineOrchestrator, "store_by_unit", _all_written)

    result = _cli_run()

    assert result.exit_code == 0, result.output
    assert "failed" not in result.output


def test_site_pipeline_lists_the_failed_receiver_days(site, monkeypatch) -> None:
    from canvodpy import Site

    monkeypatch.setattr(PipelineOrchestrator, "store_by_unit", _one_failed_day)

    with Site(testing.SITE_KEY).pipeline() as pipeline:
        assert pipeline.failed_receiver_days == ()
        list(pipeline.run(DAY, DAY, vod_analyses=()))

    assert pipeline.failed_receiver_days == (("canopy_01", DAY),)


def test_process_day_raises_when_a_receiver_day_failed(site, monkeypatch) -> None:
    from canvodpy.workflows.tasks import process_day

    monkeypatch.setattr(PipelineOrchestrator, "store_by_unit", _one_failed_day)

    with pytest.raises(RuntimeError, match=f"canopy_01 {DAY}"):
        process_day(testing.SITE_KEY, DAY)
