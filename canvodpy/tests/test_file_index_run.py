"""The file index of a run (#299): through ``Site.pipeline()`` and the CLI.

A run saves the names it finds per folder in the run history; the next run
lists again only folders with recent files and takes old folders from the
index. ``--rescan`` lists every folder.
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


def _open_and_close_a_run() -> None:
    from canvodpy.api import Site

    clear_discovery_cache()
    with Site(SITE_KEY).pipeline(n_workers=1):
        pass


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


def _dry_run(*extra: str) -> str:
    clear_discovery_cache()
    loader_module.load_config.cache_clear()
    result = runner.invoke(
        main_app,
        [
            "run",
            "--dry-run",
            "--site",
            SITE_KEY,
            "--start",
            "2025001",
            "--end",
            "2025001",
            *extra,
        ],
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


def test_the_next_run_lists_only_recent_and_undated_folders(
    tmp_path, monkeypatch
) -> None:
    canopy = _archive(tmp_path, monkeypatch)
    _open_and_close_a_run()
    listed: list[Path] = []
    real = os.scandir

    def counting(path):
        listed.append(Path(path))
        return real(path)

    monkeypatch.setattr(os, "scandir", counting)
    _open_and_close_a_run()

    assert canopy in listed
    assert canopy / "recent" in listed
    assert canopy / "25001" not in listed


def test_a_file_added_to_an_old_folder_needs_rescan(tmp_path, monkeypatch) -> None:
    canopy = _archive(tmp_path, monkeypatch)
    _open_and_close_a_run()
    (canopy / "25001" / OLD_ADDED).write_text("")

    assert "Found 2 files on 2 days for receiver canopy_01" in _dry_run()
    assert "Found 3 files on 2 days for receiver canopy_01" in _dry_run("--rescan")


def test_a_lost_run_history_gives_the_full_scan(tmp_path, monkeypatch) -> None:
    canopy = _archive(tmp_path, monkeypatch)
    _open_and_close_a_run()
    (canopy / "25001" / OLD_ADDED).write_text("")
    _release_run_history()
    run_history_path(tmp_path / "logs").unlink()

    assert "Found 3 files on 2 days for receiver canopy_01" in _dry_run()
    _open_and_close_a_run()
    with RunHistory.open(tmp_path / "logs", read_only=True) as history:
        assert OLD_ADDED in history.file_index(canopy, None)["25001"].files


def test_rescan_is_explained_in_the_help() -> None:
    result = runner.invoke(main_app, ["run", "--help"], env={"COLUMNS": "200"})
    # ANSI codes removed: on GitHub Actions typer forces a colored terminal.
    plain = " ".join(re.sub(r"\x1b\[[0-9;]*m", "", result.output).split())
    assert "--rescan" in plain
    assert "30 days" in plain


def test_a_damaged_file_index_gives_the_full_scan(tmp_path, monkeypatch) -> None:
    import sqlite3

    canopy = _archive(tmp_path, monkeypatch)
    _open_and_close_a_run()
    (canopy / "25001" / OLD_ADDED).write_text("")
    with sqlite3.connect(run_history_path(tmp_path / "logs")) as db:
        db.execute("UPDATE file_index SET files = 'not json'")
    db.close()

    assert "Found 3 files on 2 days for receiver canopy_01" in _dry_run()
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

    assert "Found 3 files on 2 days for receiver canopy_01" in _dry_run()
