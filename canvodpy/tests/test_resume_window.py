"""A run without dates resumes the receiver-days with new files (#386).

The window is today minus ``RESUME_WINDOW_DAYS`` up to today; within it a
run processes only the days for which the archive holds a file the GNSS
store doesn't. A first run on an empty store starts from the oldest data.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from canvodpy.cli.app import main_app
from canvodpy.cli.run import RESUME_WINDOW_DAYS, _resolve_date_range
from canvodpy.orchestrator.discovery import clear_discovery_cache
from test_run_discovery_messages import _write_site
from typer.testing import CliRunner

import canvod.config.loader as loader_module
from canvod.store import MyIcechunkStore
from canvod.store_metadata.testing import create_test_store, give_test_metadata
from canvod.utils.testing import SITE_KEY

runner = CliRunner()
REFERENCE_GROUP = "reference_01_canopy_01"


@pytest.fixture(autouse=True)
def _fresh():
    loader_module.load_config.cache_clear()
    clear_discovery_cache()
    yield
    loader_module.load_config.cache_clear()
    clear_discovery_cache()


def _day(days_ago: int) -> str:
    return (datetime.now(UTC).date() - timedelta(days=days_ago)).strftime("%Y%j")


def _name(station: str, day: str) -> str:
    return f"{station}_R_{day}0000_15M_05S_AA.sbf"


def _site(tmp_path: Path, monkeypatch, days: list[str]) -> Path:
    """The test site with a canopy and a reference file on each of ``days``."""
    config_dir = _write_site(tmp_path)
    monkeypatch.setenv("CANVOD_CONFIG_DIR", str(config_dir))
    data = tmp_path / "data"
    for day in days:
        (data / "02_canopy" / _name("FANA01INK", day)).write_text("")
        (data / "01_reference" / _name("FANR01INK", day)).write_text("")
    return data


def _store(tmp_path: Path, stored: dict[str, list[str]]) -> None:
    """The site's GNSS store, whose log book holds the files ``stored``."""
    from canvodpy import Site

    store_path = Site(SITE_KEY).gnss_store_path
    store_path.mkdir(parents=True)
    store = MyIcechunkStore(create_test_store(store_path))
    give_test_metadata(store_path)
    epoch = np.datetime64("2025-01-01T00:00:00", "ns")
    for group, names in stored.items():
        for name in names:
            store.append_metadata(
                group,
                rinex_hash=name,
                start=epoch,
                end=epoch,
                snapshot_id="",
                action="write",
                commit_msg="test",
                dataset_attrs={},
                canonical_name=name,
            )


def _dry_run() -> str:
    clear_discovery_cache()
    loader_module.load_config.cache_clear()
    result = runner.invoke(
        main_app,
        ["run", "--dry-run", "--site", SITE_KEY],
        env={"CANVOD_CONFIG_DIR": os.environ["CANVOD_CONFIG_DIR"], "COLUMNS": "300"},
    )
    assert result.exit_code == 0, result.output
    return result.output


def test_a_lagging_receiver_and_a_late_file_are_resumed(tmp_path, monkeypatch):
    old, older, newest = _day(5), _day(4), _day(2)
    _site(tmp_path, monkeypatch, [old, older, newest])
    # The canopy is stored up to the newest day; the reference lags two days
    # behind, and a late canopy file arrived for a day before the newest.
    _store(
        tmp_path,
        {
            "canopy_01": [_name("FANA01INK", old), _name("FANA01INK", newest)],
            REFERENCE_GROUP: [_name("FANR01INK", newest)],
        },
    )

    output = _dry_run()

    assert (
        f"resuming: 3 receiver-days with new files ({old} reference_01, "
        f"{older} canopy_01, {older} reference_01)"
    ) in output
    assert f"'date': '{old}'" in output
    assert f"'date': '{older}'" in output
    assert f"'date': '{newest}'" not in output


def test_a_run_with_nothing_new_says_so(tmp_path, monkeypatch):
    day = _day(3)
    _site(tmp_path, monkeypatch, [day])
    _store(
        tmp_path,
        {
            "canopy_01": [_name("FANA01INK", day)],
            REFERENCE_GROUP: [_name("FANR01INK", day)],
        },
    )

    output = _dry_run()

    assert "resuming: no receiver-days with new files" in output
    assert f"'date': '{day}'" not in output


def test_the_window_does_not_follow_the_store(tmp_path, monkeypatch):
    # A gap in the archive (no files at all) never pulls the window back:
    # the window is always the last RESUME_WINDOW_DAYS days.
    _site(tmp_path, monkeypatch, [_day(20)])
    _store(tmp_path, {"canopy_01": [_name("FANA01INK", "2025001")]})
    from canvodpy import Site

    start, end, new_files_only = _resolve_date_range(
        SimpleNamespace(start=None, end=None), Site(SITE_KEY)
    )

    assert (start, end) == (_day(RESUME_WINDOW_DAYS), _day(0))
    assert new_files_only


def test_explicit_dates_process_every_day_in_the_range(tmp_path, monkeypatch):
    _site(tmp_path, monkeypatch, [])
    from canvodpy import Site

    start, end, new_files_only = _resolve_date_range(
        SimpleNamespace(start="2025001", end="2025002"), Site(SITE_KEY)
    )

    assert (start, end, new_files_only) == ("2025001", "2025002", False)


def test_a_first_run_starts_from_the_oldest_data(tmp_path, monkeypatch):
    _site(tmp_path, monkeypatch, [_day(3)])
    from canvodpy import Site

    start, end, new_files_only = _resolve_date_range(
        SimpleNamespace(start=None, end=None), Site(SITE_KEY)
    )

    assert (start, end, new_files_only) == ("2000001", _day(0), False)
