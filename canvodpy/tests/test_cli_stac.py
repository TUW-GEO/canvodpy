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
