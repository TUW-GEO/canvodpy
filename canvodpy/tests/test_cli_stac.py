"""canvodpy stac: the catalog of the stores, from the terminal."""

from __future__ import annotations

import json

import pytest
import yaml
from canvodpy.cli.app import main_app
from typer.testing import CliRunner

import canvod.config.loader as loader_module
from canvod.utils import testing

runner = CliRunner()


@pytest.fixture(autouse=True)
def _clear_config_cache():
    loader_module.load_config.cache_clear()
    yield
    loader_module.load_config.cache_clear()


def _config_dir(tmp_path, stores_root):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "canvod-settings.yaml").write_text(
        yaml.safe_dump(
            {
                "processing": {
                    "metadata": {
                        "author": testing.PERSON_NAME,
                        "email": testing.PERSON_EMAIL,
                        "institution": testing.INSTITUTION,
                    },
                    "storage": {"stores_root_dir": str(stores_root)},
                },
                "sites": {
                    testing.SITE_KEY: {
                        "gnss_site_data_root": str(tmp_path / "raw"),
                        "receivers": {
                            "canopy_01": {"type": "canopy", "directory": "canopy"},
                        },
                    }
                },
            }
        )
    )
    return config_dir


def test_stac_write_writes_the_catalog_of_the_settings_data_root(tmp_path):
    stores_root = tmp_path / "stores"
    stores_root.mkdir()
    config_dir = _config_dir(tmp_path, stores_root)

    result = runner.invoke(
        main_app, ["stac", "write"], env={"CANVOD_CONFIG_DIR": str(config_dir)}
    )

    assert result.exit_code == 0, result.output
    catalog = stores_root / "catalog.json"
    assert json.loads(catalog.read_text())["type"] == "Catalog"
    assert str(catalog) in result.output.replace("\n", "")


def test_stac_write_root_option_names_another_data_root(tmp_path):
    config_dir = _config_dir(tmp_path, tmp_path / "stores")
    other = tmp_path / "copy"
    other.mkdir()

    result = runner.invoke(
        main_app,
        ["stac", "write", "--root", str(other)],
        env={"CANVOD_CONFIG_DIR": str(config_dir)},
    )

    assert result.exit_code == 0, result.output
    assert (other / "catalog.json").is_file()
    assert not (tmp_path / "stores" / "catalog.json").exists()


def test_stac_write_lists_the_stores_it_cannot_describe_and_exits_1(tmp_path):
    from canvod.store_metadata.testing import (
        create_test_store,
        give_test_metadata,
        write_unchecked,
    )

    stores_root = tmp_path / "stores"
    create_test_store(stores_root / "rohan" / "gnss")
    broken = give_test_metadata(stores_root / "isengard" / "gnss")
    (broken / "repo").write_bytes(b"not an icechunk repository")
    write_unchecked(
        give_test_metadata(stores_root / "mordor" / "gnss"),
        {"publisher.license": "Apache 2"},
    )
    config_dir = _config_dir(tmp_path, stores_root)

    result = runner.invoke(
        main_app, ["stac", "write"], env={"CANVOD_CONFIG_DIR": str(config_dir)}
    )

    assert result.exit_code == 1
    output = result.output.replace("\n", " ")
    assert "3 store(s)" in output
    assert "isengard/gnss: cannot be opened" in output
    assert "mordor/gnss: `publisher.license` 'Apache 2'" in output
    assert "rohan/gnss: has no metadata" in output
    assert "Traceback" not in result.output
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert not (stores_root / "catalog.json").exists()


def test_stac_release_tags_the_stores_and_writes_the_release(tmp_path):
    import numpy as np
    import pandas as pd
    import xarray as xr

    from canvod.store_metadata import (
        commit_with_rebase,
        open_repository,
        write_metadata,
    )
    from canvod.store_metadata.testing import made_up_metadata

    stores_root = tmp_path / "stores"
    store = stores_root / testing.SITE_KEY / "gnss"
    open_repository(store, create=True)
    write_metadata(store, made_up_metadata())
    session = open_repository(store).writable_session("main")
    xr.Dataset(
        {"SNR": (("epoch", "sid"), np.full((3, 1), 40.0, "f4"))},
        coords={
            "epoch": pd.date_range("2025-01-01", periods=3, freq="5s"),
            "sid": ["G01|L1|C"],
        },
    ).to_zarr(session.store, group="canopy_01", consolidated=False)
    commit_with_rebase(session, "observations", store_path=store)
    config_dir = _config_dir(tmp_path, stores_root)

    result = runner.invoke(
        main_app,
        ["stac", "release", "v1"],
        env={"CANVOD_CONFIG_DIR": str(config_dir)},
    )

    assert result.exit_code == 0, result.output
    assert open_repository(store).list_tags() == {"v1"}
    catalog = stores_root / "releases" / "v1" / "catalog.json"
    assert str(catalog) in result.output.replace("\n", "")


def test_stac_release_refuses_a_tag_with_a_slash_and_exits_1(tmp_path):
    config_dir = _config_dir(tmp_path, tmp_path / "stores")

    result = runner.invoke(
        main_app,
        ["stac", "release", "keep/v1"],
        env={"CANVOD_CONFIG_DIR": str(config_dir)},
    )

    assert result.exit_code == 1
    assert "Release tag 'keep/v1' is refused" in result.output.replace("\n", " ")


def _run_without_processing(monkeypatch):
    """Replace the processing of ``canvodpy run`` by a run that succeeds."""
    from canvodpy.cli import run as run_module

    monkeypatch.setattr(run_module, "_main_impl", lambda _args: 0)


def test_run_with_write_catalog_writes_the_catalog_after_the_run(tmp_path, monkeypatch):
    _run_without_processing(monkeypatch)
    stores_root = tmp_path / "stores"
    stores_root.mkdir()
    config_dir = _config_dir(tmp_path, stores_root)

    result = runner.invoke(
        main_app,
        ["run", "--site", testing.SITE_KEY, "--write-catalog"],
        env={"CANVOD_CONFIG_DIR": str(config_dir)},
    )

    assert result.exit_code == 0, result.output
    catalog = stores_root / "catalog.json"
    assert json.loads(catalog.read_text())["type"] == "Catalog"
    assert str(catalog) in result.output.replace("\n", "")


def test_run_without_write_catalog_writes_no_catalog(tmp_path, monkeypatch):
    _run_without_processing(monkeypatch)
    stores_root = tmp_path / "stores"
    stores_root.mkdir()
    config_dir = _config_dir(tmp_path, stores_root)

    result = runner.invoke(
        main_app,
        ["run", "--site", testing.SITE_KEY],
        env={"CANVOD_CONFIG_DIR": str(config_dir)},
    )

    assert result.exit_code == 0, result.output
    assert not (stores_root / "catalog.json").exists()


def test_run_dry_run_writes_no_catalog(tmp_path, monkeypatch):
    _run_without_processing(monkeypatch)
    stores_root = tmp_path / "stores"
    stores_root.mkdir()
    config_dir = _config_dir(tmp_path, stores_root)

    result = runner.invoke(
        main_app,
        ["run", "--site", testing.SITE_KEY, "--dry-run", "--write-catalog"],
        env={"CANVOD_CONFIG_DIR": str(config_dir)},
    )

    assert result.exit_code == 0, result.output
    assert not (stores_root / "catalog.json").exists()


def test_run_failing_writes_no_catalog(tmp_path, monkeypatch):
    from canvodpy.cli import run as run_module

    monkeypatch.setattr(run_module, "_main_impl", lambda _args: 1)
    stores_root = tmp_path / "stores"
    stores_root.mkdir()
    config_dir = _config_dir(tmp_path, stores_root)

    result = runner.invoke(
        main_app,
        ["run", "--site", testing.SITE_KEY, "--write-catalog"],
        env={"CANVOD_CONFIG_DIR": str(config_dir)},
    )

    assert result.exit_code == 1
    assert not (stores_root / "catalog.json").exists()


def test_run_with_a_refused_catalog_keeps_the_data_and_exits_1(tmp_path, monkeypatch):
    from canvod.store_metadata.testing import create_test_store

    _run_without_processing(monkeypatch)
    stores_root = tmp_path / "stores"
    create_test_store(stores_root / "rohan" / "gnss")
    config_dir = _config_dir(tmp_path, stores_root)

    result = runner.invoke(
        main_app,
        ["run", "--site", testing.SITE_KEY, "--write-catalog"],
        env={"CANVOD_CONFIG_DIR": str(config_dir)},
    )

    assert result.exit_code == 1
    output = result.output.replace("\n", " ")
    assert "The run's data is committed" in output
    assert "rohan/gnss: has no metadata" in output
    assert "canvodpy stac write" in output
    assert "Traceback" not in result.output
    assert not (stores_root / "catalog.json").exists()
