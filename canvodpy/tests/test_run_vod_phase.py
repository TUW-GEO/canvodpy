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
import polars as pl
import pytest
from canvodpy.orchestrator import store_retry
from canvodpy.orchestrator.pipeline import PipelineOrchestrator
from canvodpy.orchestrator.processor import RinexDataProcessor
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


def test_vod_timings_name_their_day_as_yyyydoy(two_days) -> None:
    # The GNSS stages key a day as YYYYDOY; the VOD phase's time must join
    # them on the time-per-day chart, not form points of its own.
    with _site().pipeline(n_workers=2) as pipeline:
        list(pipeline.run(*DAYS))

    log_dir = Path(two_days.processing.logging.log_dir)
    # A timing event is in both agent.json and performance.json.
    vod_days = {
        t["date_key"]
        for t in _log_events(log_dir, "stage_timing")
        if t["stage"] == "vod_calc"
    }
    assert vod_days == set(DAYS)
    unit_days = {
        day
        for e in _log_events(log_dir, "vod_unit_committed")
        for day in (e["first"], e["last"])
    }
    assert unit_days <= set(DAYS)


def test_the_vod_growth_commit_names_its_days_as_yyyydoy(two_days) -> None:
    # The second run grows the VOD day blocks the first run created.
    site = _site()
    for day in DAYS:
        with site.pipeline(n_workers=2) as pipeline:
            list(pipeline.run(day, day))

    messages = [s.message for s in site.vod_store.repo.ancestry(branch="main")]
    growth = [m for m in messages if "VOD day blocks for" in m]
    assert growth == [growth[0]]
    assert growth[0].endswith(f"VOD day blocks for {DAYS[1]}..{DAYS[1]}")


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


def _prepared_days(monkeypatch) -> list[str]:
    """The days whose auxiliary data and files a run prepares."""
    prepared: list[str] = []
    prepare = PipelineOrchestrator._prepare_single_date

    def spy(self, date_key, *args, **kwargs):
        prepared.append(date_key)
        return prepare(self, date_key, *args, **kwargs)

    monkeypatch.setattr(PipelineOrchestrator, "_prepare_single_date", spy)
    return prepared


def test_a_rerun_skips_stored_days_before_reading_them(two_days, monkeypatch) -> None:
    site = _site()
    with site.pipeline(n_workers=2) as pipeline:
        list(pipeline.run(*DAYS))
    gnss_tip = site.gnss_store.repo.lookup_branch("main")
    vod_tip = site.vod_store.repo.lookup_branch("main")

    prepared = _prepared_days(monkeypatch)
    with site.pipeline(n_workers=2) as pipeline:
        units = list(pipeline.run(*DAYS))

    # Every file of both days is in the log book: nothing is read, and the
    # days still reach the VOD phase.
    assert prepared == []
    assert site.vod_store.repo.lookup_branch("main") == vod_tip
    assert sorted(day for unit in units for day in unit.days) == list(DAYS)
    assert {unit.days[day] for unit in units for day in unit.days} == {GROUPS}
    # One commit records the run's skipped files, a row per file seen.
    store = MyIcechunkStore(site.gnss_store_path)
    commits = list(store.repo.ancestry(branch="main"))
    assert commits[1].id == gnss_tip
    for group in GROUPS:
        rows = store.load_metadata_for_dedup(group)
        written = rows.filter(pl.col("action") != "skipped")
        skipped = rows.filter(pl.col("action") == "skipped")
        columns = ["rinex_hash", "start", "end", "canonical_name"]
        assert sorted(skipped.select(columns).rows()) == sorted(
            written.select(columns).rows()
        )
        assert skipped["run_id"].n_unique() == 1
        assert set(skipped["run_id"]).isdisjoint(written["run_id"])


def test_a_rerun_reads_only_the_days_with_new_files(two_days, monkeypatch) -> None:
    site = _site()
    with site.pipeline(n_workers=2) as pipeline:
        list(pipeline.run(DAYS[0], DAYS[0]))

    prepared = _prepared_days(monkeypatch)
    with site.pipeline(n_workers=2) as pipeline:
        units = list(pipeline.run(*DAYS))

    assert prepared == [DAYS[1]]
    assert sorted(day for unit in units for day in unit.days) == list(DAYS)
    assert _vod_days(site) == {"2025-01-01", "2025-01-02"}


def _fail_once(monkeypatch, owner, name):
    """Let ``owner.name`` fail with a dropped connection on its first call."""
    calls = []
    original = getattr(owner, name)

    def flaky(*args, **kwargs):
        calls.append(name)
        if len(calls) == 1:
            msg = "end of file before message length reached"
            raise OSError(msg)
        return original(*args, **kwargs)

    monkeypatch.setattr(owner, name, flaky)
    monkeypatch.setattr(store_retry, "STORE_RETRY_BACKOFF_SECONDS", (0.0,) * 4)
    return calls


def test_a_unit_commit_survives_a_dropped_connection(two_days, monkeypatch) -> None:
    # A transient store error (S3 500, a dropped connection) once the
    # unit's forks are back: the unit is written again, not lost.
    calls = _fail_once(monkeypatch, RinexDataProcessor, "_commit_forked_unit")
    site = _site()
    with site.pipeline(n_workers=2) as pipeline:
        units = list(pipeline.run(*DAYS))

    assert len(calls) >= 2
    assert sorted(day for unit in units for day in unit.days) == list(DAYS)
    assert _vod_days(site) == {"2025-01-01", "2025-01-02"}
    log_dir = Path(two_days.processing.logging.log_dir)
    retries = _log_events(log_dir, "store_op_retry")
    assert {e["op"] for e in retries} == {"write_unit"}


def test_a_vod_unit_survives_a_dropped_connection(two_days, monkeypatch) -> None:
    calls = _fail_once(monkeypatch, MyIcechunkStore, "commit_vod_days")
    site = _site()
    with site.pipeline(n_workers=2) as pipeline:
        units = list(pipeline.run(*DAYS))

    assert len(calls) >= 2
    assert [unit.vod_error for unit in units] == [None] * len(units)
    assert _vod_days(site) == {"2025-01-01", "2025-01-02"}
    log_dir = Path(two_days.processing.logging.log_dir)
    retries = _log_events(log_dir, "store_op_retry")
    assert {(e["op"], e["first"]) for e in retries} == {("vod_unit", DAYS[0])}


def test_a_run_without_vod_writes_no_vod_store(two_days) -> None:
    site = _site()
    with site.pipeline(n_workers=2) as pipeline:
        units = list(pipeline.run(*DAYS, vod_analyses=()))

    assert [unit.vod for unit in units] == [None] * len(units)
    assert not Path(site.vod_store_path).exists()
    assert MyIcechunkStore(site.gnss_store_path).list_groups()
