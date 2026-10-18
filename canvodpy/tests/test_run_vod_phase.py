"""A run chains the VOD phase after the GNSS phase, without read-back (#427).

``Pipeline.run`` stores a unit of days, then computes their VOD in the
worker pool from the GNSS store (ADR 0021). The GNSS phase reads nothing
back. On the Rosalia test data with a synthetic second day
(``synthetic_days``).
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from canvodpy.orchestrator.pipeline import PipelineOrchestrator
from synthetic_days import RECEIVERS, site_data

from canvod.store import MyIcechunkStore
from canvod.store.day_blocks import load_group
from canvod.utils import testing

pytestmark = pytest.mark.integration

DAYS = ("2025001", "2025002")
GROUPS = ("canopy_01", "reference_01_canopy_01")
ANALYSIS = "canopy_01_vs_reference_01"


@pytest.fixture
def two_days(rosalia_site, tmp_path, monkeypatch):
    """The site on both days, with its VOD analysis; reading back fails."""
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

    def no_read_back(*_args, **_kwargs):
        pytest.fail("The GNSS phase of a run read a day back.")

    monkeypatch.setattr(PipelineOrchestrator, "_read_back_day", no_read_back)
    return config


def _site():
    from canvodpy import Site

    return Site(testing.SITE_KEY)


def _vod_days(site) -> set[str]:
    with site.vod_store.readonly_session("main") as session:
        vod = load_group(session.store, f"tau_omega/{ANALYSIS}", drop_empty=True)
    return {str(day) for day in np.unique(vod.epoch.values.astype("M8[D]"))}


def test_a_run_stores_its_days_then_their_vod(two_days) -> None:
    site = _site()
    with site.pipeline(n_workers=2) as pipeline:
        units = list(pipeline.run(*DAYS))

    stored = {day: groups for unit in units for day, groups in unit.days.items()}
    assert stored == dict.fromkeys(DAYS, GROUPS)
    written = [day for unit in units for day in unit.vod.written[ANALYSIS]]
    assert [str(day) for day in written] == ["2025-01-01", "2025-01-02"]
    assert pipeline.failed_receiver_days == ()

    # The VOD the run stored is the VOD computed in memory from its GNSS days.
    with site.vod_store.readonly_session("main") as session:
        vod = load_group(session.store, f"tau_omega/{ANALYSIS}", drop_empty=True)
    expected = site.vod.compute_bulk(ANALYSIS, write=False)
    # Computed in memory, the VOD keeps the epochs of the padded day blocks.
    expected = expected.isel(epoch=np.isfinite(expected["VOD"]).any("sid").values)
    np.testing.assert_array_equal(vod.epoch.values, expected.epoch.values)
    np.testing.assert_allclose(
        vod["VOD"].sel(sid=expected.sid).values,
        expected["VOD"].values,
        equal_nan=True,
    )


def _log_events(log_dir: Path, event: str) -> list[dict]:
    events = []
    for path in log_dir.rglob("*"):
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("{") and f'"{event}"' in line:
                record = json.loads(line)
                if record.get("event") == event:
                    events.append(record)
    return events


def test_each_vod_task_logs_its_worker_memory_peak(two_days) -> None:
    with _site().pipeline(n_workers=2) as pipeline:
        list(pipeline.run(*DAYS))

    log_dir = Path(two_days.processing.logging.log_dir)
    peaks = [
        p
        for p in _log_events(log_dir, "worker_memory_peak")
        if p["task"] == "compute_vod_into_fork"
    ]
    # One task per analysis pair and day.
    assert len(peaks) == len(DAYS)
    assert all(p["peak_gb"] >= p["before_gb"] > 0 for p in peaks)


def test_a_day_whose_gnss_phase_fails_gets_no_vod(two_days, monkeypatch) -> None:
    prepare = PipelineOrchestrator._prepare_single_date

    def no_orbits_on_the_second_day(self, date_key, *args, **kwargs):
        if date_key == DAYS[1]:
            msg = f"Failed to download the orbit products of {date_key}"
            raise RuntimeError(msg)
        return prepare(self, date_key, *args, **kwargs)

    monkeypatch.setattr(
        PipelineOrchestrator, "_prepare_single_date", no_orbits_on_the_second_day
    )
    site = _site()
    with site.pipeline(n_workers=2) as pipeline:
        units = list(pipeline.run(*DAYS))

    # The day without orbit products stays open for the next run.
    assert [day for unit in units for day in unit.days] == [DAYS[0]]
    assert _vod_days(site) == {"2025-01-01"}


def test_a_run_without_vod_writes_no_vod_store(two_days) -> None:
    site = _site()
    with site.pipeline(n_workers=2) as pipeline:
        units = list(pipeline.run(*DAYS, vod_analyses=()))

    assert [unit.vod for unit in units] == [None] * len(units)
    assert not Path(site.vod_store_path).exists()
    assert MyIcechunkStore(site.gnss_store_path).list_groups()
