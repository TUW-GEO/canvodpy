"""A run is given its dates, or ``--update-to-latest`` (one site per run).

``--update-to-latest`` starts on the earliest last stored day, counting
only the store groups with new files: after their own last stored day, or
on it but not in their log book. It ends on the latest day with files.
Without dates or the option a run stops, as it does with both.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pytest
import yaml
from canvodpy.cli.app import main_app
from canvodpy.orchestrator.discovery import clear_discovery_cache
from canvodpy.orchestrator.run_dates import NothingStoredError
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
    # Local time, as the run's "today" (just after midnight UTC differs).
    return (datetime.now().date() - timedelta(days=days_ago)).strftime("%Y%j")


def _name(station: str, day: str, time: str = "0000") -> str:
    return f"{station}_R_{day}{time}_15M_05S_AA.sbf"


def _site(tmp_path: Path, monkeypatch, days: list[str]) -> Path:
    """The test site with a canopy and a reference file on each of ``days``."""
    config_dir = _write_site(tmp_path)
    monkeypatch.setenv("CANVOD_CONFIG_DIR", str(config_dir))
    data = tmp_path / "data"
    for day in days:
        (data / "02_canopy" / _name("FANA01INK", day)).write_text("")
        (data / "01_reference" / _name("FANR01INK", day)).write_text("")
    return data


def _second_canopy(tmp_path: Path, days: list[str]) -> None:
    """Add canopy_02, paired with reference_01, with a file on each of ``days``."""
    settings_file = tmp_path / "config" / "canvod-settings.yaml"
    settings = yaml.safe_load(settings_file.read_text())
    receivers = settings["sites"][SITE_KEY]["receivers"]
    receivers["canopy_02"] = {
        "type": "canopy",
        "directory": "03_canopy",
        "reader_format": "sbf",
    }
    receivers["reference_01"]["paired_canopies"].append("canopy_02")
    settings_file.write_text(yaml.safe_dump(settings))
    folder = tmp_path / "data" / "03_canopy"
    folder.mkdir()
    for day in days:
        (folder / _name("FANA02INK", day)).write_text("")


def _store(stored: dict[str, list[str]]) -> None:
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


def _run(*options: str):
    clear_discovery_cache()
    loader_module.load_config.cache_clear()
    return runner.invoke(
        main_app,
        ["run", "--dry-run", *options],
        env={"CANVOD_CONFIG_DIR": os.environ["CANVOD_CONFIG_DIR"], "COLUMNS": "300"},
    )


def _update() -> str:
    result = _run("--site", SITE_KEY, "--update-to-latest")
    assert result.exit_code == 0, result.output
    return result.output


def test_a_lagging_receiver_sets_the_start(tmp_path, monkeypatch):
    days = [_day(n) for n in (5, 4, 3, 2)]
    _site(tmp_path, monkeypatch, days)
    # The canopy is stored up to the newest day; the reference lags behind.
    _store(
        {
            "canopy_01": [_name("FANA01INK", day) for day in days],
            REFERENCE_GROUP: [_name("FANR01INK", day) for day in days[:2]],
        }
    )

    output = _update()

    # The reference's last stored day is run again: its stored files are
    # skipped by their hash.
    assert f"update: {_day(4)} to {_day(2)}" in output
    assert f"'date': '{_day(4)}'" in output
    assert f"'date': '{_day(2)}'" in output
    assert f"'date': '{_day(5)}'" not in output


def test_a_partly_stored_last_day_gets_its_remaining_files(tmp_path, monkeypatch):
    # A run at 03:00 stored the first files of the day; the rest arrived.
    day = _day(2)
    data = _site(tmp_path, monkeypatch, [day])
    for station, folder in (("FANA01INK", "02_canopy"), ("FANR01INK", "01_reference")):
        (data / folder / _name(station, day, "0015")).write_text("")
    _store(
        {
            "canopy_01": [_name("FANA01INK", day)],
            REFERENCE_GROUP: [_name("FANR01INK", day)],
        }
    )

    output = _update()

    assert f"update: {day} to {day}" in output


def test_a_retired_receiver_does_not_hold_the_start_back(tmp_path, monkeypatch):
    days = [_day(n) for n in (9, 8, 4, 3, 2)]
    _site(tmp_path, monkeypatch, days)
    # canopy_02 sent its last file eight days ago, and it is stored. The
    # reference's group of canopy_02 is stored as far as that of canopy_01.
    _second_canopy(tmp_path, days[:2])
    _store(
        {
            "canopy_01": [_name("FANA01INK", day) for day in days[:3]],
            REFERENCE_GROUP: [_name("FANR01INK", day) for day in days[:3]],
            "canopy_02": [_name("FANA02INK", day) for day in days[:2]],
            "reference_01_canopy_02": [_name("FANR01INK", day) for day in days[:3]],
        }
    )

    output = _update()

    assert f"update: {_day(4)} to {_day(2)}" in output


def test_a_receiver_with_nothing_stored_starts_at_its_first_file(tmp_path, monkeypatch):
    days = [_day(n) for n in (6, 5, 2)]
    _site(tmp_path, monkeypatch, days)
    # canopy_02 is new: none of its files is stored yet.
    _second_canopy(tmp_path, days[1:])
    _store(
        {
            "canopy_01": [_name("FANA01INK", day) for day in days],
            REFERENCE_GROUP: [_name("FANR01INK", day) for day in days],
        }
    )

    output = _update()

    assert f"update: {_day(5)} to {_day(2)}" in output


def test_nothing_new_is_said_and_is_no_error(tmp_path, monkeypatch):
    day = _day(3)
    _site(tmp_path, monkeypatch, [day])
    _store(
        {
            "canopy_01": [_name("FANA01INK", day)],
            REFERENCE_GROUP: [_name("FANR01INK", day)],
        }
    )

    output = _update()

    assert "update: no receiver has new files" in output
    assert "Dry-run plan" not in output


def test_an_empty_store_needs_a_start(tmp_path, monkeypatch):
    _site(tmp_path, monkeypatch, [_day(3)])

    result = _run("--site", SITE_KEY, "--update-to-latest")

    assert result.exit_code == 1
    assert f"Nothing is stored yet for site '{SITE_KEY}'" in result.output
    assert "--start" in result.output


@pytest.mark.parametrize(
    ("options", "message"),
    [
        ((), "Give the first day with --start, or --update-to-latest"),
        (("--update-to-latest", "--start", "2025001"), "leave out --start and --end"),
        (("--update-to-latest", "--end", "2025001"), "leave out --start and --end"),
    ],
)
def test_the_dates_must_be_given_one_way(tmp_path, monkeypatch, options, message):
    _site(tmp_path, monkeypatch, [])

    result = _run("--site", SITE_KEY, *options)

    assert result.exit_code == 1
    assert message in result.output


def test_one_site_per_run(tmp_path, monkeypatch):
    _site(tmp_path, monkeypatch, [])

    result = _run("--site", SITE_KEY, "--site", "isengard", "--start", "2025001")

    assert result.exit_code == 1
    assert "one site per run" in result.output
    assert "for site in fangorn isengard; do canvodpy run" in result.output


def test_explicit_dates_process_every_day_in_the_range(tmp_path, monkeypatch):
    days = [_day(4), _day(3)]
    _site(tmp_path, monkeypatch, days)
    _store(
        {
            "canopy_01": [_name("FANA01INK", day) for day in days],
            REFERENCE_GROUP: [_name("FANR01INK", day) for day in days],
        }
    )

    result = _run("--site", SITE_KEY, "--start", days[0], "--end", days[1])

    assert result.exit_code == 0, result.output
    assert "update:" not in result.output
    assert f"'date': '{days[0]}'" in result.output
    assert f"'date': '{days[1]}'" in result.output


class TestPythonApi:
    """``Pipeline.run`` takes the same option, with the same errors."""

    def test_a_run_needs_a_start(self, tmp_path, monkeypatch):
        from canvodpy import Site

        _site(tmp_path, monkeypatch, [])
        with Site(SITE_KEY).pipeline(dry_run=True) as pipeline:
            with pytest.raises(ValueError, match="Give the first day"):
                next(pipeline.run())

    def test_update_to_latest_refuses_dates(self, tmp_path, monkeypatch):
        from canvodpy import Site

        _site(tmp_path, monkeypatch, [])
        with Site(SITE_KEY).pipeline(dry_run=True) as pipeline:
            with pytest.raises(ValueError, match="leave out --start and --end"):
                next(pipeline.run("2025001", update_to_latest=True))

    def test_update_to_latest_on_an_empty_store(self, tmp_path, monkeypatch):
        from canvodpy import Site

        _site(tmp_path, monkeypatch, [_day(2)])
        site = Site(SITE_KEY)
        with site.pipeline(dry_run=True) as pipeline:
            with pytest.raises(NothingStoredError):
                next(pipeline.run(update_to_latest=True))
        assert not site.gnss_store_path.exists()

    def test_the_update_range(self, tmp_path, monkeypatch):
        from canvodpy import Site

        days = [_day(4), _day(3), _day(2)]
        _site(tmp_path, monkeypatch, days)
        _store(
            {
                "canopy_01": [_name("FANA01INK", days[0])],
                REFERENCE_GROUP: [_name("FANR01INK", days[0])],
            }
        )
        with Site(SITE_KEY).pipeline(dry_run=True) as pipeline:
            assert pipeline.update_range() == (days[0], days[2])
