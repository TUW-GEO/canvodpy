"""canvodpy store migrate: a site's stores from canVODpy 0.x in one go (#456)."""

from __future__ import annotations

import pytest
import yaml
from canvodpy.cli.app import main_app
from test_cli_store import _env, _write_config, _write_old_form_store
from typer.testing import CliRunner

import canvod.config.loader as loader_module

runner = CliRunner()


@pytest.fixture(autouse=True)
def _clear_config_cache():
    loader_module.load_config.cache_clear()
    yield
    loader_module.load_config.cache_clear()


def _migrate(config_dir, *args, input=None):
    loader_module.load_config.cache_clear()
    yes = [] if input is not None else ["--yes"]
    return runner.invoke(
        main_app,
        ["store", "migrate", "TestSite", *yes, *args],
        env=_env(config_dir),
        input=input,
    )


def _setup(tmp_path, folder="rinex", **settings):
    config_dir = tmp_path / "config"
    stores_root = tmp_path / "stores"
    _write_config(config_dir, stores_root)
    if settings:
        _change_settings(config_dir, settings)
    store_path = stores_root / "TestSite" / folder
    _write_old_form_store(store_path)
    _add_log_book(store_path)
    return config_dir, stores_root / "TestSite"


def _add_log_book(store_path, group="canopy_01") -> None:
    """The log book of the old store's one file, as canVODpy 0.x kept it."""
    import numpy as np
    import zarr

    from canvod.store_metadata import open_repository

    session = open_repository(store_path).writable_session("main")
    table = zarr.open_group(session.store, mode="a").require_group(
        f"{group}/metadata/table"
    )
    start, end = np.array(
        ["2025-01-01T00:00:00", "2025-01-01T00:00:30"], dtype="datetime64[ns]"
    ).astype(np.int64)
    table.create_array("index", data=np.array([0]))
    table.create_array("rinex_hash", data=np.array(["hash0"]))
    table.create_array("action", data=np.array(["initial"]))
    table.create_array("start", data=np.array([start]))
    table.create_array("end", data=np.array([end]))
    session.commit("log book")


def _text(result) -> str:
    """The output in one line: the console wraps long lines."""
    return " ".join(result.output.split())


def _change_settings(config_dir, processing: dict) -> None:
    path = config_dir / "canvod-settings.yaml"
    data = yaml.safe_load(path.read_text())
    for section, values in processing.items():
        data["processing"].setdefault(section, {}).update(values)
    path.write_text(yaml.safe_dump(data))
    loader_module.load_config.cache_clear()


def _add_clock(store_path) -> None:
    """A clock variable, as runs with fetch_clock: true wrote it."""
    import numpy as np
    import zarr

    from canvod.store_metadata import open_repository

    session = open_repository(store_path).writable_session("main")
    group = zarr.open_group(session.store, mode="r+", path="canopy_01")
    clock = group.create_array(
        "clock", shape=(2, 2), dtype="float64", dimension_names=("epoch", "sid")
    )
    clock[:] = np.full((2, 2), 1e-4)
    session.commit("clock")


def _arrays(store_path) -> set[str]:
    import zarr

    from canvod.store_metadata import open_repository

    session = open_repository(store_path).readonly_session(branch="main")
    return set(zarr.open_group(session.store, mode="r", path="canopy_01").array_keys())


def test_a_0x_site_is_moved_to_gnss_and_migrated(tmp_path):
    from canvod.store_metadata import read_repository_metadata

    config_dir, site = _setup(tmp_path)

    result = _migrate(config_dir)

    assert result.exit_code == 0, result.output
    assert not (site / "rinex").exists()
    repository = read_repository_metadata(site / "gnss")
    assert repository["identity"]["id"] == "testsite-gnss"
    assert repository["content_settings"]["origin"] == "migrated"
    again = _migrate(config_dir)
    assert again.exit_code == 0, again.output
    assert "are migrated" in _text(again)


def test_the_plan_is_shown_and_nothing_happens_without_a_yes(tmp_path):
    config_dir, site = _setup(tmp_path)

    result = _migrate(config_dir, input="n\n")

    assert result.exit_code == 1
    assert "rinex/ -> gnss/" in _text(result)
    assert "history" in _text(result)
    assert (site / "rinex").exists()
    assert not (site / "gnss").exists()


def test_a_store_made_with_clk_files_loses_its_clock(tmp_path):
    from canvod.store_metadata import read_repository_metadata

    config_dir, site = _setup(tmp_path, aux_data={"fetch_clock": True})
    _add_clock(site / "rinex")
    _change_settings(config_dir, {"aux_data": {"fetch_clock": False}})

    plan = _migrate(config_dir, input="n\n")
    assert "'clock' of the groups canopy_01" in _text(plan)
    result = _migrate(config_dir)

    assert result.exit_code == 0, result.output
    assert "clock" not in _arrays(site / "gnss")
    content = read_repository_metadata(site / "gnss")["content_settings"]
    assert content["settings"]["processing"]["aux_data"]["fetch_clock"] is False


def test_another_folder_name_needs_the_new_name(tmp_path):
    from canvod.store_metadata import read_repository_metadata

    config_dir, site = _setup(tmp_path, folder="gnss_2024")

    refused = _migrate(config_dir)
    assert refused.exit_code == 1
    assert "--rename gnss_2024=gnss-SUFFIX" in _text(refused)

    bad = _migrate(config_dir, "--rename", "gnss_2024=GNSS-2024")
    assert bad.exit_code == 1
    assert "not allowed" in _text(bad)

    result = _migrate(config_dir, "--rename", "gnss_2024=gnss")
    assert result.exit_code == 0, result.output
    assert read_repository_metadata(site / "gnss")["identity"]["id"] == "testsite-gnss"


def test_rinex_next_to_gnss_is_refused(tmp_path):
    config_dir, site = _setup(tmp_path)
    _write_old_form_store(site / "gnss")

    result = _migrate(config_dir)

    assert result.exit_code == 1
    assert "exists already" in _text(result)
    assert (site / "rinex").exists()


def test_stores_on_s3_need_no_migration(tmp_path):
    config_dir = tmp_path / "config"
    _write_config(config_dir, tmp_path / "stores")
    _change_settings(config_dir, {"storage": {"stores_root_dir": "s3://bucket/x"}})

    result = _migrate(config_dir)

    assert result.exit_code == 1
    assert "need no migration" in _text(result)


def test_a_rerun_with_the_same_values_passes_the_migrated_stores(tmp_path):
    """A run stopped by the VOD store ends with the same line run again."""
    from canvod.store_metadata import read_repository_metadata

    config_dir, site = _setup(tmp_path)
    _write_old_form_store(site / "vod", store_type="vod_store")
    values = [
        "--gnss-set",
        "identity.description=Beech forest observations",
        "--vod-set",
        "identity.description=Beech forest VOD",
    ]

    first = _migrate(config_dir, *values)
    assert first.exit_code == 1, first.output
    assert "no log book" in _text(first)
    _add_log_book(site / "vod", "tau_omega/canopy_01_vs_reference_01")
    again = _migrate(config_dir, *values)

    assert again.exit_code == 0, again.output
    description = read_repository_metadata(site / "vod")["identity"]["description"]
    assert description == "Beech forest VOD"


def test_a_vod_store_left_behind_by_a_stopped_run_follows_on_a_rerun(
    tmp_path, monkeypatch
):
    """Stopped after the clock step, a rerun still moves the VOD store on."""
    from canvod.store_metadata import migration, read_repository_metadata

    config_dir, site = _setup(tmp_path, folder="gnss", aux_data={"fetch_clock": True})
    _add_clock(site / "gnss")
    _write_old_form_store(site / "vod", store_type="vod_store")
    _add_log_book(site / "vod", "tau_omega/canopy_01_vs_reference_01")
    for store in ("gnss", "vod"):
        loader_module.load_config.cache_clear()
        runner.invoke(
            main_app,
            ["store", "migrate-metadata", "TestSite", "--store", store, "--yes"],
            env=_env(config_dir),
        )
    _change_settings(config_dir, {"aux_data": {"fetch_clock": False}})

    def stopped(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(migration, "follow_gnss_content_hash", stopped)
    assert _migrate(config_dir).exit_code != 0
    monkeypatch.undo()
    plan = _migrate(config_dir, input="n\n")
    again = _migrate(config_dir)

    assert "new content-settings hash" in _text(plan)
    assert again.exit_code == 0, again.output
    gnss = read_repository_metadata(site / "gnss")["content_settings"]
    vod = read_repository_metadata(site / "vod")["content_settings"]
    assert vod["gnss_content_hash"] == gnss["hash"]
