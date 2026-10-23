"""A run says which receiver-days miss files and which days get no VOD (#387).

A receiver-day with fewer files than its file length gives for a whole day
(96 files of 15 minutes) gets one warning. A day on which only one receiver
of a pair has files is never processed; the run says it gets no VOD and
which receiver has no files.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path

import pytest
from canvodpy.cli.app import main_app
from canvodpy.logging.run_history_handler import RunHistoryHandler
from canvodpy.orchestrator.discovery import clear_discovery_cache
from canvodpy.run_history import RunHistory
from test_run_discovery_messages import _write_site
from typer.testing import CliRunner

import canvod.config.loader as loader_module
from canvod.utils.testing import SITE_KEY

runner = CliRunner()
DAY = "2025001"


@pytest.fixture(autouse=True)
def _fresh():
    loader_module.load_config.cache_clear()
    clear_discovery_cache()
    yield
    loader_module.load_config.cache_clear()
    clear_discovery_cache()


def _site(tmp_path: Path, monkeypatch) -> Path:
    """The test site: one canopy and one reference file on 2025001."""
    config_dir = _write_site(tmp_path)
    monkeypatch.setenv("CANVOD_CONFIG_DIR", str(config_dir))
    return tmp_path / "data"


def _fill_day(folder: Path, station: str, day: str) -> None:
    """All 96 files of 15 minutes of ``day``."""
    for quarter in range(96):
        hhmm = f"{quarter // 4:02d}{quarter % 4 * 15:02d}"
        (folder / f"{station}_R_{day}{hhmm}_15M_05S_AA.sbf").write_text("")


def _dry_run(start: str, end: str) -> str:
    clear_discovery_cache()
    loader_module.load_config.cache_clear()
    result = runner.invoke(
        main_app,
        ["run", "--dry-run", "--site", SITE_KEY, "--start", start, "--end", end],
        env={"CANVOD_CONFIG_DIR": os.environ["CANVOD_CONFIG_DIR"], "COLUMNS": "300"},
    )
    assert result.exit_code == 0, result.output
    return result.output


def test_a_receiver_day_with_missing_files_is_named(tmp_path, monkeypatch):
    data = _site(tmp_path, monkeypatch)
    _fill_day(data / "01_reference", "FANR01INK", DAY)

    output = _dry_run(DAY, DAY)

    assert "  incomplete: canopy_01 has 1 of 96 files on 2025001" in output
    assert "reference_01 has" not in output


def test_complete_receiver_days_give_no_warning(tmp_path, monkeypatch):
    data = _site(tmp_path, monkeypatch)
    _fill_day(data / "02_canopy", "FANA01INK", DAY)
    _fill_day(data / "01_reference", "FANR01INK", DAY)

    output = _dry_run(DAY, DAY)

    assert "incomplete" not in output


def test_today_is_not_checked_as_its_files_are_still_arriving(tmp_path, monkeypatch):
    data = _site(tmp_path, monkeypatch)
    today = datetime.now().strftime("%Y%j")
    (data / "02_canopy" / f"FANA01INK_R_{today}0000_15M_05S_AA.sbf").write_text("")
    (data / "01_reference" / f"FANR01INK_R_{today}0000_15M_05S_AA.sbf").write_text("")

    output = _dry_run(today, today)

    assert "incomplete" not in output


def test_a_day_with_files_of_one_receiver_only_says_it_gets_no_vod(
    tmp_path, monkeypatch
):
    data = _site(tmp_path, monkeypatch)
    for day in ("2025002", "2025003"):
        (data / "02_canopy" / f"FANA01INK_R_{day}0000_15M_05S_AA.sbf").write_text("")

    output = _dry_run(DAY, "2025003")

    assert ("  no VOD on 2 days, reference_01 has no files: 2025002, 2025003") in output


def test_the_warning_reaches_the_run_history_in_words(tmp_path):
    with RunHistory.open(tmp_path) as history:
        history.start_run(
            "run-1",
            site=SITE_KEY,
            settings={},
            canvodpy_version="1.0.0",
            commit=None,
            machine={},
            workers=1,
            label=None,
        )
    handler = RunHistoryHandler(tmp_path)
    record = logging.LogRecord("canvodpy", logging.WARNING, "", 0, None, None, None)
    record.msg = {
        "event": "receiver_day_incomplete",
        "run_id": "run-1",
        "receiver": "canopy_01",
        "date": DAY,
        "summary": "canopy_01 has 81 of 96 files on 2025001",
    }
    handler.emit(record)
    handler.close()

    with RunHistory.open(tmp_path, read_only=True) as history:
        (problem,) = history.problems("run-1")
    assert (problem.level, problem.message, problem.receiver, problem.day) == (
        "warning",
        "canopy_01 has 81 of 96 files on 2025001",
        "canopy_01",
        DAY,
    )
