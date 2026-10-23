"""The file index of a run: through ``Site.pipeline()``, the CLI and Airflow.

A run saves the names it finds per folder in the run history; the next run
lists the folders that hold the days it processes and takes the others from
the index (ADR 0020).
"""

from __future__ import annotations

import logging
import os
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
from canvodpy.cli.app import main_app
from canvodpy.logging.run_history_handler import RunHistoryHandler
from canvodpy.orchestrator.discovery import clear_discovery_cache
from canvodpy.run_history import RunHistory, run_history_path
from test_run_discovery_messages import _write_site
from typer.testing import CliRunner

import canvod.config.loader as loader_module
from canvod.utils.testing import SITE_KEY

runner = CliRunner()
OLD = "FANA01INK_R_20250010000_15M_05S_AA.sbf"
OLD_ADDED = "FANA01INK_R_20250010015_15M_05S_AA.sbf"


@pytest.fixture(autouse=True)
def _fresh(monkeypatch, tmp_path):
    loader_module.load_config.cache_clear()
    clear_discovery_cache()
    yield
    loader_module.load_config.cache_clear()
    clear_discovery_cache()


def _archive(tmp_path: Path, monkeypatch) -> Path:
    """The test site, its canopy files moved into day folders, one recent."""
    config_dir = _write_site(tmp_path)
    monkeypatch.setenv("CANVOD_CONFIG_DIR", str(config_dir))
    canopy = tmp_path / "data" / "02_canopy"
    (canopy / "25001").mkdir()
    (canopy / OLD).rename(canopy / "25001" / OLD)
    today = datetime.now(UTC).date()
    doy = today.timetuple().tm_yday
    (canopy / "recent").mkdir()
    (
        canopy / "recent" / f"FANA01INK_R_{today.year}{doy:03d}0000_15M_05S_AA.sbf"
    ).write_text("")
    return canopy


def _today() -> str:
    return datetime.now(UTC).strftime("%Y%j")


def _open_and_close_a_run() -> None:
    """A run that finds the files of every day and processes none."""
    from canvodpy.api import Site

    clear_discovery_cache()
    with Site(SITE_KEY).pipeline(n_workers=1) as pipeline:
        pipeline.preview()


def _release_run_history() -> None:
    """Close the log handlers' run history connection, so the file can go.

    The handler keeps it open for the process; Windows can't delete an
    open file. It opens the file again at its next record.
    """
    loggers = [logging.getLogger(), *logging.Logger.manager.loggerDict.values()]
    for logger in loggers:
        for handler in getattr(logger, "handlers", []):
            if isinstance(handler, RunHistoryHandler):
                handler.close()


def _dry_run(day: str = "2025001") -> str:
    clear_discovery_cache()
    loader_module.load_config.cache_clear()
    result = runner.invoke(
        main_app,
        ["run", "--dry-run", "--site", SITE_KEY, "--start", day, "--end", day],
        env={"CANVOD_CONFIG_DIR": os.environ["CANVOD_CONFIG_DIR"]},
    )
    assert result.exit_code == 0, result.output
    return result.output


def test_a_run_saves_the_file_index_of_every_receiver(tmp_path, monkeypatch) -> None:
    canopy = _archive(tmp_path, monkeypatch)

    _open_and_close_a_run()

    with RunHistory.open(tmp_path / "logs", read_only=True) as history:
        assert set(history.file_index(canopy, None)) == {".", "25001", "recent"}
        reference = tmp_path / "data" / "01_reference"
        assert set(history.file_index(reference, None)) == {"."}


def test_a_file_added_to_an_old_folder_is_found_when_its_day_is_processed(
    tmp_path, monkeypatch
) -> None:
    canopy = _archive(tmp_path, monkeypatch)
    _open_and_close_a_run()
    (canopy / "25001" / OLD_ADDED).write_text("")

    assert "Found 3 files on 2 days for receiver canopy_01" in _dry_run("2025001")


def test_a_folder_of_other_days_comes_from_the_file_index(
    tmp_path, monkeypatch
) -> None:
    canopy = _archive(tmp_path, monkeypatch)
    _open_and_close_a_run()
    (canopy / "25001" / OLD_ADDED).write_text("")

    # Processing today, the folder 25001 is taken from the index, so the
    # file added there is not seen (the case the docs name).
    assert "Found 2 files on 2 days for receiver canopy_01" in _dry_run(_today())


def test_an_airflow_day_check_lists_only_the_folders_of_its_day(
    tmp_path, monkeypatch
) -> None:
    from canvodpy.orchestrator.discovery import scan_directory
    from canvodpy.workflows.tasks import check_day

    canopy = _archive(tmp_path, monkeypatch)
    reference = tmp_path / "data" / "01_reference"
    (reference / f"FANR01INK_R_{_today()}0000_15M_05S_AA.sbf").write_text("")
    _open_and_close_a_run()
    loader_module.load_config.cache_clear()

    check_day(SITE_KEY, _today())

    # The scan the check left in the cache: 25001 came from the index.
    assert scan_directory(canopy).folders_from_index == 1


def test_a_lost_run_history_gives_the_full_scan(tmp_path, monkeypatch) -> None:
    canopy = _archive(tmp_path, monkeypatch)
    _open_and_close_a_run()
    (canopy / "25001" / OLD_ADDED).write_text("")
    _release_run_history()
    run_history_path(tmp_path / "logs").unlink()

    assert "Found 3 files on 2 days for receiver canopy_01" in _dry_run(_today())
    _open_and_close_a_run()
    with RunHistory.open(tmp_path / "logs", read_only=True) as history:
        assert OLD_ADDED in history.file_index(canopy, None)["25001"].files


def test_rescan_is_gone_from_the_help() -> None:
    result = runner.invoke(main_app, ["run", "--help"], env={"COLUMNS": "200"})
    # ANSI codes removed: on GitHub Actions typer forces a colored terminal.
    plain = " ".join(re.sub(r"\x1b\[[0-9;]*m", "", result.output).split())
    assert "--rescan" not in plain


def test_a_damaged_file_index_gives_the_full_scan(tmp_path, monkeypatch) -> None:
    import sqlite3

    canopy = _archive(tmp_path, monkeypatch)
    _open_and_close_a_run()
    (canopy / "25001" / OLD_ADDED).write_text("")
    with sqlite3.connect(run_history_path(tmp_path / "logs")) as db:
        db.execute("UPDATE file_index SET files = 'not json'")
    db.close()

    assert "Found 3 files on 2 days for receiver canopy_01" in _dry_run(_today())
    _open_and_close_a_run()
    with RunHistory.open(tmp_path / "logs", read_only=True) as history:
        assert OLD_ADDED in history.file_index(canopy, None)["25001"].files


def test_a_damaged_run_history_file_gives_the_full_scan(tmp_path, monkeypatch) -> None:
    canopy = _archive(tmp_path, monkeypatch)
    _open_and_close_a_run()
    (canopy / "25001" / OLD_ADDED).write_text("")
    path = run_history_path(tmp_path / "logs")
    _release_run_history()
    for extra in path.parent.glob(path.name + "-*"):
        extra.unlink()
    path.write_bytes(b"not a database" * 100)

    assert "Found 3 files on 2 days for receiver canopy_01" in _dry_run(_today())


def test_the_data_check_lists_every_folder(tmp_path, monkeypatch) -> None:
    from canvodpy.orchestrator.data_check import check_site_data

    canopy = _archive(tmp_path, monkeypatch)
    _open_and_close_a_run()
    (canopy / "25001" / OLD_ADDED).write_text("")
    loader_module.load_config.cache_clear()

    report = check_site_data(SITE_KEY, check_sampling=False)

    assert report.receivers["canopy_01"].files == 3
