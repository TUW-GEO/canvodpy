"""A run prepares its days in the worker pool (#433, step 3).

Preparing a day (Phase 1: orbits and clocks, receiver positions, one task
per file) holds the GIL, so threads of the main process prepare one day
at a time. Each day is prepared in a worker process instead. On the
Rosalia test data with a synthetic second day (``synthetic_days``).
"""

from __future__ import annotations

import json
import os
import pickle
from pathlib import Path

import pytest
from canvodpy.orchestrator.pipeline import _prepare_day
from synthetic_days import RECEIVERS, site_data

from canvod.utils import testing

pytestmark = pytest.mark.integration

DAYS = ("2025001", "2025002")


@pytest.fixture
def two_days(rosalia_site, tmp_path):
    """The site on both days."""
    config, test_site = rosalia_site
    site = config.sites.sites[testing.SITE_KEY]
    site.receivers = dict(test_site._site_config.receivers)
    site.vod_analyses = dict(test_site._site_config.vod_analyses)
    every_file = dict.fromkeys(RECEIVERS, slice(None))
    data = site_data(
        tmp_path / "data", dict.fromkeys(DAYS, every_file), tmp_path / "synthetic"
    )
    config.processing.storage.stores_root_dir = tmp_path / "stores"
    site.gnss_site_data_root = str(data)
    return config


def _site():
    from canvodpy import Site

    return Site(testing.SITE_KEY)


def test_a_day_prepared_in_a_worker_is_the_day_prepared_here(two_days) -> None:
    with _site().pipeline(n_workers=2) as pipeline:
        orchestrator = pipeline._orchestrator
        grouped = orchestrator._group_by_date_and_receiver(DAYS[0], DAYS[0])
        ((date_key, receivers),) = orchestrator._filter_dates(grouped, DAYS[0], DAYS[0])
        args = orchestrator._prepare_day_args(date_key, receivers, None)

        here = _prepare_day(*args)
        in_worker = orchestrator.worker_pool().submit(_prepare_day, *args).result()

    assert here is not None
    assert in_worker == here
    assert pickle.loads(pickle.dumps(here)) == here
    assert {name for name, _files in here.receiver_file_map} == set(receivers)
    files = [f for _name, day_files in here.receiver_file_map for f in day_files]
    assert set(here.canonical_names) == set(files)


def test_a_run_prepares_its_days_in_worker_processes(two_days) -> None:
    from canvodpy.run_history import RunHistory

    site = _site()
    with site.pipeline(n_workers=2) as pipeline:
        units = list(pipeline.run(*DAYS))

    assert [day for unit in units for day in unit.days] == list(DAYS)
    assert pipeline.failed_receiver_days == ()
    with RunHistory.open(two_days.processing.logging.log_dir, read_only=True) as rh:
        (run,) = rh.runs(site=testing.SITE_KEY)
        timings = rh.stage_timings(run.run_id)
    preparing = [t for t in timings if t.stage == "auxiliary_data"]
    assert {t.day for t in preparing} == set(DAYS)
    assert all(t.pid != os.getpid() for t in preparing)
    # Each day's worker logs its memory peak, as the file tasks do.
    peaks = [
        json.loads(line)
        for path in Path(two_days.processing.logging.log_dir).rglob("*.json*")
        for line in path.read_text(encoding="utf-8").splitlines()
        if '"worker_memory_peak"' in line and '"_prepare_day"' in line
    ]
    assert len(peaks) == len(DAYS)


def test_a_day_whose_preparing_fails_in_a_worker_fails_its_receivers(
    two_days, monkeypatch
) -> None:
    from canvodpy.orchestrator.pipeline import PipelineOrchestrator

    data_root = Path(two_days.sites.sites[testing.SITE_KEY].gnss_site_data_root)
    prepare_batch = PipelineOrchestrator._prepare_batch

    def files_gone_before_preparing(self, batch, keep_vars, index):
        # Found, then gone: preparing the second day finds no files.
        for path in data_root.rglob(f"*{DAYS[1]}*"):
            if path.is_file():
                path.unlink()
        return prepare_batch(self, batch, keep_vars, index)

    monkeypatch.setattr(
        PipelineOrchestrator, "_prepare_batch", files_gone_before_preparing
    )
    with _site().pipeline(n_workers=2) as pipeline:
        units = list(pipeline.run(*DAYS))

    assert [day for unit in units for day in unit.days] == [DAYS[0]]
    assert {day for _group, day in pipeline.failed_receiver_days} == {DAYS[1]}


def test_a_day_whose_preparing_raises_in_a_worker_fails_its_receivers(
    two_days, monkeypatch
) -> None:
    import canvodpy.orchestrator.pipeline as pipeline_module

    prepare_day = pipeline_module._prepare_day

    def unreadable_second_day(site, config, date_key, *args):
        # Defined here, so the worker gets this function by value
        if date_key == DAYS[1]:
            raise OSError(f"cannot read the files of {date_key}")
        return prepare_day(site, config, date_key, *args)

    monkeypatch.setattr(pipeline_module, "_prepare_day", unreadable_second_day)
    with _site().pipeline(n_workers=2) as pipeline:
        units = list(pipeline.run(*DAYS))

    assert [day for unit in units for day in unit.days] == [DAYS[0]]
    assert {day for _group, day in pipeline.failed_receiver_days} == {DAYS[1]}
