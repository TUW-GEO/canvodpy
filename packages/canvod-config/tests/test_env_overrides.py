"""A ``CANVOD__`` environment variable changes the one setting it names."""

from collections.abc import Iterator
from pathlib import Path

import pytest

from canvod.config import load_config
from canvod.utils import testing


@pytest.fixture
def config_dir(tmp_path: Path) -> Iterator[Path]:
    load_config.cache_clear()
    yield testing.write_settings(tmp_path / "config").parent
    load_config.cache_clear()


def test_stores_folder_from_the_environment(config_dir, monkeypatch, tmp_path):
    monkeypatch.setenv(
        "CANVOD__PROCESSING__STORAGE__STORES_ROOT_DIR", str(tmp_path / "elsewhere")
    )

    config = load_config(config_dir=config_dir)

    assert config.processing.storage.stores_root_dir == tmp_path / "elsewhere"
    assert config.processing.metadata.author == testing.PERSON_NAME


def test_days_per_batch_from_the_environment(config_dir, monkeypatch):
    monkeypatch.setenv("CANVOD__PROCESSING__PARAMS__DAYS_PER_BATCH", "7")

    config = load_config(config_dir=config_dir)

    assert config.processing.params.days_per_batch == 7
    assert config.processing.storage.stores_root_dir == config_dir / "stores"


def test_credentials_from_the_environment_keep_the_rest(config_dir, monkeypatch):
    unchanged = load_config(config_dir=config_dir)
    load_config.cache_clear()
    monkeypatch.setenv(
        "CANVOD__PROCESSING__CREDENTIALS__NASA_EARTHDATA_ACC_MAIL", testing.PERSON_EMAIL
    )

    config = load_config(config_dir=config_dir)

    assert config.nasa_earthdata_acc_mail == testing.PERSON_EMAIL
    assert config.sids == unchanged.sids
    assert config.sites == unchanged.sites
